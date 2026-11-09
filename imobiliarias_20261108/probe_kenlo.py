import requests,bs4,re,json
sites={'torres':'https://www.torresprime.com.br/imoveis/a-venda','myx':'https://www.myximoveis.com.br/imoveis/a-venda','raiz':'https://www.raizimobiliariasantos.com.br/imoveis/a-venda','mape':'https://www.mapenegocios.com.br/imoveis/a-venda'}
for name,url in sites.items():
 try:
  r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=30);s=bs4.BeautifulSoup(r.content,'html.parser')
  print('\n',name,r.status_code,r.url,len(r.content))
  print('title',s.title.get_text(' ',strip=True) if s.title else '')
  print('links',[(a.get('href'),a.get_text(' ',strip=True)[:100]) for a in s.select('a[href]') if re.search(r'/imovel/',a.get('href',''))][:4])
  print('forms',[(f.get('action'),[(x.get('name'),x.get('value')) for x in f.select('[name]')][:20]) for f in s.select('form')][:2])
  print('scripts',[(x.get('type'),len(x.get_text())) for x in s.select('script') if 'ld+json' in x.get('type','') or '__NEXT_DATA__' in x.get('id','')])
  print('pagination',[(a.get('href'),a.get_text(' ',strip=True)) for a in s.select('a[href]') if re.search(r'pag|page=',a.get('href',''),re.I)][:5])
  if name=='myx':
   a=next((a for a in s.select('a[href]') if '/imovel/' in a.get('href','')),None)
   if a:print('FIRSTCARD',str(a)[:4500])
   for node in s.select('script[type="application/ld+json"]'):
    try:
     j=json.loads(node.get_text());print('JSONLD',str(j)[:1000])
    except ValueError:pass
 except Exception as e:print(name,type(e).__name__)
