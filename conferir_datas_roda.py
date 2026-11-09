import json
from pathlib import Path
import requests
from bs4 import BeautifulSoup

path = Path(__file__).resolve().parent/'relatorio_coletado/roda.json'
doc = json.loads(path.read_text(encoding='utf-8'))
for item in doc['rows']:
    try:
        response = requests.get(item['url'], headers={'User-Agent':'Mozilla/5.0'}, timeout=25)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        print('\n', item['id'], item['url'])
        for script in soup.find_all('script', type='application/ld+json'):
            try: data=json.loads(script.string or script.get_text())
            except (ValueError,TypeError): continue
            stack=[data]
            while stack:
                obj=stack.pop()
                if isinstance(obj,list): stack.extend(obj)
                elif isinstance(obj,dict):
                    if obj.get('@type') == 'RealEstateListing' and obj.get('datePosted') and obj.get('url','').rstrip('/') == item['url'].rstrip('/'):
                        item['data_publicacao'] = obj['datePosted']
                    if any(k in obj for k in ('datePosted','datePublished','dateCreated')):
                        print('TYPE',obj.get('@type'),'URL',obj.get('url'),'datePosted',obj.get('datePosted'),'datePublished',obj.get('datePublished'),'dateCreated',obj.get('dateCreated'))
                    stack.extend(obj.values())
        node=soup.select_one('.dateUpdated')
        print('ultima atualizacao preco:', node.get_text(' ',strip=True) if node else 'ausente')
        if node:
            item['data_atualizacao_preco'] = node.get_text(' ',strip=True).split()[0]
    except Exception as e: print('ERRO',type(e).__name__)
path.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding='utf-8')
