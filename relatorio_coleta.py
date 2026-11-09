import concurrent.futures
import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

LOCAL = os.environ.get('REPORT_LOCAL') == '1'
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'relatorio_coletado_principal' if LOCAL else Path('/home/opc/relatorio_imoveis_20261108_principal')
OUT.mkdir(exist_ok=True)
BASE = Path('/home/opc')
PRESERVE_ON_RETRY = False

def source(name):
    if LOCAL:
        if name == 'universal': return ROOT/'novos_monitores/monitor_universal.py'
        return ROOT/'r3-work-20261108/purchase-sources'/('monitor_' + name + '.py')
    return BASE / {'universal': 'monitor_rhema_multiverso/monitor_universal.py',
                   'vivareal': 'monitor_vivareal_comprar/monitor.py', 'zap': 'monitor_zapimoveis_ocr/monitor.py',
                   'invista': 'monitor_invista/monitor_final.py', 'r3': 'monitor_r3_comprar/monitor.py'}[name]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

def published(url):
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        for tag in soup.select('meta[property="article:published_time"], meta[itemprop="datePublished"], meta[name="datePublished"]'):
            if tag.get('content'):
                return tag['content']
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(tag.string or tag.get_text())
                stack = [data]
                while stack:
                    obj = stack.pop()
                    if isinstance(obj, list):
                        stack.extend(obj)
                    elif isinstance(obj, dict):
                        if obj.get('datePublished') and obj.get('@type') in ('RealEstateListing', 'Offer', 'Product', 'Residence', 'Apartment', 'SingleFamilyResidence'):
                            return obj['datePublished']
                        stack.extend(obj.values())
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return None

def save(site, rows, errors, total):
    path = OUT / (site + '.json')
    if PRESERVE_ON_RETRY and errors and not rows and path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if previous.get('rows'):
            rows = previous['rows']
            total = previous.get('total', total)
            errors = list(previous.get('errors', [])) + errors
    path.write_text(json.dumps({'site': site, 'rows': rows, 'errors': errors, 'total': total}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(site, 'total', total, 'aceitos', len(rows), 'erros', len(errors), flush=True)

def primary_universal(m, site, item):
    """Revalida um anúncio universal exclusivamente pelo perfil principal."""
    neighborhood = m.norm(item.get('bairro'))
    city = m.norm(item.get('cidade'))
    price = m.number(item.get('valor'))
    condo = m.number(item.get('valorcondominio'))
    area = m.number(item.get('areaprincipal'))
    rooms = m.number(item.get('numeroquartos'))
    spots = m.number(item.get('numerovagas'))
    preliminary_text = m.norm(' '.join(str(item.get(key) or '') for key in (
        'titulo', 'tipo', 'descricao', 'tipovagas'
    )))
    collective = ('coletiv' in m.norm(item.get('tipovagas'))
                  or bool(re.search(r'\b(?:vaga|garagem)\s+coletiva\b', preliminary_text)))
    details_may_fill = site in m.DIRECT_DETAIL_SITES or site == 'chaves'
    if (city != 'santos' or neighborhood not in m.A or price is None or price <= 0 or price > 530000
            or (condo is not None and (condo < 0 or condo > 1100))
            or (area is None and not details_may_fill) or (area is not None and area < 70)
            or (rooms is None and not details_may_fill) or (rooms is not None and rooms != 2)
            or ((spots is None or spots < 1) and not collective and not details_may_fill)):
        return False
    m.matches(site, item)  # Busca e registra evidências da ficha quando aplicável.
    detail = ' '.join(str(item.get(key) or '') for key in (
        '_report_detail_text', '_kenlo_text', '_unsoft_text', 'descricao',
        '_bw_amenities', 'titulo', 'tipo', 'tipovagas'
    ))
    text = m.norm(detail)
    neighborhood = m.norm(item.get('bairro'))
    city = m.norm(item.get('cidade'))
    kind = m.norm(item.get('tipo'))
    price = m.number(item.get('valor'))
    condo = m.number(item.get('valorcondominio'))
    area = m.number(item.get('areaprincipal'))
    rooms = m.number(item.get('numeroquartos'))
    spots = m.number(item.get('numerovagas'))
    floor = m.number(item.get('numeroandar'))
    collective = ('coletiv' in m.norm(item.get('tipovagas'))
                  or bool(re.search(r'\b(?:vaga|garagem)\s+coletiva\b', text)))
    elevator_count = m.number(item.get('numeroelevador'))
    has_elevator = ((elevator_count is not None and elevator_count > 0)
                    or bool(re.search(r'\belevador(?:es)?\b', text)))
    no_elevator = bool(re.search(r'\b(?:sem|nao possui|nao tem)\s+elevador(?:es)?\b', text))
    address = m.norm(item.get('endereco'))
    avenue = bool(re.match(r'^(avenida|av)\b', address))
    excluded_text = bool(re.search(r'\bterreo\b|\bgarden\b|\bquintal\b', text))
    return bool(
        city == 'santos' and neighborhood in m.A and 'apartamento' in kind
        and price is not None and 0 < price <= 530000
        and area is not None and area >= 70 and rooms == 2
        and (condo is None or 0 <= condo <= 1100)
        and ((spots is not None and spots >= 1) or collective)
        and floor != 0 and not excluded_text
        and has_elevator and not no_elevator
        and not avenue and not item.get('_address_unverified')
    )

def universal(site):
    m = load('universal', source('universal'))
    m.REPORT_PRIMARY_ONLY = True
    items = m.fetch(site)
    def evaluate(entry):
        code, item = entry
        try:
            if not primary_universal(m, site, item):
                return None
            url = item.get('url', '')
            if not url:
                return {'error': str(code) + ': sem URL'}
            return {'site': site, 'id': code, 'url': urljoin(m.SITE[site][0], url),
                    'bairro': item.get('bairro'), 'preco': m.number(item.get('valor')),
                    'condominio': m.number(item.get('valorcondominio')), 'area': m.number(item.get('areaprincipal')),
                    'quartos': item.get('numeroquartos'), 'vagas': item.get('numerovagas'),
                    'elevador': 'Confirmado', 'endereco': item.get('endereco'),
                    'titulo': str(item.get('titulo') or '')[:250], 'data_publicacao': published(urljoin(m.SITE[site][0], url))}
        except Exception as e:
            return {'error': str(code) + ': ' + type(e).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        found = list(pool.map(evaluate, items.items()))
    save(site, [v for v in found if v and 'error' not in v], [v['error'] for v in found if v and 'error' in v], len(items))

def portal(site):
    path = source(site)
    if site == 'zap':
        import types
        stub = types.ModuleType('visual_analyzer')
        stub.VisualPropertyAnalyzer = lambda: None
        sys.modules['visual_analyzer'] = stub
    m = load('portal', path)
    cls = m.VivaRealMonitor if site == 'vivareal' else m.ZapImoveisMonitor
    monitor = cls('unused', 'unused')
    monitor.purchase_profiles = [p for p in monitor.purchase_profiles if p['name'] == 'principal']
    rows, errors, total, page = [], [], 0, 1
    while True:
        data = monitor.fetch_listings(page)
        if not data or 'search' not in data:
            errors.append('Falha na página ' + str(page)); break
        result = data['search'].get('result', {})
        listings = result.get('listings', [])
        if not listings: break
        total += len(listings)
        for raw in listings:
            d = raw.get('listing', {})
            price = (d.get('pricingInfos') or [{}])[0]
            first = lambda v: v[0] if isinstance(v, list) and v else (None if isinstance(v, list) else v)
            item = {'id': d.get('id'), 'title': d.get('title'), 'price': price.get('price'), 'address': d.get('address') or {},
                    'bedrooms': first(d.get('bedrooms')), 'parkingSpaces': first(d.get('parkingSpaces')),
                    'usableAreas': first(d.get('usableAreas')), 'monthlyCondoFee': price.get('monthlyCondoFee'),
                    'unitFloor': d.get('unitFloor'), 'amenities': d.get('amenities', []), 'unitSubTypes': d.get('unitSubTypes', [])}
            amenities = item.get('amenities') or []
            amenity_text = ' '.join(map(str, amenities if isinstance(amenities, list) else [amenities]))
            collective = 'coletiv' in (str(item.get('title') or '') + ' ' + amenity_text).casefold()
            checked_item = dict(item)
            if collective and monitor._numeric_value(checked_item.get('parkingSpaces')) is None:
                checked_item['parkingSpaces'] = 1
            if monitor.matches_purchase_profile(checked_item):
                rows.append({'site': site, 'id': item['id'], 'url': f'https://www.{"vivareal" if site == "vivareal" else "zapimoveis"}.com.br/imovel/{item["id"]}/',
                             'bairro': item['address'].get('neighborhood'), 'endereco': item['address'].get('street'),
                             'preco': monitor._numeric_value(item['price']), 'condominio': monitor._numeric_value(item['monthlyCondoFee']),
                             'area': monitor._numeric_value(item['usableAreas']), 'quartos': item['bedrooms'], 'vagas': item['parkingSpaces'],
                             'elevador': 'Confirmado', 'titulo': item['title'], 'data_publicacao': d.get('createdAt')})
        count = data['search'].get('totalCount') or result.get('totalCount')
        if (count is not None and page * monitor.page_size >= int(count)) or (count is None and len(listings) < monitor.page_size): break
        page += 1
    save(site, rows, errors, total)

def invista():
    m = load('invista', source('invista'))
    monitor = m.MonitorImoveis('unused', 'unused')
    monitor.purchase_profiles = [p for p in monitor.purchase_profiles if p['name'] == 'principal']
    items = monitor.buscar_imoveis_site()
    def evaluate(item):
        if not monitor.buscar_detalhes_imovel(item) or not monitor.corresponde_a_perfil(item): return None
        return {'site': 'invista', 'id': item['codigo'], 'url': item['url'], 'bairro': item['bairro'],
                'preco': monitor._numero(item['valor']), 'condominio': monitor._numero(item['valorcondominio']),
                'area': monitor._numero(item['areaprincipal']), 'quartos': item['numeroquartos'], 'vagas': item['numerovagas'],
                'elevador': 'Confirmado', 'endereco': item.get('endereco'),
                'titulo': item['titulo'], 'data_publicacao': published(item['url'])}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: rows = [x for x in pool.map(evaluate, items) if x]
    errors = ['Busca retornou zero anúncios; possível falha de consulta'] if not items else []
    save('invista', rows, errors, len(items))

def r3():
    m = load('r3', source('r3'))
    monitor = m.R3ImoveisMonitor('unused', 'unused')
    monitor.purchase_profiles = [p for p in monitor.purchase_profiles if p['name'] == 'principal']
    items, seen, errors = [], set(), []
    for page in range(1, 11):
        batch = monitor.fetch_properties(page)
        if not batch:
            if page == 1:
                errors.append('Primeira página vazia ou falha de conexão')
            break
        new = [x for x in batch if x['id'] not in seen]
        if not new: break
        seen.update(x['id'] for x in new)
        items.extend(x for x in new if monitor.passes_search_filters(x)[0])
    def evaluate(item):
        if not monitor.fetch_property_details(item) or not monitor.passes_full_filters(item)[0]: return None
        return {'site': 'r3', 'id': item['id'], 'url': item['url'], 'bairro': item['neighborhood'],
                'preco': item['price'], 'condominio': item.get('condo_fee'), 'area': item['area'],
                'quartos': item['bedrooms'], 'vagas': item['parking'],
                'elevador': 'Confirmado', 'endereco': item.get('address'),
                'titulo': item['title'], 'data_publicacao': published(item['url'])}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool: rows = [x for x in pool.map(evaluate, items) if x]
    save('r3', rows, errors, len(seen))

UNIVERSAL_SITES = [
    'chave_santos', 'maneco', 'torres_prime', 'myx', 'raiz', 'mape', 'listagem', 'expoente',
    'pousada', 'rochedo', 'lopes_conceito', 'prime_trade', 'balduino', 'cerejo', 'casabella',
    'familia', 'viver_em_santos', 'gavea', 'fabricio', 'bw', 'remax_evoke_iv', 'rhema',
    'multiverso', 'roda', 'proprietario', 'chaves',
]
ALL_SITES = ['vivareal', 'zap', 'r3', 'invista', *UNIVERSAL_SITES]

def collect(site):
    if site in ('vivareal', 'zap'):
        portal(site)
    elif site == 'invista':
        invista()
    elif site == 'r3':
        r3()
    elif site in UNIVERSAL_SITES:
        universal(site)
    else:
        raise ValueError('Fonte desconhecida: ' + site)

if len(sys.argv) < 2:
    raise SystemExit('Uso: python relatorio_coleta.py all|FONTE')
if sys.argv[1] == 'all':
    for site in ALL_SITES:
        try:
            collect(site)
        except Exception as exc:
            save(site, [], [type(exc).__name__ + ': ' + str(exc)[:250]], 0)
elif sys.argv[1] == 'retry':
    PRESERVE_ON_RETRY = True
    retry_sites = ['zap', 'r3', 'invista', 'chave_santos', 'maneco', 'torres_prime',
                   'viver_em_santos', 'bw', 'multiverso', 'chaves']
    for site in retry_sites:
        try:
            collect(site)
        except Exception as exc:
            save(site, [], [type(exc).__name__ + ': ' + str(exc)[:250]], 0)
else:
    collect(sys.argv[1])
