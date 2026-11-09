import requests,bs4,re
from urllib.parse import urljoin

sites={'torres_prime':'https://www.torresprime.com.br/','myx':'https://www.myximoveis.com.br/',
       'raiz':'https://www.raizimobiliariasantos.com.br/','mape':'https://www.mapenegocios.com.br/'}
session=requests.Session();session.headers['User-Agent']='Mozilla/5.0'
for site,base in sites.items():
 found={}; expected=None
 for page in range(1,20):
  r=session.get(base+'imoveis/a-venda/apartamento/santos',params={'preco-de-venda':'~426000','pagina':page},timeout=30);r.raise_for_status()
  soup=bs4.BeautifulSoup(r.content,'html.parser');title=soup.title.get_text(' ',strip=True); match=re.match(r'(\d+)',title)
  if not match: raise ValueError((site,title))
  expected=int(match.group(1)); anchors=soup.select('a.card-with-buttons[href*="/imovel/"]'); before=len(found)
  for a in anchors:
   text=a.get_text(' ',strip=True);id=a['href'].split('/')[-1];found[id]=(urljoin(base,a['href']),text)
  print(site,'página',page,'contagem',len(anchors),'total esperado',expected, 'únicos',len(found))
  if len(found)>=expected or not anchors or len(found)==before:break
 print('CANDIDATOS',site)
 for k,(url,text) in found.items():
  if re.search(r'apartamento\s+(?:aparecida|boqueir[aã]o|embar[eé]|gonzaga|pomp[eé]ia|campo grande|marap[eé]|jos[eé] menino)\s+-\s+santos\s+-\s+sp',text,re.I) and re.search(r'\b2\s+quartos?\b',text,re.I):
   print(k,text[:220],url)
 print('FIM',site,expected,len(found))
