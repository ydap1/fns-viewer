"""Request routing, independent of any particular server.

Handlers take a path plus parsed query parameters and return a plain
`(status, headers, body)` tuple, so the same routes serve the bundled
`http.server` (see `server.py`) and any WSGI host (see `wsgi.py`).
"""
from __future__ import annotations

import json
import mimetypes
import sqlite3
import threading
import urllib.parse

from . import statistics, store
from .config import CODE_FIELDS, EXPORT_LIMIT, FIELD_LABELS, PAYER_FIELDS, STATIC
from .export import make_xlsx
from .xmlsource import fetch_record

Response = tuple[int, dict[str, str], bytes]
_local = threading.local()


def connection() -> sqlite3.Connection:
    """One read-only connection per thread; SQLite readers do not block readers."""
    con = getattr(_local, 'con', None)
    if con is None:
        con = _local.con = store.connect(readonly=True)
    return con


def json_response(payload, status: int = 200) -> Response:
    raw = json.dumps(payload, ensure_ascii=False).encode()
    return status, {'Content-Type': 'application/json; charset=utf-8'}, raw


def static_response(name: str) -> Response:
    path = (STATIC / name).resolve()
    if not path.is_file() or STATIC.resolve() not in path.parents:
        return json_response({'error': 'Страница не найдена'}, 404)
    kind = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    charset = '; charset=utf-8' if kind.startswith(('text/', 'application/javascript')) else ''
    # The assets ship next to the program, so a reload must always pick up an update.
    return 200, {'Content-Type': kind + charset, 'Cache-Control': 'no-cache'}, path.read_bytes()


def export_response(records, payer: str, name: str) -> Response:
    raw = make_xlsx(records, payer)
    return 200, {
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': f'attachment; filename="{name}.xlsx"',
    }, raw


def handle(path: str, params: dict[str, list[str]]) -> Response:
    if path == '/':
        return static_response('index.html')
    if not path.startswith('/api/'):
        return static_response(path.lstrip('/'))

    con = connection()
    try:
        if path == '/api/meta':
            return json_response({'labels': FIELD_LABELS, 'payerFields': PAYER_FIELDS,
                                  'codeFields': CODE_FIELDS})
        if path == '/api/options':
            return json_response(store.options(con))
        if path == '/api/statistics':
            if not statistics.available():
                return json_response({'available': False})
            region = params.get('region', [''])[0].strip()
            if not region:
                return json_response({'error': 'Не указан регион'}, 400)
            payload = statistics.for_region(region, params.get('period', [''])[0])
            payload['available'] = True
            payload['form'] = '5-МН'
            return json_response(payload)
        if path == '/api/search':
            return json_response(store.search(con, params))
        if path == '/api/export.xlsx':
            payer = params.get('payer', [''])[0]
            ident = params.get('id', [''])[0].strip()
            if ident:
                # A single document, exported straight from the opened card.
                row = con.execute('SELECT id, offset FROM records WHERE id=?', (ident,)).fetchone()
                if not row:
                    return json_response({'error': 'Запись не найдена'}, 404)
                return export_response([(row['id'], fetch_record(row['offset']))], payer,
                                       f'tax_document_{ident}')
            clause, args, order = store.query(params)
            found = con.execute(f'SELECT records.id, offset{clause} ORDER BY {order} LIMIT ?',
                                args + [EXPORT_LIMIT]).fetchall()
            return export_response([(row['id'], fetch_record(row['offset'])) for row in found],
                                   payer, 'tax_records')
        if path.startswith('/api/record/'):
            ident = urllib.parse.unquote(path.rsplit('/', 1)[1])
            row = con.execute('SELECT id, offset, region_id, tax_id FROM records WHERE id=?',
                              (ident,)).fetchone()
            if not row:
                return json_response({'error': 'Запись не найдена'}, 404)
            element = fetch_record(row['offset'])
            names = store.list_values(con)
            return json_response({
                'id': row['id'],
                'region': names.get(row['region_id'], row['region_id']),
                'tax': names.get(row['tax_id'], row['tax_id']),
                'attributes': element.attrib,
                'rates': [x.attrib for x in element.findall('tr')],
                'benefits': [x.attrib for x in element.findall('tb')],
            })
        return json_response({'error': 'Страница не найдена'}, 404)
    except Exception as exc:  # noqa: BLE001 - the browser should see why a request failed
        return json_response({'error': str(exc)}, 500)


def route(raw_path: str) -> Response:
    path, _, query = raw_path.partition('?')
    return handle(urllib.parse.unquote(path), urllib.parse.parse_qs(query))
