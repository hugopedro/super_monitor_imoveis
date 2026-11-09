import concurrent.futures
import json
from pathlib import Path
import requests
from bs4 import BeautifulSoup

PATH = Path(__file__).resolve().parent/'relatorio_coletado/chaves.json'
doc = json.loads(PATH.read_text(encoding='utf-8'))

def run(item):
    try:
        response = requests.get(item['url'], headers={'User-Agent':'Mozilla/5.0'}, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        candidates = []
        for tag in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(tag.string or tag.get_text())
            except (ValueError, TypeError):
                continue
            stack = [data]
            while stack:
                obj = stack.pop()
                if isinstance(obj, list): stack.extend(obj)
                elif isinstance(obj, dict):
                    if obj.get('datePublished'):
                        candidates.append((obj.get('@type'), obj.get('datePublished'), obj.get('url'), obj.get('name')))
                    stack.extend(obj.values())
        return item['id'], candidates, None
    except Exception as e:
        return item['id'], [], type(e).__name__

if __name__ == '__main__':
    import sys
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(doc['rows'])
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(run, doc['rows'][:limit]))
    print(json.dumps(results[:5], ensure_ascii=False, indent=2))
    Path(__file__).resolve().parent.joinpath('relatorio_coletado/chaves_datas_brutas.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Fichas:', len(results), 'com datas:', sum(bool(c) for _,c,_ in results), 'erros:',sum(bool(e) for _,_,e in results))
    if limit >= len(doc['rows']):
        by_id = {str(item['id']): item for item in doc['rows']}
        updated = 0
        for listing_id, candidates, error in results:
            for kind, published, url, name in candidates:
                if kind == 'WebPage' and url and ('/id-' + str(listing_id) + '/') in url:
                    by_id[str(listing_id)]['data_publicacao'] = published
                    updated += 1
                    break
        PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Datas de publicação da ficha associadas ao ID correto:', updated)
