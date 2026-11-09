import importlib.util
import sys

path = '/home/opc/update_condo_20261108/monitor_universal.py'
spec = importlib.util.spec_from_file_location('monitor_universal', path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module.detail = lambda site, item: ('https://example.com/imovel', '')
item = {'cidade': 'Santos', 'bairro': 'Marapé', 'tipo': 'Apartamento',
        'valor': 425000, 'areaprincipal': 70, 'numeroquartos': 2,
        'numerovagas': 1, 'numeroandar': None}
assert module.matches('multiverso', item)[0]
assert module.matches('multiverso', {**item, 'valorcondominio': 0})[0]
assert not module.matches('multiverso', {**item, 'valorcondominio': 801})[0]
assert not module.matches('multiverso', {**item, 'numeroandar': 0})[0]
assert not module.matches('multiverso', {**item, 'descricao': 'apartamento térreo'})[0]
print('Filtros: condomínio e andar ausentes aceitos; limite e térreo respeitados.')
