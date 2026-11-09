import requests,re
u='https://static-sites.kenlo.io/2.4.20/widgets/search/assets/bundle.min.js'
r=requests.get(u,timeout=30);r.raise_for_status()
for term in ('preco','preço','price','bedroom','area','pagina'):
 print('\n##',term)
 hits=list(re.finditer(re.escape(term),r.text,re.I))[:12]
 for h in hits: print(r.text[max(0,h.start()-110):h.end()+160])
