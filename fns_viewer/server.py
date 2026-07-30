"""The bundled server: `http.server` plus the command line.

This is the zero-install path. `wsgi.py` exposes the same routes to a real
application server when one process on one laptop stops being enough.
"""
from __future__ import annotations

import argparse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import app, store


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        status, headers, body = app.route(self.path)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_HEAD(self):
        status, headers, body = app.route(self.path)
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description='Просмотр локального налогового XML-экспорта')
    parser.add_argument('--rebuild', action='store_true',
                        help='удалить и заново построить компактный индекс поиска')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--host', default='127.0.0.1',
                        help='адрес прослушивания; 0.0.0.0 открывает доступ по сети')
    parser.add_argument('--open-browser', action='store_true', help='открыть просмотрщик в браузере')
    args = parser.parse_args(argv)

    if args.rebuild:
        store.build_index()
    else:
        store.ensure_index()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f'http://{"127.0.0.1" if args.host == "0.0.0.0" else args.host}:{args.port}'
    print(f'Откройте {url} в браузере (для остановки нажмите Ctrl-C).', flush=True)
    if args.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nОстановлено.', flush=True)
