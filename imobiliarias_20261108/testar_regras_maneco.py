import importlib.util
from pathlib import Path
spec=importlib.util.spec_from_file_location('monitor_universal',Path(__file__).resolve().parent.parent/'novos_monitores'/'monitor_universal.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Response:
 def __init__(self, text):self.content=text.encode('utf-8')
 def raise_for_status(self):pass
def match(description, fee):
 tax='' if fee is None else f'<div><p class="p-cinza">Condomínio</p><h6>R$ {fee}</h6></div>'
 html=f'<div class="container-esquerda"><h1>Apartamento</h1><p class="descricao">{description}</p></div>{tax}'
 m.SESSION.get=lambda *args,**kw:Response(html)
 item={'codigo':1,'url_amigavel':'ap-1','bairro':'Campo Grande','cidade':'Santos','tipo':'Apartamento',
       'valor':'R$ 425.000,00','areainterna':'70,00','numeroquartos':'2','numerovagas':'1'}
 return m.matches('maneco',item)[0]
assert match('Apartamento em Santos',None)
assert match('Apartamento em Santos','800,00')
assert not match('Apartamento em Santos','801,00')
assert not match('Apartamento térreo','500,00')
assert not match('Apartamento sem vaga','500,00')
print('Maneco: área, condomínio ausente/limite, térreo e vaga verificados')
