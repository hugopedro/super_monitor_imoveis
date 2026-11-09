import requests,bs4,json,re
urls=['https://www.torresprime.com.br/imovel/apartamento-santos-2-quartos-98-m/AP5129-C8E','https://www.torresprime.com.br/imovel/apartamento-santos-2-quartos-90-m/AP3645-C8E','https://www.myximoveis.com.br/imovel/apartamento-santos-2-quartos-75-m/AP7099-MYX']
for url in urls:
 r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=30);r.raise_for_status();s=bs4.BeautifulSoup(r.content,'html.parser')
 print('\nURL',url,'TITULO',s.title.get_text(' ',strip=True));
 for element in s.find_all(string=re.compile(r'^Descrição$'))[:1]:
  print('DESCRICAO PAI',str(element.parent.parent)[:1800])
 for element in s.find_all(string=re.compile(r'^Condomínio$'))[:1]:
  print('CONDOMINIO PAI',str(element.parent.parent)[:1300])
 for tag in s(['script','style','footer','header','nav']):tag.decompose()
 text=' '.join(s.get_text(' ',strip=True).split())
 for term in ('condomínio','condominio','elevador','térreo','vaga','Descrição','Valor'):
  for m in list(re.finditer(term,text,re.I))[:2]:print(term,text[max(0,m.start()-100):m.start()+160])
 print('INÍCIO',text[:1300])
