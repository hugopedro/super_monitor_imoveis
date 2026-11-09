import importlib.util
from pathlib import Path

path=Path(__file__).resolve().parent.parent/'novos_monitores'/'monitor_universal.py'
spec=importlib.util.spec_from_file_location('monitor_universal',path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
for site in sorted(m.KENLO):
    items=m.fetch(site)
    matched=[]
    for code,item in items.items():
        ok,url=m.matches(site,item)
        if ok: matched.append((code,item.get('bairro'),item.get('valor'),item.get('valorcondominio'),url))
    print(site,'candidatos no bairro',len(items),'compatíveis',len(matched),flush=True)
    for row in matched: print(' ',row,flush=True)
