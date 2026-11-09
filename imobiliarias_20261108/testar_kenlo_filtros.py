import requests,bs4
urls=['https://www.myximoveis.com.br/imoveis/a-venda/apartamento/santos',
      'https://www.myximoveis.com.br/imoveis/a-venda/apartamento/santos?preco-de-venda=~426000',
      'https://www.torresprime.com.br/imoveis/a-venda/apartamento/santos?preco-de-venda=~426000']
for url in urls:
 r=requests.get(url,headers={'User-Agent':'Mozilla/5.0'},timeout=30);s=bs4.BeautifulSoup(r.content,'html.parser')
 print(r.status_code,r.url,s.title.get_text(' ',strip=True) if s.title else 'sem título')
 print([a.get_text(' ',strip=True)[:160] for a in s.select('a.card-with-buttons[href]')][:3])
