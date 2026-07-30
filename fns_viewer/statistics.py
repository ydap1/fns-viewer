"""Form 5-МН — what was actually assessed, next to the rates data.xml sets.

`data.xml` holds what regional and municipal law *establishes*: rates, objects,
exemptions. Form 5-МН («Отчет о налоговой базе и структуре начислений по местным
налогам») holds what came of it — taxpayer counts, taxable base, tax charged,
relief granted — for land tax and individual property tax.

Granularity is the subject of the Federation. The form has a «Муниципальное
образование» field, but every published copy aggregates to the region, so a
municipal document is shown its region's totals and the interface says so.

Source: the federal section of
https://www.nalog.gov.ru/rnNN/related_activities/statistics_and_analytics/forms/
publishes one archive per year holding all regions at once, so a full import is
about fifteen downloads rather than one per region.
"""
from __future__ import annotations

import csv
import gzip
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from .config import PACKAGE

# Committed to the repository rather than downloaded by each user: it is 1.1 MB
# gzipped, and shipping it means `git pull` delivers the statistics the same way
# it delivers the code — no import step, no network, no pip install. Only
# whoever refreshes it for a new year needs xlrd and a built XML index.
DATA = PACKAGE / "data"
VALUES_FILE = DATA / "5mn-values.csv.gz"
INDICATORS_FILE = DATA / "5mn-indicators.csv.gz"

FORMS_URL = "https://www.nalog.gov.ru/rn77/related_activities/statistics_and_analytics/forms/"
USER_AGENT = "fns-viewer/2.1 (local tax rate viewer; +https://github.com/ydap1/fns-viewer)"
POLITE_DELAY = 1.0  # seconds between requests to nalog.gov.ru
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

SECTIONS = {
    1: "Земельный налог — организации",
    2: "Земельный налог — физические лица",
    3: "Налог на имущество физических лиц",
}
# Rows that are totals or grouping headers rather than a subject of the Federation.
NOT_A_REGION = re.compile(
    r"федеральн\w*\s+округ|российская\s+федерация|в\s+том\s+числе|примечание"
    r"|субъекты|итого|всего|^\s*$", re.I)
# These sheets are typed by hand and contain Latin letters that look Cyrillic:
# "Ямало-Hенецкий" carries a Latin H. Fold them before comparing names.
CONFUSABLES = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")
# The statistics spell a few subjects differently from the classifier data.xml uses.
ALIASES = {
    "чувашская": "21",
    "кемеровская кузбасс": "42",
    "севастополь": "92",
    "ханты мансийский юграа": "86",
    "ханты мансийский югра": "86",
}

_loaded: dict | None = None


def _read(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        yield from csv.DictReader(handle)


def load() -> dict:
    """Read the shipped tables into memory once. 249k rows is about 30 MB."""
    global _loaded
    if _loaded is not None:
        return _loaded
    values: dict[str, dict[int, dict[int, list]]] = {}
    labels: dict[tuple[int, str], str] = {}
    if VALUES_FILE.exists():
        for row in _read(VALUES_FILE):
            amount = row["amount"]
            (values.setdefault(row["region"], {})
                   .setdefault(int(row["year"]), {})
                   .setdefault(int(row["section"]), [])
                   .append((row["code"], float(amount) if amount != "" else None)))
    if INDICATORS_FILE.exists():
        for row in _read(INDICATORS_FILE):
            labels[(int(row["section"]), row["code"])] = row["label"]
    _loaded = {"values": values, "labels": labels}
    return _loaded


def save(values, indicators) -> None:
    """Write the two shipped tables. Only the refresh path calls this."""
    DATA.mkdir(exist_ok=True)

    def write(path, header, rows):
        # mtime=0 keeps the gzip byte-identical when the data has not changed,
        # so an unchanged refresh does not show up as a diff.
        with gzip.GzipFile(path, "wb", compresslevel=9, mtime=0) as raw:
            writer = csv.writer(io.TextIOWrapper(raw, "utf-8", newline=""))
            writer.writerow(header)
            writer.writerows(rows)

    write(VALUES_FILE, ["year", "section", "region", "code", "amount"], values)
    write(INDICATORS_FILE, ["section", "code", "label"], indicators)


def normalise(name: str) -> str:
    """Reduce a subject's name to something both sources agree on."""
    text = re.sub(r"\(.*?\)", " ", str(name or "")).translate(CONFUSABLES).lower()
    text = text.replace("ё", "е")
    text = text.replace("автономный округ", "ао").replace("автономная область", "аобл")
    # "г.Москва" has no space after the dot; the dot is what makes it an
    # abbreviation, so requiring it stops this from eating "город Москва".
    text = re.sub(r"^\s*г\.\s*|^\s*г\s+", " ", text)
    text = re.sub(r"\b(область|обл|край|республика|респ|город|федеральная территория)\b", " ", text)
    text = re.sub(r"[^а-яa-z0-9]+", " ", text)
    return " ".join(text.split())


def region_lookup(names: dict[str, str]) -> dict[str, str]:
    """Map normalised subject name -> two-digit code, from data.xml's own list."""
    table = {normalise(name): code for code, name in names.items()}
    table.update(ALIASES)
    return table


# ---------------------------------------------------------------- spreadsheets

def _xlsx_sheets(blob: bytes) -> list[list[dict[str, str]]]:
    """Every worksheet of an .xlsx as {column letter: text} rows."""
    book = zipfile.ZipFile(io.BytesIO(blob))
    shared: list[str] = []
    if "xl/sharedStrings.xml" in book.namelist():
        shared = ["".join(t.text or "" for t in item.iter(NS + "t"))
                  for item in ET.fromstring(book.read("xl/sharedStrings.xml"))]
    names = sorted((n for n in book.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                   key=lambda n: int(re.search(r"(\d+)", n).group(1)))
    sheets = []
    for name in names:
        rows = []
        for row in ET.fromstring(book.read(name)).iter(NS + "row"):
            cells: dict[str, str] = {}
            for cell in row.iter(NS + "c"):
                column = re.match(r"([A-Z]+)", cell.get("r") or "A").group(1)
                node = cell.find(NS + "v")
                text = node.text if node is not None else None
                if cell.get("t") == "s" and text is not None:
                    text = shared[int(text)]
                elif cell.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(NS + "t"))
                if text not in (None, ""):
                    cells[column] = str(text).strip()
            rows.append(cells)
        sheets.append(rows)
    return sheets


def _xls_sheets(blob: bytes) -> list[list[dict[str, str]]]:
    """Same shape for genuine binary .xls. Needs xlrd."""
    try:
        import xlrd  # noqa: PLC0415 - optional, only the binary years need it
    except ImportError:
        raise RuntimeError(
            "Для файлов в старом формате .xls нужен модуль xlrd: "
            "pip install -r requirements.txt"
        ) from None
    book = xlrd.open_workbook(file_contents=blob)
    sheets = []
    for sheet in book.sheets():
        rows = []
        for index in range(sheet.nrows):
            cells = {}
            for column, cell in enumerate(sheet.row(index)):
                text = cell.value
                if text in (None, ""):
                    continue
                # xlrd hands back every number as a float, so the row code 1100
                # arrives as "1100.0" and stops looking like a code.
                if isinstance(text, float) and text.is_integer():
                    text = str(int(text))
                cells[_column_letter(column + 1)] = str(text).strip()
            rows.append(cells)
        sheets.append(rows)
    return sheets


def sheets_of(blob: bytes) -> list[list[dict[str, str]]]:
    """Read a workbook, trusting its magic bytes rather than its file name.

    The tax service publishes .xlsx files named .xls often enough that going by
    the extension throws XLRDError on perfectly good data.
    """
    if blob[:2] == b"PK":
        return _xlsx_sheets(blob)
    if blob[:4] == b"\xd0\xcf\x11\xe0":
        return _xls_sheets(blob)
    raise ValueError("нераспознанный формат файла")


def _column_letter(number: int) -> str:
    name = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _number(text: str) -> float | None:
    # Values arrive as "121 732 606", "1 234,5", or "Х" where the figure is
    # suppressed because a single taxpayer would be identifiable.
    cleaned = re.sub(r"[\s ]", "", str(text or "")).replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


# «РАЗДЕЛ ΙΙI» mixes Greek capital iota with Latin I inside one numeral, so the
# numeral is folded to Latin before it is counted.
ROMAN = {"I": 1, "II": 2, "III": 3}
IOTA = str.maketrans("Ιι", "Ii")


def section_of(name: str, rows: list[dict[str, str]]) -> int | None:
    """Which РАЗДЕЛ this sheet is, from its file name or its own title row."""
    found = re.search(r"Раздел\s*([123])", name, re.I)
    if found:
        return int(found.group(1))
    head = " ".join(v for cells in rows[:4] for v in cells.values())
    found = re.search(r"РАЗДЕЛ\s+([IΙ]{1,3})(?![IΙ])", head, re.I)
    if found:
        return ROMAN.get(found.group(1).translate(IOTA).upper())
    for keyword, number in (("земельному налогу по организациям", 1),
                            ("земельному налогу по физическим", 2),
                            ("имущество физических", 3)):
        if keyword in head.lower():
            return number
    return None


def parse_sheet(rows: list[dict[str, str]], name: str) -> tuple[list[tuple[str, int, str]], list[tuple[str, str, float | None]]]:
    """Return (indicators, values) for one Раздел sheet.

    The sheet carries a stacked header: several rows of prose, then a row of
    stable numeric row codes (1100, 1110, …), then one row per subject.
    """
    header_at = None
    for index, cells in enumerate(rows[:25]):
        codes = [v for k, v in cells.items() if k != "A" and re.fullmatch(r"\d{3,4}", v or "")]
        if len(codes) >= 3:
            header_at = index
            break
    if header_at is None:
        raise ValueError(f"{name}: не найдена строка с кодами показателей")

    code_of = {column: text for column, text in rows[header_at].items()
               if column != "A" and re.fullmatch(r"\d{3,4}", text or "")}
    # Build a label per column from the prose rows stacked above the codes.
    indicators = []
    for position, (column, code) in enumerate(sorted(code_of.items(), key=lambda kv: (len(kv[0]), kv[0]))):
        parts = [rows[i].get(column, "") for i in range(header_at)]
        label = " · ".join(" ".join(p.split()) for p in parts if p)
        indicators.append((code, position, label or f"Показатель {code}"))

    values = []
    for cells in rows[header_at + 1:]:
        subject = cells.get("A", "")
        if not subject or NOT_A_REGION.search(subject):
            continue
        for column, code in code_of.items():
            if column in cells:
                values.append((subject, code, _number(cells[column])))
    return indicators, values


# ---------------------------------------------------------------- downloading

def _fetch(url: str, timeout: int = 120) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def discover() -> dict[int, str]:
    """Find the per-year archive of 5-МН broken down by subject.

    Older years link straight to a file; from 2012 the year links to a page that
    holds it. The archive whose name ends in `reg` is the one with every subject
    in it — the plain file is the Russia total only.
    """
    page = _fetch(FORMS_URL).decode("utf-8", "replace")
    boundary = [m.start() for m in re.finditer("Отчеты, сформированные УФНС", page)]
    federal = page[:boundary[-1]] if boundary else page
    # The table markup is not well-formed enough to split on <tr>: doing so
    # hands 5-МН the year links belonging to 5-ТИ. Slice between form labels.
    labels = [(m.start(), m.group(1)) for m in re.finditer(r">\s*(\d{1,2}-[А-ЯЁ]{2,5})\s*<", federal)]
    position = next((i for i, (_, code) in enumerate(labels) if code == "5-МН"), None)
    if position is None:
        raise RuntimeError("На странице ФНС не найдена строка формы 5-МН")
    start = labels[position][0]
    end = labels[position + 1][0] if position + 1 < len(labels) else len(federal)
    row = federal[start:end]

    found: dict[int, str] = {}
    for href, year in re.findall(r'href="([^"]+)"[^>]*>\s*(\d{4})\s*<', row):
        target = urllib.parse.urljoin(FORMS_URL, href)
        if re.search(r"\.(xlsx?|zip)$", target, re.I):
            found[int(year)] = target
            continue
        try:
            time.sleep(POLITE_DELAY)
            sub = _fetch(target).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError):
            continue
        files = [urllib.parse.urljoin(target, h)
                 for h in re.findall(r'href="([^"]+\.(?:xlsx?|zip))"', sub, re.I)]
        # The per-subject archive is the one with "reg" in its name, but the
        # suffix varies: reg.zip, reg_.zip, reg_m.zip, regut.zip. Without it
        # the only file on the page is the Russia total, which has no regions
        # in it at all, so such a year is skipped rather than half-imported.
        regional = [f for f in files if "reg" in f.rsplit("/", 1)[-1].lower()]
        if regional:
            found[int(year)] = regional[0]
    return dict(sorted(found.items()))


def _is_archive(blob: bytes) -> bool:
    """A zip of workbooks, as opposed to an .xlsx (which is also a zip)."""
    if blob[:2] != b"PK":
        return False
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    return not any(n.startswith("xl/") for n in names)


def workbooks(blob: bytes, url: str) -> list[tuple[str, bytes]]:
    """Split a download into (name, bytes) workbooks, unwrapping an archive."""
    if _is_archive(blob):
        archive = zipfile.ZipFile(io.BytesIO(blob))
        return [(n, archive.read(n)) for n in archive.namelist()
                if re.search(r"\.xlsx?$", n, re.I)]
    return [(url.rsplit("/", 1)[-1], blob)]


def parse_year(blob: bytes, url: str) -> list[tuple[int, list, list]]:
    """Every (section, indicators, values) a year's download contains.

    A year arrives either as an archive of one workbook per Раздел, or as a
    single workbook holding the three Разделы as separate sheets.
    """
    out = []
    problems = []
    for name, book in workbooks(blob, url):
        try:
            sheets = sheets_of(book)
        except (ValueError, RuntimeError, zipfile.BadZipFile) as error:
            # One unreadable Раздел must not cost the other two: without xlrd
            # the 2012-2014 archives still yield everything that is .xlsx.
            problems.append(f"{name}: {error}")
            continue
        for rows in sheets:
            section = section_of(name, rows)
            if section is None:
                continue
            try:
                indicators, values = parse_sheet(rows, name)
            except ValueError:
                continue
            if values:
                out.append((section, indicators, values))
    if not out and problems:
        raise ValueError("; ".join(problems[:2]))
    return out, problems


def update(years: list[int] | None = None, progress=print) -> int:
    """Download and store 5-МН. Returns the number of stored figures."""
    import sqlite3  # noqa: PLC0415 - only the refresh path touches the index

    from . import store  # local import: statistics can be imported without an index
    from .config import DB

    # The subject names come from data.xml's own classifier, so the index has to
    # exist. Users never hit this: they get the finished tables from git.
    try:
        with store.connect(readonly=True) as index:
            names = {}
            for row in index.execute("SELECT value FROM list_values"):
                found = re.match(r"^(\d\d)\s*-\s*(.+)$", row[0])
                if found:
                    names[found.group(1)] = found.group(2).strip()
    except sqlite3.Error:
        raise SystemExit(
            f"Для обновления статистики нужен индекс {DB}: он даёт названия регионов.\n"
            "Положите data.xml рядом с viewer.py и запустите его один раз, "
            "затем повторите обновление."
        ) from None
    lookup = region_lookup(names)

    progress("Поиск файлов формы 5-МН на nalog.gov.ru…")
    found_years = discover()
    wanted = sorted(y for y in found_years if years is None or y in years)
    progress(f"Найдено лет: {len(found_years)}, будет загружено: {len(wanted)}")

    all_values: list[tuple] = []
    indicator_labels: dict[tuple[int, str], str] = {}
    stored = 0
    unmatched: set[str] = set()
    for year in wanted:
        url = found_years[year]
        try:
            time.sleep(POLITE_DELAY)
            blob = _fetch(url)
        except (urllib.error.URLError, TimeoutError) as error:
            progress(f"  {year}: не загрузилось ({error})")
            continue
        try:
            parsed, problems = parse_year(blob, url)
        except Exception as error:  # noqa: BLE001 - one bad year must not end the run
            progress(f"  {year}: не разобрано — {error}")
            continue
        for problem in problems:
            progress(f"  {year}: пропущен {problem}")
        before = stored
        for section, indicators, values in parsed:
            for code, _position, label in indicators:
                indicator_labels.setdefault((section, code), label)
            rows = []
            for subject, code, amount in values:
                region = lookup.get(normalise(subject))
                if region is None:
                    unmatched.add(subject)
                    continue
                rows.append((year, section, region, code,
                             "" if amount is None else
                             int(amount) if float(amount).is_integer() else amount))
            all_values.extend(rows)
            stored += len(rows)
        got = sorted({s for s, _, _ in parsed})
        progress(f"  {year}: разделы {got or '—'}, показателей {stored - before:,}")

    if not all_values:
        progress("Ничего не загружено — файлы оставлены без изменений.")
        return 0
    all_values.sort(key=lambda row: (row[0], row[1], row[2], int(row[3])))
    save(all_values, [(section, code, label)
                      for (section, code), label in sorted(indicator_labels.items(),
                                                           key=lambda kv: (kv[0][0], int(kv[0][1])))])
    if unmatched:
        progress(f"Не сопоставлено с регионами: {', '.join(sorted(unmatched)[:8])}")
    progress(f"Сохранено показателей: {stored:,} → {VALUES_FILE.name}, {INDICATORS_FILE.name}")
    progress("Не забудьте закоммитить их, чтобы данные приехали всем по git pull.")
    return stored


# ---------------------------------------------------------------- reading back

def available() -> bool:
    return VALUES_FILE.exists()


def for_region(region: str, year: str | int | None) -> dict:
    """Every figure for one subject, for the closest year at or before `year`."""
    table = load()
    by_year = table["values"].get(region, {})
    years = sorted(by_year)
    if not years:
        return {'years': [], 'year': None, 'sections': []}
    try:
        wanted = int(year)
    except (TypeError, ValueError):
        wanted = years[-1]
    chosen = max((y for y in years if y <= wanted), default=years[0])

    labels = table["labels"]
    sections = []
    for number in sorted(SECTIONS):
        rows = by_year[chosen].get(number)
        if not rows:
            continue
        items = []
        for code, amount in sorted(rows, key=lambda row: int(row[0])):
            label = labels.get((number, code), code)
            items.append({'code': code, 'label': tidy_label(label),
                          'headline': bool(HEADLINE.match(label)), 'amount': amount})
        sections.append({'section': number, 'title': SECTIONS[number], 'items': items})
    return {'years': years, 'year': chosen, 'sections': sections}


# The form numbers its own top-level rows ("1.Количество налогоплательщиков",
# "4. Налоговая база"). Everything else is a breakdown of one of those, so the
# numbering is exactly the split between headline figures and detail.
HEADLINE = re.compile(r"^\s*\d+(\.\d+)?\s*[.)]")


def tidy_label(label: str) -> str:
    text = " ".join(str(label or "").split())
    # Drop the cross-references the form uses to point back up its own hierarchy.
    text = re.sub(r"\s*·\s*", " · ", text)
    return text or "—"
