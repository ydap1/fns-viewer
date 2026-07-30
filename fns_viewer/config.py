"""Paths, labels, and query constants shared by the indexer, the API, and exports.

Paths come from the environment so the package can run against a data set that
lives outside the checkout, which is what a shared or containerised deployment
needs. The defaults keep the single-folder layout working unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("FNS_VIEWER_HOME") or PACKAGE.parent)
XML = Path(os.environ.get("FNS_VIEWER_XML") or ROOT / "data.xml")
DB = Path(os.environ.get("FNS_VIEWER_DB") or ROOT / "tax_viewer_index.sqlite3")
STATIC = PACKAGE / "static"

PAGE_SIZE = 50
EXPORT_LIMIT = 1000


def revision() -> str:
    """Short commit of this checkout, or '' if it is not a clone.

    Updates arrive by `git pull`, so "which version am I looking at" is a
    question users and bug reports need answered. Read from .git directly
    rather than shelling out: git need not be on PATH for this to work.
    """
    git = ROOT / '.git'
    try:
        head = (git / 'HEAD').read_text().strip()
        if not head.startswith('ref: '):
            return head[:7]
        name = head[5:]
        ref = git / name
        if ref.exists():
            return ref.read_text().strip()[:7]
        for line in (git / 'packed-refs').read_text().splitlines():
            if line.endswith(' ' + name):
                return line.split()[0][:7]
    except OSError:
        pass
    return ''

FIELD_LABELS = {
    'ID': 'Идентификатор', 'Region_ID': 'Номер региона', 'TaxOrganCode': 'Код налогового органа',
    'Okato_ID': 'Номер ОКАТО', 'Oktmo_ID': 'Номер ОКТМО', 'Oktmo': 'Номер ОКТМО',
    'MunObraz': 'Муниципальное образование', 'TaxPeriod': 'Налоговый период',
    'LawNum': 'Номер документа', 'LawDate': 'Дата документа', 'LawDoc': 'Налоговый документ',
    'PayFiz': 'Срок уплаты для физических лиц', 'PayYur': 'Срок уплаты для юридических лиц',
    'PayAll': 'Срок уплаты', 'FileGUID': 'Идентификатор файла', 'TableType': 'Тип таблицы',
    'Nalog_ID': 'Идентификатор налога', 'TaxPlace_ID': 'Идентификатор документа',
    'TaxObject': 'Объект налогообложения', 'TaxRates': 'Ставка налога',
    'Category': 'Категория налогоплательщика', 'Base': 'Основание предоставления',
    'Amount': 'Размер льготы', 'Unit': 'Единица измерения', 'Condition': 'Условия предоставления',
    'LawArticle': 'Статья документа', 'Fl': 'Физические лица', 'UL': 'Юридические лица',
    'IP': 'Индивидуальные предприниматели',
}
# Codes the document header shows as monospace chips instead of ordinary fields.
CODE_FIELDS = ['Oktmo_ID', 'Oktmo', 'Okato_ID', 'TaxOrganCode', 'TaxPlace_ID']
# The export marks each rate and benefit with the payer categories it applies to.
PAYER_FIELDS = {'fl': 'Fl', 'ul': 'UL', 'ip': 'IP'}
NUMERIC_FIELDS = {'TaxRates', 'Amount'}
SORT_COLUMNS = {'period': 'period', 'region': 'region_id', 'tax': 'tax_id',
                'municipality': 'municipality COLLATE NOCASE', 'law': 'law COLLATE NOCASE'}
TAX_LIST_IDS = {'2802', '2803', '2804', '2805'}
