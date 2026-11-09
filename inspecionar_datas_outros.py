import json
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

root = Path(__file__).resolve().parent / 'relatorio_coletado'
for site in ('r3', 'multiverso', 'roda', 'rhema', 'proprietario'):
    doc = json.loads((root / (site + '.json')).read_text(encoding='utf-8'))
    print('\n###', site, 'candidatos', len(doc['rows']))
    for item in doc['rows'][:2]:
        try:
            r = requests.get(item['url'], headers={'User-Agent':'Mozilla/5.0'}, timeout=25)
            r.raise_for_status()
            s = BeautifulSoup(r.content, 'html.parser')
            print('ID:', item['id'], 'URL:', item['url'])
            for m in re.finditer(r'(?i)(datepublished|datecreated|createdat|publishedat|publicationdate|dateposted|data[_-]?(?:publicacao|cadastro|inclusao|criacao)|(?:publicado|anunciado|cadastrado)\s+(?:em|há|ha)|\b20\d\d[-/]\d\d[-/]\d\d)', str(s)):
                print(' ', re.sub(r'\s+', ' ', str(s)[max(0,m.start()-90):m.end()+110])[:250])
                if m.start() > 300000: break
        except Exception as e:
            print('ERRO', type(e).__name__)
