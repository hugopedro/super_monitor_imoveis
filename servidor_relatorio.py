"""Servidor local e banco persistente das decisões do relatório de imóveis."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sqlite3
import webbrowser

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'decisoes_imoveis.sqlite3'
PAGE = ROOT / 'apartamentos_santos.html'
HOST, PORT = '127.0.0.1', 8765

def initialize():
    with sqlite3.connect(DB) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS decisions (
            listing_key TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK(status IN ('excluded','considered')),
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == '/api/decisions':
            with sqlite3.connect(DB) as conn:
                rows = conn.execute('SELECT listing_key,status FROM decisions').fetchall()
            self.send_json(200, {key: status for key, status in rows})
            return
        if self.path == '/':
            self.path = '/apartamentos_santos.html'
        return super().do_GET()

    def do_POST(self):
        if self.path != '/api/decision':
            self.send_error(404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > 4096:
                self.send_error(413)
                return
            data = json.loads(self.rfile.read(length))
            key, status = data.get('key'), data.get('status')
            if not isinstance(key, str) or len(key) > 300 or status not in ('excluded', 'considered', None):
                self.send_error(400, 'Dados inválidos')
                return
            with sqlite3.connect(DB) as conn:
                if status is None:
                    conn.execute('DELETE FROM decisions WHERE listing_key=?', (key,))
                else:
                    conn.execute('''INSERT INTO decisions(listing_key,status,updated_at)
                        VALUES(?,?,CURRENT_TIMESTAMP)
                        ON CONFLICT(listing_key) DO UPDATE SET status=excluded.status,updated_at=excluded.updated_at''',
                        (key, status))
            self.send_json(200, {'ok': True})
        except (ValueError, sqlite3.Error):
            self.send_error(400, 'Não foi possível salvar')

if __name__ == '__main__':
    initialize()
    url = f'http://{HOST}:{PORT}/'
    print(f'Banco local: {DB}')
    print(f'Relatório: {url}')
    try:
        webbrowser.open(url)
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print('\nServidor encerrado; suas decisões continuam salvas no banco.')
