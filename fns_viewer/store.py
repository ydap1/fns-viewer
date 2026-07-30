"""The SQLite index: building it, keeping it fresh, and querying it.

Free-text search runs through an FTS5 table rather than `LIKE '%…%'`. On the
694 790-record index the old substring scan cost about 1.1 s and ran twice per
request (once to count, once to page); the inverted index answers both in
single-digit milliseconds, which is what makes the data set growable.
"""
from __future__ import annotations

import mmap
import re
import sqlite3
import time

from .config import DB, PAGE_SIZE, SORT_COLUMNS, TAX_LIST_IDS, XML, revision
from .xmlsource import START_TAG, attrs, source_stamp

SCHEMA = """
  PRAGMA journal_mode=OFF;
  PRAGMA synchronous=OFF;
  CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  CREATE TABLE records (
    id TEXT PRIMARY KEY, offset INTEGER NOT NULL, region_id TEXT,
    tax_id TEXT, period TEXT, municipality TEXT, law TEXT
  );
  CREATE INDEX records_filters ON records(region_id, tax_id, period);
  -- Period is the default ordering, so every visitor pays for it: without this
  -- the opening screen sorts all 694 790 rows (403 ms measured, now 1 ms) and
  -- it costs 14 MB. Indexes for the other sort columns were measured too and
  -- dropped: they saved ~70 ms each and cost over 300 MB together.
  CREATE INDEX records_period ON records(period DESC, id DESC);
  CREATE TABLE list_values (id TEXT PRIMARY KEY, value TEXT NOT NULL);
  -- Contentless: the text is only ever matched, never read back, so storing a
  -- second copy of it would just double the index for nothing.
  CREATE VIRTUAL TABLE records_fts USING fts5(
    text, content='', tokenize='unicode61 remove_diacritics 2', prefix='2 3'
  );
"""
WORD = re.compile(r"[^\W_]+", re.UNICODE)


def connect(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, check_same_thread=False)
    else:
        con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def match_expression(text: str) -> str | None:
    """Turn a typed phrase into an FTS5 prefix query, or None if it has no words.

    Every token must match, and the last-typed word is treated as a prefix so
    results narrow while the user is still typing.
    """
    tokens = WORD.findall(text or '')
    if not tokens:
        return None
    return ' AND '.join(f'"{token}"*' for token in tokens)


def build_index() -> None:
    if not XML.exists():
        raise SystemExit(f"Не найден файл {XML}")
    if DB.exists():
        for attempt in range(5):
            try:
                DB.unlink()
                break
            except PermissionError:
                if attempt == 4:
                    raise SystemExit(
                        "Не удалось обновить индекс: файл tax_viewer_index.sqlite3 "
                        "занят другой программой. Закройте другие окна просмотрщика, "
                        "программы для SQLite и повторите запуск через несколько секунд."
                    )
                time.sleep(1)
    con = connect()
    con.executescript(SCHEMA)
    started = time.monotonic()
    count = 0
    batch: list[tuple] = []
    text_batch: list[tuple] = []

    def flush() -> None:
        con.executemany("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        con.executemany("INSERT INTO records_fts(rowid, text) VALUES (?, ?)", text_batch)
        con.commit()
        batch.clear()
        text_batch.clear()

    with XML.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as data:
        # The List section comes first and is tiny. It provides names for regions
        # and tax IDs used by TaxPlace records.
        list_end = data.find(b"</List>")
        if list_end != -1:
            for match in re.finditer(rb"<li\s+([^>]*?)/>", data[:list_end]):
                a = attrs(match.group(1))
                if a.get("ID") and a.get("List_value"):
                    con.execute("INSERT OR REPLACE INTO list_values VALUES (?, ?)",
                                (a["ID"], a["List_value"]))
        for match in START_TAG.finditer(data):
            a = attrs(match.group(1))
            ident = a.get("ID")
            if not ident:
                continue
            count += 1
            municipality = a.get("MunObraz", "")
            law = a.get("LawDoc", "")
            batch.append((ident, match.start(), a.get("Region_ID", ""), a.get("Nalog_ID", ""),
                          a.get("TaxPeriod", ""), municipality, law))
            text_batch.append((count, " ".join((municipality, law, a.get("TaxOrganCode", "")))))
            if len(batch) == 5000:
                flush()
                if count % 50000 == 0:
                    print(f"Проиндексировано {count:,} записей за {time.monotonic() - started:.0f} с",
                          flush=True)
        if batch:
            flush()
    con.execute("INSERT INTO metadata VALUES ('source_stamp', ?)", (source_stamp(),))
    con.execute("INSERT INTO metadata VALUES ('records', ?)", (str(count),))
    con.commit()
    con.execute("INSERT INTO records_fts(records_fts) VALUES ('optimize')")
    con.commit()
    con.close()
    print(f"Индекс готов: {count:,} записей за {time.monotonic() - started:.0f} с", flush=True)


def ensure_index() -> None:
    con: sqlite3.Connection | None = None
    try:
        con = connect()
        row = con.execute("SELECT value FROM metadata WHERE key='source_stamp'").fetchone()
        if row and row[0] == source_stamp():
            con.execute("SELECT 1 FROM records_fts LIMIT 1").fetchone()
            return
    except sqlite3.Error:
        pass
    finally:
        if con is not None:
            con.close()
    print("Создаётся локальный индекс (только при первом запуске или после изменения data.xml)…",
          flush=True)
    build_index()


def query(params: dict[str, list[str]]) -> tuple[str, list, str]:
    """Build the FROM/WHERE clause, its arguments, and the ORDER BY for a search."""
    source = "records"
    filters: list[str] = []
    args: list = []
    expression = match_expression(params.get('q', [''])[0].strip())
    if expression:
        source = "records JOIN records_fts ON records_fts.rowid = records.rowid"
        filters.append("records_fts MATCH ?")
        args.append(expression)
    for column, key in [('region_id', 'region'), ('tax_id', 'tax'), ('period', 'period')]:
        value = params.get(key, [''])[0].strip()
        if value:
            filters.append(f'{column} = ?')
            args.append(value)
    where = ' WHERE ' + ' AND '.join(filters) if filters else ''
    column = SORT_COLUMNS.get(params.get('sort', ['period'])[0], 'period')
    direction = 'ASC' if params.get('dir', ['desc'])[0].lower() == 'asc' else 'DESC'
    return f' FROM {source}{where}', args, f'{column} {direction}, records.id DESC'


def search(con: sqlite3.Connection, params: dict[str, list[str]]) -> dict:
    clause, args, order = query(params)
    total = con.execute(f'SELECT count(*){clause}', args).fetchone()[0]
    page = max(0, int(params.get('page', ['0'])[0] or 0))
    rows = con.execute(
        f'SELECT records.id, region_id, tax_id, period, municipality, law{clause}'
        f' ORDER BY {order} LIMIT ? OFFSET ?', args + [PAGE_SIZE, page * PAGE_SIZE]).fetchall()
    names = list_values(con)
    return {
        'count': total,
        'page': page,
        'pageSize': PAGE_SIZE,
        'rows': [{'id': r['id'],
                  'region': names.get(r['region_id'], r['region_id']),
                  'tax': names.get(r['tax_id'], r['tax_id']),
                  'period': r['period'],
                  'municipality': r['municipality'],
                  'law': r['law']} for r in rows],
    }


def list_values(con: sqlite3.Connection) -> dict[str, str]:
    return {r['id']: r['value'] for r in con.execute('SELECT id, value FROM list_values')}


def options(con: sqlite3.Connection) -> dict:
    values = con.execute("SELECT id, value FROM list_values").fetchall()
    # Region values start with a two-digit code; known tax IDs are the tax names.
    regions = [(r['id'], r['value']) for r in values if re.match(r"^\d\d\s*-", r['value'])]
    taxes = [(r['id'], r['value']) for r in values if r['id'] in TAX_LIST_IDS]
    periods = [r[0] for r in con.execute(
        "SELECT DISTINCT period FROM records WHERE period <> '' ORDER BY period DESC")]
    total = con.execute("SELECT value FROM metadata WHERE key='records'").fetchone()
    return {'regions': sorted(regions, key=lambda item: item[1]),
            'taxes': taxes,
            'periods': periods,
            'total': int(total[0]) if total else 0,
            'revision': revision()}
