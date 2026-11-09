import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests
from bs4 import BeautifulSoup

root = Path(__file__).resolve().parent / 'relatorio_coletado'
targets = ['r3','multiverso','roda','rhema','proprietario']
items = [(site,item) for site in targets for item in json.loads((root/(site+'.json')).read_text(encoding='utf-8'))['rows']]
date_rx = re.compile(r'(?i)(?:publicad[oa]|anunciad[oa]|cadastrad[oa]|inclu[ií]d[oa]|criad[oa]|inserid[oa]|atualizad[oa]|datePosted|datePublished|createdAt|publishedAt)[^\n]{0,70}(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|há\s+\d+\s+(?:dia|semana|m[eê]s|ano))')

def inspect(pair):
    site,item=pair
    try:
        r=requests.get(item['url'],headers={'User-Agent':'Mozilla/5.0'},timeout=25);r.raise_for_status()
        soup=BeautifulSoup(r.content,'html.parser')
        text=' '.join(soup.get_text(' ',strip=True).split())
        hits=date_rx.findall(text)
        return (site,item['id'],hits[:2],None)
    except Exception as e:return (site,item['id'],[],type(e).__name__)

with ThreadPoolExecutor(max_workers=5) as pool: results=list(pool.map(inspect,items))
for site in targets:
    section=[x for x in results if x[0]==site]
    print(site,'fichas',len(section),'datas textuais',sum(bool(x[2]) for x in section),'erros',sum(bool(x[3]) for x in section))
    for x in section:
        if x[2]: print(' ',x[:3])
