import requests,re
base='https://www.chavesantosimoveis.com.br/'
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0','X-Requested-With':'XMLHttpRequest'})
for path in ('assets/js/busca/funcoesAuxiliaresBusca.js','assets/js/busca/index.js'):
 try:
  r=s.get(base+path,timeout=20); print(path,r.status_code,len(r.content),r.url)
  if 'javascript' in r.headers.get('content-type','') or path.endswith('.js'):
   if path.endswith('index.js'):
    for match in re.finditer('retornar-imoveis-disponiveis',r.text): print('CONTEXTO',r.text[match.start()-200:match.start()+650])
   for line in r.text.splitlines():
    if re.search(r'(url:|retornar-imoveis)',line,re.I): print(line.strip()[:240])
 except Exception as e:print(type(e).__name__)
