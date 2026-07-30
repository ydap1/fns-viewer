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
VALUES_FILE = DATA / "stats-values.csv.gz"
INDICATORS_FILE = DATA / "stats-indicators.csv.gz"
SECTIONS_FILE = DATA / "stats-sections.csv.gz"

# The three forms that correspond to taxes data.xml actually carries.
FORMS = {
    "5-МН": ("Местные налоги", ("2803", "2805")),
    "5-НИО": ("Налог на имущество организаций", ("2804",)),
    "5-ТН": ("Транспортный налог", ("2802",)),
}

FORMS_URL = "https://www.nalog.gov.ru/rn77/related_activities/statistics_and_analytics/forms/"
USER_AGENT = "fns-viewer/2.1 (local tax rate viewer; +https://github.com/ydap1/fns-viewer)"
POLITE_DELAY = 1.0  # seconds between requests to nalog.gov.ru
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"

# Section titles are read out of each sheet's own heading, except for 5-МН,
# whose Разделы are named only in the workbook's first page.
KNOWN_TITLES = {
    ("5-МН", 1): "Земельный налог — организации",
    ("5-МН", 2): "Земельный налог — физические лица",
    ("5-МН", 3): "Налог на имущество физических лиц",
    ("5-НИО", 1): "Налог на имущество организаций — по декларациям",
    ("5-НИО", 2): "Налог на имущество организаций — льготы и вычеты",
    ("5-ТН", 1): "Транспортный налог — организации",
    ("5-ТН", 2): "Транспортный налог — физические лица",
}
# Which tax each section actually reports on. 5-МН covers two different taxes
# across its three Разделы, so a land-tax document has no business showing the
# individual-property section, and vice versa.
SECTION_TAXES = {
    ("5-МН", 1): ("2803",),
    ("5-МН", 2): ("2803",),
    ("5-МН", 3): ("2805",),
    ("5-НИО", 1): ("2804",),
    ("5-НИО", 2): ("2804",),
    ("5-ТН", 1): ("2802",),
    ("5-ТН", 2): ("2802",),
}
# Rows that are totals or grouping headers rather than a subject of the Federation.
NOT_A_REGION = re.compile(
    r"федеральн\w*\s+округ|российская\s+федерация|в\s+том\s+числе|примечание"
    r"|субъекты|итого|всего|начальник|управлени|^\s*$", re.I)
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
    """Read the shipped tables into memory once."""
    global _loaded
    if _loaded is not None:
        return _loaded
    values: dict[str, dict[int, dict[str, dict[int, list]]]] = {}
    labels: dict[tuple[str, int, str], str] = {}
    titles: dict[tuple[str, int], str] = {}
    if VALUES_FILE.exists():
        for row in _read(VALUES_FILE):
            amount = row["amount"]
            (values.setdefault(row["region"], {})
                   .setdefault(int(row["year"]), {})
                   .setdefault(row["form"], {})
                   .setdefault(int(row["section"]), [])
                   .append((row["code"], float(amount) if amount != "" else None)))
    if INDICATORS_FILE.exists():
        for row in _read(INDICATORS_FILE):
            labels[(row["form"], int(row["section"]), row["code"])] = row["label"]
    if SECTIONS_FILE.exists():
        for row in _read(SECTIONS_FILE):
            titles[(row["form"], int(row["section"]))] = row["title"]
    _loaded = {"values": values, "labels": labels, "titles": titles}
    return _loaded


def save(values, indicators, sections) -> None:
    """Write the shipped tables. Only the refresh path calls this."""
    DATA.mkdir(exist_ok=True)

    def write(path, header, rows):
        # mtime=0 keeps the gzip byte-identical when the data has not changed,
        # so an unchanged refresh does not show up as a diff.
        with gzip.GzipFile(path, "wb", compresslevel=9, mtime=0) as raw:
            text = io.TextIOWrapper(raw, "utf-8", newline="")
            writer = csv.writer(text)
            writer.writerow(header)
            writer.writerows(rows)
            # Closing the GzipFile does not drain the text buffer above it: that
            # silently truncated the tail of every table and left the smallest
            # one empty, because its content never filled a buffer at all.
            text.flush()
            text.detach()

    write(VALUES_FILE, ["form", "year", "section", "region", "code", "amount"], values)
    write(INDICATORS_FILE, ["form", "section", "code", "label"], indicators)
    write(SECTIONS_FILE, ["form", "section", "title"], sections)


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
    # The code row is the last one in the header zone that is followed by a
    # subject name. Matching the first row of 3-4 digit numbers instead picks up
    # 5-ТН data rows, whose leading figures look exactly like row codes.
    # Below the code row come "РОССИЙСКАЯ ФЕДЕРАЦИЯ", "в том числе:" and a
    # federal district before the first real subject, so the lookahead has to
    # reach past them or the genuine code row is rejected.
    def is_subject(cells: dict[str, str]) -> bool:
        first = cells.get("A", "")
        return bool(first) and not re.fullmatch(r"[\d\s.,]+", first) and not NOT_A_REGION.search(first)

    def candidates(pattern):
        for index, cells in enumerate(rows[:25]):
            codes = [v for k, v in cells.items() if k != "A" and re.fullmatch(pattern, v or "")]
            if len(codes) >= 3 and any(is_subject(l) for l in rows[index + 1:index + 10]):
                yield index

    # Four digits first: 5-ТН data rows open with three-digit figures that look
    # exactly like row codes, so the loose pattern is only a fallback.
    header_at = next(candidates(r"\d{4}"), None)
    width = r"\d{4}"
    if header_at is None:
        header_at = next(candidates(r"\d{3,4}"), None)
        width = r"\d{3,4}"
    if header_at is None:
        raise ValueError(f"{name}: не найдена строка с кодами показателей")

    code_of = {column: text for column, text in rows[header_at].items()
               if column != "A" and re.fullmatch(width, text or "")}
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


def parse_single_region(rows: list[dict[str, str]]) -> list[tuple[int, str, str, float | None]]:
    """Read a one-region workbook, where indicators run down the page.

    The federal archives put subjects in rows and indicators in columns; the
    УФНС files for 2009-2011 do the opposite — «Показатели | Код строки |
    Значение показателя», with each Раздел introduced by its own heading.
    """
    out: list[tuple[int, str, str, float | None]] = []
    section = None
    pending: list[str] = []
    for cells in rows:
        first = " ".join(str(cells.get("A", "")).split())
        heading = re.search(r"Раздел\s+([IΙ]{1,3})\b", first, re.I)
        if heading:
            section = ROMAN.get(heading.group(1).translate(IOTA).upper())
            pending = []
            continue
        code = str(cells.get("B", "")).strip()
        # Four digits only: the header block of these files also carries three
        # digit fields (ОКАТО, код налогового органа) in the same column, and
        # they are not indicators.
        if not re.fullmatch(r"\d{4}", code):
            # Text with no code of its own is a sub-heading for the rows below,
            # except the table's own column headings.
            if first and len(first) > 3 and not TABLE_HEADING.match(first):
                pending = [first]
            continue
        if section is None:
            continue
        label = " · ".join([*pending, first]) if first else " · ".join(pending)
        out.append((section, code, label or code, _number(cells.get("C"))))
        pending = []
    return out


TABLE_HEADING = re.compile(r"^(показател|код строки|значение показател|наименование)", re.I)
REGIONAL_URL = "https://www.nalog.gov.ru/rn{code}/related_activities/statistics_and_analytics/forms/"


def regional_sources(codes, forms, years, progress=print) -> dict:
    """Crawl every regional page for the years the federal section lacks."""
    found: dict[str, dict[str, dict[int, str]]] = {}
    for position, code in enumerate(codes, 1):
        url = REGIONAL_URL.format(code=code)
        try:
            time.sleep(POLITE_DELAY)
            page = _fetch(url, timeout=60).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            progress(f"  rn{code}: страница недоступна ({error})")
            continue
        marks = [m.start() for m in re.finditer("Отчеты, сформированные УФНС", page)]
        if not marks:
            continue
        regional = page[marks[-1]:]
        per_form: dict[str, dict[int, str]] = {}
        for form in forms:
            row = form_row(regional, form)
            if row is None:
                continue
            links = {}
            for href, year in re.findall(r'href="([^"]+)"[^>]*>\s*(\d{4})\s*[;.]?\s*<', row):
                if int(year) in years:
                    links.setdefault(int(year), urllib.parse.urljoin(url, href))
            if links:
                per_form[form] = links
        if per_form:
            found[code] = per_form
        if position % 15 == 0:
            progress(f"  просмотрено регионов: {position}/{len(codes)}")
    return found


# ---------------------------------------------------------------- downloading

def _fetch(url: str, timeout: int = 120) -> bytes:
    # Some published paths contain raw spaces and Cyrillic, which urllib rejects
    # outright ("URL can't contain control characters"), so escape the path.
    split = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(split._replace(
        path=urllib.parse.quote(split.path, safe="/%"),
        query=urllib.parse.quote(split.query, safe="=&%")))
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# A form label is written either as its own cell (>5-МН<) or inline as №5-МН.
# Missing the second spelling is what made Moscow look like it had no 5-МН.
LABEL = r"(?:>|№)\s*(\d{1,2}-[А-ЯЁ]{2,5})\s*(?:<|\s)"


def form_row(part: str, code: str) -> str | None:
    """The slice of markup belonging to one form's row."""
    labels = [(m.start(), m.group(1)) for m in re.finditer(LABEL, part)]
    position = next((i for i, (_, found) in enumerate(labels) if found == code), None)
    if position is None:
        return None
    start = labels[position][0]
    end = labels[position + 1][0] if position + 1 < len(labels) else len(part)
    return part[start:end]


def discover(form: str = "5-МН") -> dict[int, str]:
    """Find the per-year archive of `form` broken down by subject.

    Older years link straight to a file; later ones link to a page that holds it.
    The archive with "reg" in its name is the one with every subject in it — the
    plain file next to it is the Russia total only.
    """
    page = _fetch(FORMS_URL).decode("utf-8", "replace")
    boundary = [m.start() for m in re.finditer("Отчеты, сформированные УФНС", page)]
    federal = page[:boundary[-1]] if boundary else page
    # The table markup is not well-formed enough to split on <tr>: doing so
    # hands 5-МН the year links belonging to 5-ТИ. Slice between form labels.
    row = form_row(federal, form)
    if row is None:
        raise RuntimeError(f"На странице ФНС не найдена строка формы {form}")

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
    merged: dict[int, dict] = {}
    problems = []
    for name, book in workbooks(blob, url):
        try:
            sheets = sheets_of(book)
        except (ValueError, RuntimeError, zipfile.BadZipFile) as error:
            # One unreadable Раздел must not cost the others: without xlrd the
            # 2012-2014 archives still yield everything that is .xlsx.
            problems.append(f"{name}: {error}")
            continue
        # 5-ТН and 5-НИО split one Раздел across a dozen sheets that repeat the
        # same regions with different columns, so the member file names the
        # section and every sheet inside it merges into that one section.
        from_name = re.search(r"Раздел\s*([123])", name, re.I)
        for rows in sheets:
            section = int(from_name.group(1)) if from_name else section_of(name, rows)
            if section is None:
                continue
            try:
                indicators, values = parse_sheet(rows, name)
            except ValueError:
                continue
            if not values:
                continue
            slot = merged.setdefault(section, {'indicators': {}, 'values': [], 'title': ''})
            for code, _position, label in indicators:
                slot['indicators'].setdefault(code, label)
            slot['values'].extend(values)
            if not slot['title']:
                slot['title'] = section_title(rows)
    out = [(section, [(code, 0, label) for code, label in slot['indicators'].items()],
            slot['values'], slot['title'])
           for section, slot in sorted(merged.items())]
    if not out and problems:
        raise ValueError("; ".join(problems[:2]))
    return out, problems


def section_title(rows: list[dict[str, str]]) -> str:
    """A readable heading for a section, taken from the sheet's own title rows."""
    text = " ".join(v for cells in rows[:4] for v in cells.values())
    text = " ".join(text.split())
    found = re.search(r"(Отчет о налоговой базе[^.]{0,120})", text, re.I)
    if found:
        return found.group(1).strip(" .,")
    found = re.search(r"РАЗДЕЛ\s+[IΙ]{1,3}\s*(.{0,110})", text, re.I)
    return (found.group(1).strip(" .,") if found else text[:110]).strip()


def update(years: list[int] | None = None, forms: list[str] | None = None, progress=print) -> int:
    """Download and store the federal per-subject archives. Returns figure count."""
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

    all_values: list[tuple] = []
    indicator_labels: dict[tuple[str, int, str], str] = {}
    section_titles: dict[tuple[str, int], str] = {}
    stored = 0
    unmatched: set[str] = set()

    for form in (forms or list(FORMS)):
        progress(f"\n=== {form} — {FORMS[form][0]} ===")
        try:
            found_years = discover(form)
        except (RuntimeError, urllib.error.URLError, TimeoutError) as error:
            progress(f"  не удалось получить список лет: {error}")
            continue
        wanted = sorted(y for y in found_years if years is None or y in years)
        progress(f"  лет доступно {len(found_years)}, будет загружено {len(wanted)}")

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
            for section, indicators, values, title in parsed:
                for code, _position, label in indicators:
                    indicator_labels.setdefault((form, section, code), label)
                section_titles.setdefault(
                    (form, section), KNOWN_TITLES.get((form, section)) or title)
                rows = []
                for subject, code, amount in values:
                    region = lookup.get(normalise(subject))
                    if region is None:
                        unmatched.add(subject)
                        continue
                    rows.append((form, year, section, region, code,
                                 "" if amount is None else
                                 int(amount) if float(amount).is_integer() else amount))
                all_values.extend(rows)
                stored += len(rows)
            got = sorted({s for s, _, _, _ in parsed})
            progress(f"  {year}: разделы {got or '—'}, показателей {stored - before:,}")

    if not all_values:
        progress("Ничего не загружено — файлы оставлены без изменений.")
        return 0
    merge_and_save(all_values, indicator_labels, section_titles, progress)
    if unmatched:
        progress(f"Не сопоставлено с регионами: {', '.join(sorted(unmatched)[:8])}")
    return stored


def update_early(years=(2009, 2010, 2011), progress=print) -> int:
    """Add the years the federal section never published, from the УФНС pages.

    One file per region per form per year — about seven hundred downloads —
    because before 2012 nothing was published as a single per-subject archive.
    """
    import sqlite3  # noqa: PLC0415 - only the refresh path touches the index

    from . import store  # local import: statistics can be imported without an index
    from .config import DB

    try:
        with store.connect(readonly=True) as index:
            codes = sorted({m.group(1) for row in index.execute("SELECT value FROM list_values")
                            if (m := re.match(r"^(\d\d)\s*-", row[0]))})
    except sqlite3.Error:
        raise SystemExit(f"Нужен индекс {DB}: он даёт список регионов.") from None

    progress(f"Обход {len(codes)} региональных страниц за годы {sorted(years)}…")
    sources = regional_sources(codes, list(FORMS), set(years), progress)
    total_files = sum(len(y) for form in sources.values() for y in form.values())
    progress(f"Регионов с данными: {len(sources)}, файлов к загрузке: {total_files}")

    all_values: list[tuple] = []
    labels: dict[tuple[str, int, str], str] = {}
    done = failed = 0
    for code, per_form in sorted(sources.items()):
        for form, per_year in per_form.items():
            for year, url in sorted(per_year.items()):
                try:
                    time.sleep(POLITE_DELAY)
                    # A third of these links are dead; a long timeout turns that
                    # into hours of waiting, while a live file answers in under
                    # a second.
                    blob = _fetch(url, timeout=15)
                    sheets = sheets_of(blob)
                except Exception as error:  # noqa: BLE001 - one bad file of many
                    failed += 1
                    if failed <= 12:
                        progress(f"  rn{code} {form} {year}: {str(error)[:70]}")
                    continue
                rows = [item for sheet in sheets for item in parse_single_region(sheet)]
                if not rows:
                    failed += 1
                    continue
                for section, indicator, label, amount in rows:
                    labels.setdefault((form, section, indicator), label)
                    all_values.append((form, year, section, code, indicator,
                                       "" if amount is None else
                                       int(amount) if float(amount).is_integer() else amount))
                done += 1
        progress(f"  rn{code}: готово ({done} файлов разобрано, {failed} пропущено)")

    if not all_values:
        progress("Ничего не загружено — файлы оставлены без изменений.")
        return 0
    merge_and_save(all_values, labels, {}, progress)
    progress(f"Файлов разобрано {done}, пропущено {failed}")
    return len(all_values)


def merge_and_save(values, labels, titles, progress=print) -> None:
    """Fold new figures into whatever is already shipped, then write the files."""
    existing = {}
    if VALUES_FILE.exists():
        for row in _read(VALUES_FILE):
            existing[(row["form"], int(row["year"]), int(row["section"]),
                      row["region"], row["code"])] = row["amount"]
    for form, year, section, region, code, amount in values:
        existing[(form, year, section, region, code)] = amount

    old_labels, old_titles = {}, {}
    if INDICATORS_FILE.exists():
        for row in _read(INDICATORS_FILE):
            old_labels[(row["form"], int(row["section"]), row["code"])] = row["label"]
    if SECTIONS_FILE.exists():
        for row in _read(SECTIONS_FILE):
            old_titles[(row["form"], int(row["section"]))] = row["title"]
    old_labels.update(labels)
    old_titles.update(titles)

    save(
        sorted(((f, y, s, r, c, a) for (f, y, s, r, c), a in existing.items()),
               key=lambda row: (row[0], row[1], row[2], row[3], int(row[4]))),
        sorted(((f, s, c, l) for (f, s, c), l in old_labels.items()),
               key=lambda row: (row[0], row[1], int(row[2]))),
        sorted(((f, s, t) for (f, s), t in old_titles.items())),
    )
    progress(f"Сохранено: {len(existing):,} показателей → {VALUES_FILE.name}")
    progress("Не забудьте закоммитить их, чтобы данные приехали всем по git pull.")


# ---------------------------------------------------------------- reading back

# ---------------------------------------------------------------- analysis

def catalog() -> dict:
    """Everything the analysis screen needs to offer a choice."""
    table = load()
    years, present = set(), {}
    for by_year in table["values"].values():
        for year, forms in by_year.items():
            years.add(year)
            for form, sections in forms.items():
                for section, rows in sections.items():
                    present.setdefault((form, section), set()).update(code for code, _ in rows)
    forms = []
    for code, (name, _covers) in FORMS.items():
        sections = []
        for (form, number), codes in sorted(present.items()):
            if form != code:
                continue
            indicators = sorted(codes, key=int)
            sections.append({
                'section': number,
                'title': (KNOWN_TITLES.get((form, number))
                          or table["titles"].get((form, number)) or f'Раздел {number}'),
                'taxes': list(SECTION_TAXES.get((form, number), ())),
                'indicators': [{'code': c,
                                'label': tidy_label(table["labels"].get((form, number, c), c))}
                               for c in indicators],
            })
        if sections:
            forms.append({'form': code, 'name': name, 'sections': sections})
    return {'forms': forms, 'years': sorted(years),
            'regions': sorted(table["values"])}


class Formula:
    """A tiny arithmetic evaluator over indicator slots named A, B, C…

    Deliberately not `eval`: the expression arrives from a query string, and the
    grammar it needs is four operators, parentheses and a unary minus.
    """

    TOKEN = re.compile(r"\s*(?:(\d+\.?\d*)|([A-Za-z])|(.))")

    def __init__(self, text: str):
        self.tokens = []
        position = 0
        while position < len(text):
            match = self.TOKEN.match(text, position)
            if not match or match.end() == position:
                break
            position = match.end()
            number, name, symbol = match.groups()
            if number is not None:
                self.tokens.append(("num", float(number)))
            elif name is not None:
                self.tokens.append(("var", name.upper()))
            elif symbol.strip():
                if symbol not in "+-*/()":
                    raise ValueError(f"недопустимый символ {symbol!r}")
                self.tokens.append(("op", symbol))
        self.at = 0

    def _peek(self):
        return self.tokens[self.at] if self.at < len(self.tokens) else (None, None)

    def _take(self):
        token = self._peek()
        self.at += 1
        return token

    def evaluate(self, values: dict[str, float | None]) -> float | None:
        self.at = 0
        result = self._sum(values)
        if self.at != len(self.tokens):
            raise ValueError("лишние символы в формуле")
        return result

    def _sum(self, values):
        left = self._product(values)
        while self._peek() == ("op", "+") or self._peek() == ("op", "-"):
            _, symbol = self._take()
            right = self._product(values)
            if left is None or right is None:
                left = None
            else:
                left = left + right if symbol == "+" else left - right
        return left

    def _product(self, values):
        left = self._unary(values)
        while self._peek() == ("op", "*") or self._peek() == ("op", "/"):
            _, symbol = self._take()
            right = self._unary(values)
            if left is None or right is None:
                left = None
            elif symbol == "*":
                left = left * right
            else:
                left = None if right == 0 else left / right
        return left

    def _unary(self, values):
        if self._peek() == ("op", "-"):
            self._take()
            inner = self._unary(values)
            return None if inner is None else -inner
        return self._atom(values)

    def _atom(self, values):
        kind, value = self._take()
        if kind == "num":
            return value
        if kind == "var":
            return values.get(value)
        if (kind, value) == ("op", "("):
            inner = self._sum(values)
            if self._take() != ("op", ")"):
                raise ValueError("не закрыта скобка")
            return inner
        raise ValueError("формула не разобрана")


def parse_picks(raw: list[str]) -> list[dict]:
    """Turn `A:5-МН:1:1100` strings into indicator slots."""
    picks = []
    for index, item in enumerate(raw):
        parts = item.split(":")
        if len(parts) == 4:
            slot, form, section, code = parts
        elif len(parts) == 3:
            slot, form, section, code = chr(65 + index), *parts
        else:
            raise ValueError(f"не разобран показатель {item!r}")
        picks.append({'slot': slot.upper()[:1], 'form': form,
                      'section': int(section), 'code': code})
    return picks


def series(picks: list[dict], regions: list[str], expression: str = "") -> dict:
    """A year × region matrix for one indicator, or for a formula over several."""
    table = load()
    formula = Formula(expression) if expression.strip() else None
    labels = table["labels"]

    years = sorted({year for region in regions
                    for year in table["values"].get(region, {})})
    rows = []
    for region in regions:
        by_year = table["values"].get(region, {})
        points = []
        for year in years:
            slots: dict[str, float | None] = {}
            for pick in picks:
                found = (by_year.get(year, {}).get(pick['form'], {})
                         .get(pick['section'], []))
                slots[pick['slot']] = next(
                    (amount for code, amount in found if code == pick['code']), None)
            if formula is None:
                points.append(slots.get(picks[0]['slot']) if picks else None)
            else:
                try:
                    points.append(formula.evaluate(slots))
                except ValueError:
                    points.append(None)
        rows.append({'region': region, 'values': points})

    described = [{'slot': p['slot'], 'form': p['form'], 'section': p['section'],
                  'code': p['code'],
                  'label': tidy_label(labels.get((p['form'], p['section'], p['code']), p['code']))}
                 for p in picks]
    return {'years': years, 'rows': rows, 'picks': described,
            'expression': expression.strip()}


def available() -> bool:
    return VALUES_FILE.exists()


def for_region(region: str, year: str | int | None, taxes: tuple[str, ...] = ()) -> dict:
    """Figures for one subject, for the closest year at or before `year`.

    `taxes` are the Nalog_ID values of the open document; when given, only the
    forms that cover those taxes are returned, so a transport-tax document does
    not get three sections about land tax.
    """
    table = load()
    by_year = table["values"].get(region, {})
    years = sorted(by_year)
    if not years:
        return {'years': [], 'year': None, 'forms': []}
    try:
        wanted = int(year)
    except (TypeError, ValueError):
        wanted = years[-1]
    chosen = max((y for y in years if y <= wanted), default=years[0])

    labels, titles = table["labels"], table["titles"]
    forms = []
    for code, (name, covers) in FORMS.items():
        if taxes and not set(taxes) & set(covers):
            continue
        sections = []
        for number, rows in sorted(by_year[chosen].get(code, {}).items()):
            covers = SECTION_TAXES.get((code, number))
            if taxes and covers and not set(taxes) & set(covers):
                continue
            items = []
            for indicator, amount in sorted(rows, key=lambda row: int(row[0])):
                label = labels.get((code, number, indicator), indicator)
                clean = tidy_label(label)
                # A breakdown row inherits its parent's numbering through the
                # joined hierarchy, so the separator is what tells them apart.
                items.append({'code': indicator, 'label': clean,
                              'headline': bool(HEADLINE.match(clean)) and ' · ' not in clean,
                              'amount': amount})
            sections.append({'section': number,
                             'title': (KNOWN_TITLES.get((code, number))
                                       or titles.get((code, number)) or f'Раздел {number}'),
                             'items': items})
        if sections:
            forms.append({'form': code, 'name': name, 'sections': sections})
    return {'years': years, 'year': chosen, 'forms': forms}


# The form numbers its own top-level rows ("1.Количество налогоплательщиков",
# "4. Налоговая база"). Everything else is a breakdown of one of those, so the
# numbering is exactly the split between headline figures and detail.
HEADLINE = re.compile(r"^\s*\d+(\.\d+)?\s*[.)]")


def tidy_label(label: str) -> str:
    text = " ".join(str(label or "").split())
    # Drop the cross-references the form uses to point back up its own hierarchy.
    text = re.sub(r"\s*·\s*", " · ", text)
    return text or "—"
