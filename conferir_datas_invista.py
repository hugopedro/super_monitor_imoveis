import concurrent.futures
import json
from pathlib import Path
from conferir_datas_chaves import run

path = Path(__file__).resolve().parent/'relatorio_coletado/invista.json'
doc = json.loads(path.read_text(encoding='utf-8'))
by_id = {str(item['id']): item for item in doc['rows']}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(run, doc['rows']))
count = 0
for listing_id, candidates, error in results:
    item = by_id[str(listing_id)]
    for kind, stamp, url, name in candidates:
        if kind == 'WebPage' and url and url.rstrip('/') == item['url'].rstrip('/'):
            item['data_publicacao'] = stamp
            count += 1
            break
path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
print('Invista: datas confirmadas', count, 'erros', sum(bool(r[2]) for r in results))
