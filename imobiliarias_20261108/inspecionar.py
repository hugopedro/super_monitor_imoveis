import concurrent.futures
import json
import re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

root = Path(__file__).resolve().parent
items = json.loads((root/'inventario.json').read_text(encoding='utf-8'))
def probe(pair):
    name, item = pair
    if not item['url'] or item['estado'] == 'monitor existente': return name, 'ignorado'
    try:
        r=requests.get(item['url'],headers={'User-Agent':'Mozilla/5.0'},timeout=25)
        soup=BeautifulSoup(r.content,'html.parser')
        forms=[{'action':f.get('action'),'method':f.get('method'),'fields':[x.get('name') for x in f.select('[name]')][:30]} for f in soup.select('form')][:3]
        scripts=[urljoin(r.url,x.get('src')) for x in soup.select('script[src]') if any(t in x.get('src','').lower() for t in ('busca','imov','search','main','app.'))][:8]
        links=[urljoin(r.url,a.get('href')) for a in soup.select('a[href]') if re.search(r'(comprar|venda|imoveis|imovel)',a.get('href',''),re.I)][:4]
        brands=[x for x in ('imoview','jetimob','vista','inforce','universalcrm','kenlo','next-data','next.js') if x in r.text.lower()]
        return name, {'status':r.status_code,'url':r.url,'bytes':len(r.content),'brands':brands,'forms':forms,'scripts':scripts,'links':links}
    except Exception as e:return name, {'error':type(e).__name__}
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: results=dict(pool.map(probe,items.items()))
print(json.dumps(results,ensure_ascii=False,indent=2))
