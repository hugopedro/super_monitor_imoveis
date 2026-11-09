import concurrent.futures
import json
from pathlib import Path
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent/'relatorio_coletado'
sites = ['r3','multiverso','roda','rhema','proprietario']
items = [(site, item) for site in sites for item in json.loads((ROOT/(site+'.json')).read_text(encoding='utf-8'))['rows']]

def inspect(entry):
    site,item=entry
    try:
        response=requests.get(item['url'], headers={'User-Agent':'Mozilla/5.0'}, timeout=25)
        response.raise_for_status()
        soup=BeautifulSoup(response.content, 'html.parser')
        found=[]
        for tag in soup.find_all('script', type='application/ld+json'):
            try: data=json.loads(tag.string or tag.get_text())
            except (ValueError,TypeError): continue
            stack=[data]
            while stack:
                obj=stack.pop()
                if isinstance(obj,list): stack.extend(obj)
                elif isinstance(obj,dict):
                    for key in ('datePosted','datePublished','dateCreated'):
                        if obj.get(key): found.append([obj.get('@type'),key,obj[key],obj.get('url')])
                    stack.extend(obj.values())
        return {'site':site,'id':item['id'],'found':found,'error':None}
    except Exception as e: return {'site':site,'id':item['id'],'found':[],'error':type(e).__name__}

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(inspect,items))
for site in sites:
    values=[r for r in results if r['site']==site]
    print(site, 'verificados',len(values),'com datas estruturadas',sum(bool(r['found']) for r in values),'erros',sum(bool(r['error']) for r in values))
    for row in values:
        if row['found']: print(' ',row['id'],row['found'])
(ROOT/'datas_restantes_verificacao.json').write_text(json.dumps(results, ensure_ascii=False, indent=2),encoding='utf-8')
