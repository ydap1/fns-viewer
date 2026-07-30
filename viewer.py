#!/usr/bin/env python3
"""Small, local browser for the tax XML export.

The source export is several GB, so this program keeps a compact SQLite index
of the top-level TaxPlace records.  Details are read from XML only after a
record is opened.
"""
from __future__ import annotations

import argparse
import html
import io
import json
import mmap
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import webbrowser
import xml.etree.ElementTree as ET
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
XML = HERE / "data.xml"
DB = HERE / "tax_viewer_index.sqlite3"
START_TAG = re.compile(rb"<tp\s+([^>]*?)>")
ATTRIBUTE = re.compile(rb'''([:\w.-]+)\s*=\s*(["'])(.*?)\2''', re.DOTALL)
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
# The export marks each rate and benefit with the payer categories it applies to.
PAYER_FIELDS = {'fl': 'Fl', 'ul': 'UL', 'ip': 'IP'}
NUMERIC_FIELDS = {'TaxRates', 'Amount'}
SORT_COLUMNS = {'period': 'period', 'region': 'region_id', 'tax': 'tax_id',
                'municipality': 'municipality COLLATE NOCASE', 'law': 'law COLLATE NOCASE'}


def object_group(text: str) -> tuple[str, str]:
    """Split an object of taxation into its group and the qualifying detail.

    Many objects repeat one group with different limits, for example
    "Гидроциклы … (с каждой лошадиной силы): Свыше 100 л.с.", so rates can be
    ranked by group instead of arriving in the order the region typed them.
    """
    text = ' '.join(str(text or '').split())
    head, separator, tail = text.partition(':')
    if separator and head.strip():
        return head.strip(), tail.strip()
    return text, ''


def number(text) -> float | None:
    try:
        return float(str(text).replace(',', '.'))
    except (TypeError, ValueError):
        return None


def attrs(raw: bytes) -> dict[str, str]:
    # This export's List section contains a few legacy values that are not
    # strict XML, so parse quoted attributes directly for indexing. ElementTree
    # is still used for the individual document fragment when it is opened.
    return {m.group(1).decode('ascii'): html.unescape(m.group(3).decode('utf-8', 'replace'))
            for m in ATTRIBUTE.finditer(raw)}


def source_stamp() -> str:
    stat = XML.stat()
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


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
    con.executescript("""
      PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE records (
        id TEXT PRIMARY KEY, offset INTEGER NOT NULL, region_id TEXT,
        tax_id TEXT, period TEXT, municipality TEXT, law TEXT, search_text TEXT
      );
      CREATE INDEX records_filters ON records(region_id, tax_id, period);
      CREATE TABLE list_values (id TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    started = time.monotonic()
    count = 0
    batch: list[tuple] = []
    with XML.open("rb") as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as data:
        # The List section comes first and is tiny. It provides names for regions
        # and tax IDs used by TaxPlace records.
        list_end = data.find(b"</List>")
        if list_end != -1:
            for match in re.finditer(rb"<li\s+([^>]*?)/>", data[:list_end]):
                a = attrs(match.group(1))
                if a.get("ID") and a.get("List_value"):
                    con.execute("INSERT OR REPLACE INTO list_values VALUES (?, ?)", (a["ID"], a["List_value"]))
        for match in START_TAG.finditer(data):
            a = attrs(match.group(1))
            ident = a.get("ID")
            if not ident:
                continue
            municipality = a.get("MunObraz", "")
            law = a.get("LawDoc", "")
            text = " ".join((municipality, law, a.get("TaxOrganCode", ""))).casefold()
            batch.append((ident, match.start(), a.get("Region_ID", ""), a.get("Nalog_ID", ""),
                          a.get("TaxPeriod", ""), municipality, law, text))
            count += 1
            if len(batch) == 5000:
                con.executemany("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
                con.commit(); batch.clear()
                if count % 50000 == 0:
                    print(f"Проиндексировано {count:,} записей за {time.monotonic() - started:.0f} с", flush=True)
        if batch:
            con.executemany("INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?)", batch)
    con.execute("INSERT INTO metadata VALUES ('source_stamp', ?)", (source_stamp(),))
    con.commit(); con.close()
    print(f"Индекс готов: {count:,} записей за {time.monotonic() - started:.0f} с", flush=True)


def ensure_index() -> None:
    con: sqlite3.Connection | None = None
    try:
        con = connect()
        row = con.execute("SELECT value FROM metadata WHERE key='source_stamp'").fetchone()
        if row and row[0] == source_stamp():
            return
    except sqlite3.Error:
        pass
    finally:
        if con is not None:
            con.close()
    print("Создаётся локальный индекс (только при первом запуске или после изменения data.xml)…", flush=True)
    build_index()


def fetch_record(offset: int) -> ET.Element:
    with XML.open("rb") as fh:
        fh.seek(offset)
        parts: list[bytes] = []
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                raise ValueError("Неожиданный конец XML-файла")
            parts.append(chunk)
            joined = b"".join(parts)
            end = joined.find(b"</tp>")
            if end != -1:
                return ET.fromstring(joined[:end + 5])


def make_xlsx(records: list[tuple[str, ET.Element]], payer: str = '') -> bytes:
    """Create a simple .xlsx file without requiring third-party packages."""
    preferred = ['ID', 'Region_ID', 'TaxOrganCode', 'Okato_ID', 'Oktmo_ID', 'Oktmo', 'MunObraz',
                 'TaxPeriod', 'LawNum', 'LawDate', 'LawDoc', 'PayFiz', 'PayYur', 'PayAll',
                 'FileGUID', 'TableType', 'Nalog_ID', 'TaxPlace_ID']

    def field_order(items):
        seen = {key for item in items for key in item}
        return [key for key in preferred if key in seen] + sorted(seen - set(preferred))

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

    def column_name(number):
        name = ''
        while number:
            number, remainder = divmod(number - 1, 26)
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
        for row_number, values in enumerate([headers, *data], 1):
            style = 1 if row_number == 1 else 0
            cells = ''.join(cell(f'{column_name(column)}{row_number}', value, style)
                            for column, value in enumerate(values, 1))
            rows.append(f'<row r="{row_number}">{cells}</row>')
        last_column = column_name(len(headers))
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                f'<sheetData>{"".join(rows)}</sheetData><autoFilter ref="A1:{last_column}{len(data) + 1}"/>'
                '</worksheet>')

    sheets = [
        ('Записи', [FIELD_LABELS.get(key, key) for key in record_fields],
         [[attrs.get(key, '') for key in record_fields] for attrs in record_attrs]),
        ('Налоговые ставки',
         ['Идентификатор документа', 'Группа объекта налогообложения', 'Уточнение объекта']
         + [FIELD_LABELS.get(key, key) for key in rate_fields],
         [[record_id, *object_group(attrs.get('TaxObject', '')), *values(attrs, rate_fields)]
          for _, record_id, attrs in rates]),
        ('Льготы', ['Идентификатор документа'] + [FIELD_LABELS.get(key, key) for key in benefit_fields],
         [[record_id] + values(attrs, benefit_fields) for _, record_id, attrs in benefits]),
    ]
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>''')
        archive.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        archive.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{name}" sheetId="{index}" r:id="rId{index}"/>' for index, (name, _, _) in enumerate(sheets, 1)) + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>''')
        archive.writestr('xl/styles.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts><fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf xfId="0"/><xf xfId="0" fontId="1" applyFont="1"/></cellXfs></styleSheet>''')
        for index, (_, headers, data) in enumerate(sheets, 1):
            archive.writestr(f'xl/worksheets/sheet{index}.xml', sheet_xml(headers, data))
    return output.getvalue()


PAGE = r"""<!doctype html><meta charset=utf-8><title>Просмотрщик налоговой базы</title>
<style>
body{font:15px system-ui,sans-serif;max-width:1380px;margin:28px auto;padding:0 18px;color:#172033;background:#fafbfc}h1{margin:0 0 5px}p{color:#536170}form,.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0}input,select,button{padding:9px;border:1px solid #b8c2cc;border-radius:6px;background:white;font:inherit}input{min-width:190px}button{background:#1769aa;color:#fff;border:0;cursor:pointer}.summary{margin:12px 0;color:#536170}table{border-collapse:collapse;width:100%;background:#fff}th,td{padding:9px;text-align:left;vertical-align:top;border-bottom:1px solid #e3e7eb}th{background:#edf3f8;position:sticky;top:0}a{color:#075d9d;cursor:pointer}.modal{position:fixed;inset:0;background:#0007;padding:4vh 5vw;overflow:auto}.card{background:white;max-width:1560px;margin:auto;padding:22px;border-radius:10px}.close{float:right}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px}.kv{border:1px solid #e3e7eb;padding:8px}.kv b{display:block;color:#536170;font-size:12px}.detail-table{margin:8px 0 4px;table-layout:fixed}.detail-table td{white-space:pre-wrap;overflow-wrap:break-word}.hidden{display:none}small{color:#697784}
.section-head{display:flex;align-items:baseline;gap:16px;flex-wrap:wrap;margin:24px 0 6px}.section-head h2{margin:0;font-size:18px}.section-head label{color:#536170;font-size:13px}.section-head select{padding:5px}
.payers{margin:18px 0 2px}.payers>b{display:block;color:#536170;font-size:12px;margin-bottom:6px}.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:#fff;color:#172033;border:1px solid #b8c2cc;border-radius:6px;text-align:left;line-height:1.35;padding:7px 11px}.chip small{display:block;font-size:11px}.chip.on{background:#1769aa;color:#fff;border-color:#1769aa}.chip.on small{color:#d6e8f6}
.detail-table th{font-size:12px;color:#536170;white-space:nowrap}tr.group td{background:#eef3f8;font-weight:600;white-space:normal}tr.group small{font-weight:400}
.tag{display:inline-block;min-width:28px;text-align:center;padding:1px 5px;margin-right:3px;border-radius:4px;background:#eef1f4;color:#a2adb8;font-size:11px}.tag.on{background:#dcefdc;color:#1f5c2c}
.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}.long{max-height:11em;overflow:auto}.note{color:#7a5300;background:#fff8e6;border:1px solid #f0dfae;padding:10px;border-radius:6px}</style>
<h1>Просмотрщик налоговой базы</h1><p>Локальный просмотрщик <code>data.xml</code> в режиме только для чтения. Откройте строку, чтобы посмотреть ставки и льготы.</p>
<form id=f><input name=q placeholder="Поиск по муниципалитету, закону, ИФНС"><select name=region><option value="">Все регионы</option></select><select name=tax><option value="">Все налоги</option></select><input name=period placeholder="Налоговый период, например 2026"><button>Найти</button></form>
<div class=summary id=s>Загрузка…</div><table><thead><tr><th><button type=button class=sort data-sort=period>Период</button></th><th><button type=button class=sort data-sort=region>Регион</button></th><th><button type=button class=sort data-sort=tax>Налог</button></th><th><button type=button class=sort data-sort=municipality>Муниципальное образование</button></th><th><button type=button class=sort data-sort=law>Закон</button></th></tr></thead><tbody id=rows></tbody></table><div class=toolbar><button id=prev>Назад</button><button id=next>Вперёд</button><button id=download>Скачать Excel (до 1000 записей)</button></div><div id=modal class="modal hidden"><div class=card><button class=close onclick="modal.classList.add('hidden')">Закрыть</button><div id=detail>Загрузка…</div></div></div>
<script>
let page=0, count=0, sort='period', dir='desc'; const f=document.querySelector('#f'), rows=document.querySelector('#rows'), s=document.querySelector('#s'), modal=document.querySelector('#modal'), detail=document.querySelector('#detail');
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={ID:'Идентификатор',Region_ID:'Номер региона',TaxOrganCode:'Код налогового органа',Okato_ID:'Номер ОКАТО',Oktmo_ID:'Номер ОКТМО',Oktmo:'Номер ОКТМО',MunObraz:'Муниципальное образование',TaxPeriod:'Налоговый период',LawNum:'Номер документа',LawDate:'Дата документа',LawDoc:'Налоговый документ',PayFiz:'Срок уплаты для физических лиц',PayYur:'Срок уплаты для юридических лиц',PayAll:'Срок уплаты',FileGUID:'Идентификатор файла',TableType:'Тип таблицы',Nalog_ID:'Идентификатор налога',TaxPlace_ID:'Идентификатор документа',TaxObject:'Объект налогообложения',TaxRates:'Ставка налога',Category:'Категория налогоплательщика',Base:'Основание предоставления',Amount:'Размер льготы',Unit:'Единица измерения',Condition:'Условия предоставления',LawArticle:'Статья документа',Fl:'Физические лица',UL:'Юридические лица',IP:'Индивидуальные предприниматели'};
const fieldName=k=>labels[k]||k;
const PAYERS=[['','Все категории','Все'],['fl','Физические лица','ФЛ'],['ul','Юридические лица','ЮЛ'],['ip','Индивидуальные предприниматели','ИП']];
const PAYER_FIELD={fl:'Fl',ul:'UL',ip:'IP'};
let record=null,payer='',rateSort='object',benefitSort='category';
const tidy=x=>String(x??'').replace(/\s+/g,' ').trim();
const num=x=>{const v=parseFloat(String(x??'').replace(',','.'));return isNaN(v)?null:v};
const fmt=v=>v===null?'—':v.toLocaleString('ru-RU',{maximumFractionDigits:4});
const plural=(n,f)=>{const a=Math.abs(n)%100,b=a%10;return n+' '+(a>10&&a<20?f[2]:b===1?f[0]:b>1&&b<5?f[1]:f[2])};
const forPayer=(items,value)=>items.filter(x=>!value||x[PAYER_FIELD[value]]==='1');
const splitObject=t=>{const s=tidy(t),i=s.indexOf(':');return i>0?[s.slice(0,i).trim(),s.slice(i+1).trim()]:[s,'']};
const payerTags=item=>PAYERS.slice(1).map(([v,name,short])=>`<span class="tag${item[PAYER_FIELD[v]]==='1'?' on':''}" title="${esc(name)}">${short}</span>`).join('');
const optionTags=(list,active)=>list.map(([v,name])=>`<option value="${v}"${v===active?' selected':''}>${esc(name)}</option>`).join('');
function setPayer(value){payer=value;render()}
function setRateSort(value){rateSort=value;render()}
function setBenefitSort(value){benefitSort=value;render()}
function downloadRecord(){location='/api/export.xlsx?'+new URLSearchParams({id:record.id,payer})}
function payerBar(){return `<div class=payers><b>Категория плательщика — ставки и льготы показываются только для выбранной</b><div class=chips>${PAYERS.map(([v,name])=>
  `<button type=button class="chip${v===payer?' on':''}" onclick="setPayer('${v}')">${esc(name)}<small>${plural(forPayer(record.rates,v).length,['ставка','ставки','ставок'])} · ${plural(forPayer(record.benefits,v).length,['льгота','льготы','льгот'])}</small></button>`).join('')}</div></div>`}
function heading(title,shown,total,control){return `<div class=section-head><h2>${title} (${shown}${shown!==total?` из ${total}`:''})</h2>${control}</div>`}
const emptyNote=()=>`<p class=note>Для выбранной категории плательщиков записей нет. В части документов признаки ФЛ/ЮЛ/ИП не заполнены — тогда выберите «Все категории».</p>`;
function rateGroups(items){
  const groups=new Map();
  for(const item of items){
    const [name,detail]=splitObject(item.TaxObject),key=name.toLocaleLowerCase('ru');
    if(!groups.has(key))groups.set(key,{name,items:[]});
    groups.get(key).items.push({...item,detail,rate:num(item.TaxRates)});
  }
  const list=[...groups.values()],down=rateSort==='rate-desc',sign=down?-1:1;
  for(const g of list){
    const values=g.items.map(x=>x.rate).filter(x=>x!==null);
    g.min=values.length?Math.min(...values):null;g.max=values.length?Math.max(...values):null;
    g.items.sort((a,b)=>sign*((a.rate??0)-(b.rate??0))||a.detail.localeCompare(b.detail,'ru'));
  }
  if(rateSort==='object')list.sort((a,b)=>a.name.localeCompare(b.name,'ru'));
  else list.sort((a,b)=>sign*((down?a.max:a.min)??0)-sign*((down?b.max:b.min)??0)||a.name.localeCompare(b.name,'ru'));
  return list;
}
function ratesSection(){
  const items=forPayer(record.rates,payer);
  const control=`<label>Ранжировать: <select onchange="setRateSort(this.value)">${optionTags([['object','по объекту налогообложения'],['rate','по ставке, по возрастанию'],['rate-desc','по ставке, по убыванию']],rateSort)}</select></label>`;
  const head=heading('Налоговые ставки',items.length,record.rates.length,control);
  if(!items.length)return head+(record.rates.length?emptyNote():'<p>Нет</p>');
  const groups=rateGroups(items);
  // Only regions that spell out power limits after a colon need the detail column.
  const detailed=groups.some(g=>g.items.some(x=>x.detail));
  const columns=[['<col style=width:130px>','<th class=num>Ставка налога</th>']];
  if(detailed)columns.push(['<col>','<th>Уточнение объекта</th>']);
  columns.push(['<col style=width:130px>','<th>Плательщики</th>'],['<col style=width:130px>','<th>Идентификатор</th>']);
  const body=groups.map(g=>{
    const range=g.min===null?'':' · ставка '+(g.min===g.max?fmt(g.min):`${fmt(g.min)} – ${fmt(g.max)}`);
    return `<tr class=group><td colspan=${columns.length}>${esc(g.name)} <small>· ${plural(g.items.length,['ставка','ставки','ставок'])}${esc(range)}</small></td></tr>`
      +g.items.map(x=>`<tr title="${esc(tidy(x.TaxObject))}"><td class=num><b>${esc(fmt(x.rate))}</b></td>${detailed?`<td>${esc(x.detail||'—')}</td>`:''}<td>${payerTags(x)}</td><td><small>${esc(x.ID||'')}</small></td></tr>`).join('');
  }).join('');
  return head+`<table class=detail-table><colgroup>${columns.map(c=>c[0]).join('')}</colgroup><thead><tr>${columns.map(c=>c[1]).join('')}</tr></thead><tbody>${body}</tbody></table>`;
}
function benefitsSection(){
  const items=forPayer(record.benefits,payer).map(x=>({...x,amount:num(x.Amount)}));
  const control=`<label>Ранжировать: <select onchange="setBenefitSort(this.value)">${optionTags([['category','по категории налогоплательщика'],['amount','по размеру льготы'],['article','по статье документа']],benefitSort)}</select></label>`;
  const head=heading('Льготы',items.length,record.benefits.length,control);
  if(!items.length)return head+(record.benefits.length?emptyNote():'<p>Нет</p>');
  if(benefitSort==='amount')items.sort((a,b)=>(b.amount??-1)-(a.amount??-1)||tidy(a.Category).localeCompare(tidy(b.Category),'ru'));
  else if(benefitSort==='article')items.sort((a,b)=>tidy(a.LawArticle).localeCompare(tidy(b.LawArticle),'ru',{numeric:true}));
  else items.sort((a,b)=>tidy(a.Category).localeCompare(tidy(b.Category),'ru'));
  const body=items.map(x=>`<tr><td>${esc(tidy(x.Category)||'—')}</td><td class=num><b>${esc(fmt(x.amount))}</b> ${esc(tidy(x.Unit))}</td><td>${payerTags(x)}</td><td>${esc(tidy(x.Base)||'—')}</td><td><div class=long>${esc(x.Condition||'—')}</div></td><td>${esc(tidy(x.LawArticle)||'—')}</td><td><small>${esc(x.ID||'')}</small></td></tr>`).join('');
  return head+`<table class=detail-table><colgroup><col style=width:26%><col style=width:120px><col style=width:120px><col style=width:18%><col><col style=width:130px><col style=width:110px></colgroup><thead><tr><th>Категория налогоплательщика</th><th class=num>Размер льготы</th><th>Плательщики</th><th>Основание</th><th>Условия предоставления</th><th>Статья</th><th>Идентификатор</th></tr></thead><tbody>${body}</tbody></table>`;
}
function render(){
  const attributes=Object.entries(record.attributes).map(([k,v])=>`<div class=kv><b>${esc(fieldName(k))}</b>${esc(v)}</div>`).join('');
  detail.innerHTML=`<h2>Документ ${esc(record.attributes.ID)}</h2><div class=grid>${attributes}</div>${payerBar()}`
    +`<div class=toolbar><button type=button onclick="downloadRecord()">Скачать этот документ в Excel (с учётом выбранной категории)</button></div>`
    +ratesSection()+benefitsSection();
}
async function options(){let d=await (await fetch('/api/options')).json();for(const [id,n] of d.regions)f.region.add(new Option(n,id));for(const [id,n] of d.taxes)f.tax.add(new Option(n,id));} 
async function search(){let p=new URLSearchParams(new FormData(f));p.set('page',page);p.set('sort',sort);p.set('dir',dir);let d=await (await fetch('/api/search?'+p)).json();count=d.count;s.textContent=`Найдено записей: ${count.toLocaleString()} · показаны ${count?page*50+1:0}–${Math.min((page+1)*50,count)}`;rows.innerHTML=d.rows.map(r=>`<tr><td>${esc(r.period)}</td><td>${esc(r.region)}</td><td>${esc(r.tax)}</td><td><a onclick="openRecord('${esc(r.id)}')">${esc(r.municipality||'—')}</a></td><td>${esc(r.law||'—')}</td></tr>`).join('')||'<tr><td colspan=5>По вашему запросу ничего не найдено</td></tr>';}
async function openRecord(id){modal.classList.remove('hidden');detail.textContent='Загрузка…';let d=await (await fetch('/api/record/'+encodeURIComponent(id))).json();if(d.error){detail.textContent=d.error;return}record={...d,id};payer='';rateSort='object';benefitSort='category';render();}
f.onsubmit=e=>{e.preventDefault();page=0;search()};prev.onclick=()=>{if(page){page--;search()}};next.onclick=()=>{if((page+1)*50<count){page++;search()}};download.onclick=()=>{let p=new URLSearchParams(new FormData(f));p.set('sort',sort);p.set('dir',dir);location='/api/export.xlsx?'+p};document.querySelectorAll('.sort').forEach(b=>b.onclick=()=>{let next=b.dataset.sort;dir=sort===next?(dir==='asc'?'desc':'asc'):'asc';sort=next;page=0;search()});options().then(search);
</script>"""


def list_query(params) -> tuple[str, list, str]:
    filters = []
    args: list = []
    for column, key in [('region_id', 'region'), ('tax_id', 'tax'), ('period', 'period')]:
        value = params.get(key, [''])[0].strip()
        if value:
            filters.append(f'{column} = ?')
            args.append(value)
    text = params.get('q', [''])[0].strip().casefold()
    if text:
        filters.append('search_text LIKE ?')
        args.append('%' + text + '%')
    where = ' WHERE ' + ' AND '.join(filters) if filters else ''
    column = SORT_COLUMNS.get(params.get('sort', ['period'])[0], 'period')
    direction = 'ASC' if params.get('dir', ['desc'])[0].lower() == 'asc' else 'DESC'
    return where, args, f'{column} {direction}, id DESC'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, payload, status=200):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def send_xlsx(self, records, payer='', name='tax_records'):
        raw = make_xlsx(records, payer)
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.send_header("Content-Disposition", f'attachment; filename="{name}.xlsx"')
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers(); self.wfile.write(raw)
    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path == "/":
            raw = PAGE.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        params = urllib.parse.parse_qs(query)
        con = connect()
        try:
            if path == "/api/options":
                values = con.execute("SELECT id,value FROM list_values").fetchall()
                # Region values start with a two-digit code; known tax IDs are the three tax names.
                regions = [(r['id'], r['value']) for r in values if re.match(r"^\d\d\s*-", r['value'])]
                taxes = [(r['id'], r['value']) for r in values if r['id'] in {'2802','2803','2804','2805'}]
                return self.send_json({'regions': sorted(regions, key=lambda x:x[1]), 'taxes': taxes})
            if path == "/api/search":
                where, args, order = list_query(params)
                count=con.execute('SELECT count(*) FROM records'+where,args).fetchone()[0]
                page=max(0,int(params.get('page',['0'])[0] or 0)); args2=args+[50,page*50]
                found=con.execute(f'SELECT id,region_id,tax_id,period,municipality,law FROM records{where} ORDER BY {order} LIMIT ? OFFSET ?',args2).fetchall()
                names={r['id']:r['value'] for r in con.execute('SELECT id,value FROM list_values')}
                return self.send_json({'count':count,'rows':[dict(id=r['id'],region=names.get(r['region_id'],r['region_id']),tax=names.get(r['tax_id'],r['tax_id']),period=r['period'],municipality=r['municipality'],law=r['law']) for r in found]})
            if path == "/api/export.xlsx":
                payer=params.get('payer',[''])[0]
                ident=params.get('id',[''])[0].strip()
                if ident:
                    # A single document, exported straight from the opened card.
                    row=con.execute('SELECT id,offset FROM records WHERE id=?',(ident,)).fetchone()
                    if not row: return self.send_json({'error':'Запись не найдена'},404)
                    return self.send_xlsx([(row['id'], fetch_record(row['offset']))], payer, f'tax_document_{ident}')
                where, args, order = list_query(params)
                found=con.execute(f'SELECT id,offset FROM records{where} ORDER BY {order} LIMIT 1000',args).fetchall()
                return self.send_xlsx([(row['id'], fetch_record(row['offset'])) for row in found], payer)
            if path.startswith('/api/record/'):
                ident=urllib.parse.unquote(path.rsplit('/',1)[1]); row=con.execute('SELECT offset FROM records WHERE id=?',(ident,)).fetchone()
                if not row: return self.send_json({'error':'Запись не найдена'},404)
                el=fetch_record(row['offset'])
                return self.send_json({'attributes':el.attrib,'rates':[x.attrib for x in el.findall('tr')],'benefits':[x.attrib for x in el.findall('tb')]})
            return self.send_json({'error':'Страница не найдена'},404)
        except Exception as exc:
            return self.send_json({'error':str(exc)},500)
        finally: con.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description='Просмотр локального налогового XML-экспорта')
    parser.add_argument('--rebuild', action='store_true', help='удалить и заново построить компактный индекс поиска')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open-browser', action='store_true', help='открыть просмотрщик в браузере')
    args=parser.parse_args()
    if args.rebuild: build_index()
    else: ensure_index()
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    url=f'http://127.0.0.1:{args.port}'
    print(f'Откройте {url} в браузере (для остановки нажмите Ctrl-C).',flush=True)
    if args.open_browser: webbrowser.open(url)
    server.serve_forever()
