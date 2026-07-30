"""WSGI entry point, for when the viewer outgrows one laptop.

    pip install gunicorn
    FNS_VIEWER_XML=/data/data.xml gunicorn -w 4 fns_viewer.wsgi:application

The index must already exist; build it once with `python3 viewer.py --rebuild`
and mount it read-only, since every worker only reads.
"""
from __future__ import annotations

from . import app

STATUS = {200: '200 OK', 404: '404 Not Found', 405: '405 Method Not Allowed',
          500: '500 Internal Server Error'}


def application(environ, start_response):
    if environ.get('REQUEST_METHOD') not in ('GET', 'HEAD'):
        start_response(STATUS[405], [('Content-Type', 'text/plain; charset=utf-8')])
        return [b'Method Not Allowed']
    path = environ.get('PATH_INFO', '/')
    query = environ.get('QUERY_STRING', '')
    status, headers, body = app.route(f'{path}?{query}' if query else path)
    start_response(STATUS.get(status, f'{status} Status'),
                   [*headers.items(), ('Content-Length', str(len(body)))])
    return [] if environ['REQUEST_METHOD'] == 'HEAD' else [body]
