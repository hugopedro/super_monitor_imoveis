import requests,bs4,re
from urllib.parse import urljoin
session=requests.Session();session.headers['User-Agent']='Mozilla/5.0';base='https://imobiliariapousada.com.br/'
seen={}
for page in range(1,20):
 r=session.get(base+'apartamento/a-venda/santos-sp',params={'preco-maximo':'426000','pagina':page},timeout=30);r.raise_for_status();s=bs4.BeautifulSoup(r.content,'html.parser')
 title=s.title.get_text(' ',strip=True);total=re.match(r'\d+',title)
 cards=s.select('.thumbnail_one:has(a.property-card-link)');before=len(seen)
 for card in cards:
  link=card.select_one('a.property-card-link.d-block:not(.image_area)');photo=card.select_one('a.property-card-link.image_area')
  if not link:continue
  url=urljoin(base,link.get('href'));text=link.get_text(' ',strip=True);price=photo.get_text(' ',strip=True) if photo else ''
  seen[url]=(text,price)
 print('pagina',page,'title',title,'cards',len(cards),'unique',len(seen),flush=True)
 if total and len(seen)>=int(total.group()):break
 if not cards or before==len(seen):raise RuntimeError('Paginação incompleta')
for url,(text,price) in seen.items():
 if re.search(r'\b(?:aparecida|boqueir[aã]o|embar[eé]|gonzaga|pomp[eé]ia|campo grande|marap[eé]|jos[eé] menino)\s*,\s*santos',text,re.I) and re.search(r'\b2\s+quartos?',text,re.I):print('CANDIDATO',price,text[:250],url)
