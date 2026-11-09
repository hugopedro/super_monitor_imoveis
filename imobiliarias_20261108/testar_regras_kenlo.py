import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('monitor_universal',Path(__file__).resolve().parent.parent/'novos_monitores'/'monitor_universal.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Response:
    def __init__(self, body): self.content=body.encode('utf-8')
    def raise_for_status(self): pass

def run(description, fee=None, **changes):
    taxes='' if fee is None else f'<div class="taxes"><span class="tax">Condomínio R$ {fee}</span></div>'
    html=f'<html><div class="box-description">{description}</div>{taxes}</html>'
    m.SESSION.get=lambda *args,**kwargs:Response(html)
    item={'codigo':'AP1','url':'https://www.torresprime.com.br/imovel/a/AP1',
          'cidade':'Santos','tipo':'Apartamento','bairro':'Marapé','valor':'425.000',
          'areaprincipal':'75','numeroquartos':'2','numerovagas':'1'}
    item.update(changes)
    return m.matches('torres_prime',item)[0]

assert run('Apartamento em prédio residencial')
assert run('Apartamento em prédio residencial', '800')
assert not run('Apartamento em prédio residencial', '801')
assert not run('Apartamento térreo', '300')
assert not run('Apartamento sem vaga de garagem', '300')
assert run('Apartamento com vaga coletiva', None, numerovagas=None)
assert not run('Apartamento em prédio residencial', '300', numeroquartos='3')
print('Regras Kenlo: condomínio, piso, vagas coletivas, quartos e teto verificados')
