"""Excel export, written by hand so the program needs no third-party packages."""
from __future__ import annotations

import html
import io
import xml.etree.ElementTree as ET
import zipfile

from .config import FIELD_LABELS, NUMERIC_FIELDS, PAYER_FIELDS
from .xmlsource import number, object_group

PREFERRED = ['ID', 'Region_ID', 'TaxOrganCode', 'Okato_ID', 'Oktmo_ID', 'Oktmo', 'MunObraz',
             'TaxPeriod', 'LawNum', 'LawDate', 'LawDoc', 'PayFiz', 'PayYur', 'PayAll',
             'FileGUID', 'TableType', 'Nalog_ID', 'TaxPlace_ID']
CONTENT_TYPES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
ROOT_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
BOOK_RELS = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
STYLES = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf xfId="0"/><xf xfId="0" fontId="1" applyFont="1"/></cellXfs></styleSheet>')


def make_xlsx(records: list[tuple[str, ET.Element]], payer: str = '') -> bytes:
    def field_order(items):
        seen = {key for item in items for key in item}
        return [key for key in PREFERRED if key in seen] + sorted(seen - set(PREFERRED))

    payer_field = PAYER_FIELDS.get(payer)

    def wanted(item: dict[str, str]) -> bool:
        return not payer_field or item.get(payer_field) == '1'

    def collect(tag):
        # Keep the document order the search produced, then rank rows inside
        # each document so equal objects and categories end up next to each other.
        return [(position, record_id, item.attrib)
                for position, (record_id, element) in enumerate(records)
                for item in element.findall(tag) if wanted(item.attrib)]

    record_attrs = [element.attrib for _, element in records]
    rates = collect('tr')
    benefits = collect('tb')
    rates.sort(key=lambda row: (row[0], object_group(row[2].get('TaxObject', ''))[0].casefold(),
                                number(row[2].get('TaxRates')) if number(row[2].get('TaxRates')) is not None else float('inf'),
                                object_group(row[2].get('TaxObject', ''))[1].casefold()))
    benefits.sort(key=lambda row: (row[0], ' '.join(row[2].get('Category', '').split()).casefold(),
                                   -(number(row[2].get('Amount')) or 0.0)))
    record_fields = field_order(record_attrs)
    rate_fields = field_order([item for _, _, item in rates])
    benefit_fields = field_order([item for _, _, item in benefits])

    def column_name(index):
        name = ''
        while index:
            index, remainder = divmod(index - 1, 26)
            name = chr(65 + remainder) + name
        return name

    def cell(ref, value, style=0):
        # Rates and benefit amounts go in as numbers so Excel can sort them.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
        value = html.escape(str(value if value is not None else ''), quote=True)
        return f'<c r="{ref}" t="inlineStr" s="{style}"><is><t>{value}</t></is></c>'

    def values(attributes, fields):
        row = []
        for key in fields:
            raw = attributes.get(key, '')
            parsed = number(raw) if key in NUMERIC_FIELDS else None
            row.append(parsed if parsed is not None else raw)
        return row

    def sheet_xml(headers, data):
        rows = []
        for row_number, row_values in enumerate([headers, *data], 1):
            style = 1 if row_number == 1 else 0
            cells = ''.join(cell(f'{column_name(column)}{row_number}', value, style)
                            for column, value in enumerate(row_values, 1))
            rows.append(f'<row r="{row_number}">{cells}</row>')
        last_column = column_name(len(headers))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(rows)}</sheetData><autoFilter ref="A1:{last_column}{len(data) + 1}"/>'
                '</worksheet>')

    sheets = [
        ('Записи', [FIELD_LABELS.get(key, key) for key in record_fields],
         [[item.get(key, '') for key in record_fields] for item in record_attrs]),
        ('Налоговые ставки',
         ['Идентификатор документа', 'Группа объекта налогообложения', 'Уточнение объекта']
         + [FIELD_LABELS.get(key, key) for key in rate_fields],
         [[record_id, *object_group(item.get('TaxObject', '')), *values(item, rate_fields)]
          for _, record_id, item in rates]),
        ('Льготы', ['Идентификатор документа'] + [FIELD_LABELS.get(key, key) for key in benefit_fields],
         [[record_id] + values(item, benefit_fields) for _, record_id, item in benefits]),
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', CONTENT_TYPES)
        archive.writestr('_rels/.rels', ROOT_RELS)
        archive.writestr('xl/workbook.xml',
                         '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
                         ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                         + ''.join(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>'
                                   for index, (name, _, _) in enumerate(sheets, 1))
                         + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', BOOK_RELS)
        archive.writestr('xl/styles.xml', STYLES)
        for index, (_, headers, data) in enumerate(sheets, 1):
            archive.writestr(f'xl/worksheets/sheet{index}.xml', sheet_xml(headers, data))
    return output.getvalue()
