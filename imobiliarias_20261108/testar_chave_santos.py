import importlib.util
import sys
from pathlib import Path

path=Path(__file__).resolve().parent.parent/'novos_monitores'/'monitor_universal.py'
spec=importlib.util.spec_from_file_location('monitor_universal',path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
site=sys.argv[1] if len(sys.argv)>1 else 'chave_santos'
items=m.fetch(site)
print('Anúncios:',len(items))
basic=[item for item in items.values() if m.norm(item.get('cidade'))=='santos' and m.norm(item.get('bairro')) in m.B and m.norm(item.get('tipo'))=='apartamento']
print('Apartamento em bairro solicitado:',len(basic))
for item in basic[:2]: print('AMOSTRA', {k:item.get(k) for k in ('codigo','titulo','url_amigavel','bairro','valor','valorcondominio','areaprincipal','areainterna','areaprincipaltratado','numeroquartos','numerovagas','numeroandar')})
if basic: print('CHAVES',list(basic[0]))
errors=[]
for key,item in items.items():
 try:
  ok,url=m.matches(site,item)
  if ok: print('APROVADO',key,item.get('bairro'),item.get('valor'),item.get('valorcondominio'),item.get('areaprincipal'),url)
 except Exception as e: errors.append((key,type(e).__name__,str(e)[:100]))
print('Fichas com erro:',errors)
if errors: raise SystemExit(1)
