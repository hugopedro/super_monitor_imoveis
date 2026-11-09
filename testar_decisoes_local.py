import json
import sqlite3
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

import servidor_relatorio as app

app.initialize()
server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
base = f'http://127.0.0.1:{server.server_port}'
key = '__test_persistencia__'

def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = Request(base + path, data=body, headers={'Content-Type':'application/json'} if body else {})
    with urlopen(req) as res: return json.loads(res.read()) if 'json' in res.headers.get('Content-Type','') else res.status

try:
    request('/api/decision', {'key':key,'status':'considered'})
    assert request('/api/decisions')[key] == 'considered'
    request('/api/decision', {'key':key,'status':'excluded'})
    assert request('/api/decisions')[key] == 'excluded'
    request('/api/decision', {'key':key,'status':None})
    assert key not in request('/api/decisions')
    print('GET/POST/DELETE do banco local: OK')
finally:
    server.shutdown()
    server.server_close()
