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

LOCAL = os.environ.get('REPORT_LOCAL') == '1' or not Path('/home/opc').exists()
ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'relatorio_coletado_principal' if LOCAL else Path('/home/opc/relatorio_imoveis_20261108_principal')
OUT_SECUNDARIO = ROOT / 'relatorio_coletado' if LOCAL else Path('/home/opc/relatorio_imoveis_20261108')
OUT.mkdir(exist_ok=True)
OUT_SECUNDARIO.mkdir(exist_ok=True)
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

def published_info(url, item_id=None):
    pub_date = None
    upd_date = None
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        node = soup.select_one('.dateUpdated')
        if node:
            upd_text = node.get_text(' ', strip=True)
            if upd_text:
                upd_date = upd_text.split()[0]
        for tag in soup.select('meta[property="article:published_time"], meta[itemprop="datePublished"], meta[name="datePublished"]'):
            if tag.get('content'):
                return tag['content'], upd_date
        listing_types = {'RealEstateListing', 'Offer', 'Product', 'Residence', 'Apartment', 'SingleFamilyResidence'}
        for tag in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(tag.string or tag.get_text())
                stack = [data]
                while stack:
                    obj = stack.pop()
                    if isinstance(obj, list):
                        stack.extend(obj)
                    elif isinstance(obj, dict):
                        raw_type = obj.get('@type')
                        types = set(raw_type) if isinstance(raw_type, list) else ({raw_type} if raw_type else set())
                        stamp = obj.get('datePublished') or obj.get('datePosted')
                        if stamp and (types & listing_types):
                            return stamp, upd_date
                        if obj.get('datePublished') and 'WebPage' in types:
                            obj_url = str(obj.get('url') or '')
                            if (item_id and f'/id-{item_id}/' in obj_url) or obj_url.rstrip('/') == url.rstrip('/'):
                                pub_date = obj['datePublished']
                        stack.extend(obj.values())
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return pub_date, upd_date

def published(url, item_id=None):
    return published_info(url, item_id)[0]

def save(site, rows, errors, total, out_dir=OUT, label=None):
    path = out_dir / (site + '.json')
    if PRESERVE_ON_RETRY and errors and not rows and path.exists():
        previous = json.loads(path.read_text(encoding='utf-8'))
        if previous.get('rows'):
            rows = previous['rows']
            total = previous.get('total', total)
            errors = list(previous.get('errors', [])) + errors
    path.write_text(json.dumps({'site': site, 'rows': rows, 'errors': errors, 'total': total}, ensure_ascii=False, indent=2), encoding='utf-8')
    tag = f'{site} [{label}]' if label else site
    print(tag, 'total', total, 'aceitos', len(rows), 'erros', len(errors), flush=True)

def evaluate_universal(m, site, item):
    """Avalia um anúncio universal para ambos os perfis (principal e secundário)."""
    if site == 'maneco':
        item['areaprincipal'] = item.get('areaprincipal') or item.get('areainterna')
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
    details_may_fill = site in m.DIRECT_DETAIL_SITES or site in ('chaves', 'maneco')
    cand_primary = (neighborhood in m.A and price is not None and 0 < price <= 530000
                    and (condo is None or 0 <= condo <= 1100))
    cand_secondary = (neighborhood in m.B and price is not None and 0 < price <= 426000
                      and (condo is None or 0 <= condo <= 800))
    if (city != 'santos' or (not cand_primary and not cand_secondary)
            or (area is None and not details_may_fill) or (area is not None and area < 70)
            or (rooms is None and not details_may_fill) or (rooms is not None and rooms != 2)
            or ((spots is None or spots < 1) and not collective and not details_may_fill)):
        return False, False, False
    _, match_url = m.matches(site, item)  # Busca e registra evidências da ficha quando aplicável.
    if match_url and not item.get('url'):
        item['url'] = match_url
    if item.get('_unavailable'):
        return False, False, False
    if (site in m.KENLO and not item.get('_kenlo_validated')) or (site == 'maneco' and not item.get('_maneco_validated')):
        return False, False, False
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
    if collective and (spots is None or spots < 1):
        item['numerovagas'] = '1 coletiva'
    elevator_count = m.number(item.get('numeroelevador'))
    has_elevator = ((elevator_count is not None and elevator_count > 0)
                    or bool(re.search(r'\belevador(?:es)?\b|\belevator\b', text)))
    no_elevator = bool(re.search(r'\b(?:sem|nao possui|nao tem)\s+elevador(?:es)?\b', text))
    elevator_confirmed = has_elevator and not no_elevator
    address = m.norm(item.get('endereco'))
    avenue = bool(re.match(r'^(avenida|av)\b', address))
    title_norm = m.norm(item.get('titulo'))
    rental_only = bool(re.search(r'\b(?:para\s+locacao|para\s+alugar|locacao)\b', title_norm)
                       and not re.search(r'\bvenda\b', title_norm))
    excluded_text = bool(re.search(r'\bterreo\b|\bgarden\b|\bquintal\b|\bbackyard\b', text)
                         or m.norm(item.get('quintal')) in {'1', 'true', 'sim'}
                         or rental_only)
    base_ok = bool(
        city == 'santos' and 'apartamento' in kind and 'garden' not in kind and 'terreo' not in kind
        and price is not None and price >= 50000
        and area is not None and area >= 70 and rooms == 2
        and ((spots is not None and spots >= 1) or collective)
        and floor != 0 and not excluded_text
    )
    ok_primary = bool(
        base_ok and neighborhood in m.A and price <= 530000
        and (condo is None or 0 <= condo <= 1100)
        and elevator_confirmed
        and not avenue and not item.get('_address_unverified')
    )
    ok_secondary = bool(
        base_ok and neighborhood in m.B and price <= 426000
        and (condo is None or 0 <= condo <= 800)
    )
    return ok_primary, ok_secondary, elevator_confirmed

def primary_universal(m, site, item):
    """Revalida um anúncio universal exclusivamente pelo perfil principal."""
    return evaluate_universal(m, site, item)[0]

def universal(site):
    m = load('universal_' + site, source('universal'))
    m.REPORT_PRIMARY_ONLY = True
    items = m.fetch(site)
    def evaluate(entry):
        code, item = entry
        try:
            ok_p, ok_s, elev_ok = evaluate_universal(m, site, item)
            if not ok_p and not ok_s:
                return None
            url = item.get('url', '')
            if not url:
                return {'error': str(code) + ': sem URL'}
            full_url = urljoin(m.SITE[site][0], url)
            if 'data_publicacao' in item and item.get('data_publicacao') is not None:
                pub_date, upd_date = item.get('data_publicacao'), item.get('data_atualizacao_preco')
            else:
                pub_date, upd_date = published_info(full_url, code)
            addr_norm = m.norm(item.get('endereco'))
            clean_addr = (
                item.get('endereco')
                if addr_norm
                and not item.get('_address_unverified')
                and 'indisponivel' not in addr_norm
                and 'aproximada' not in addr_norm
                and not (site == 'prime_trade' and addr_norm.startswith('rua da paz'))
                else None
            )
            row = {'site': site, 'id': code, 'url': full_url,
                   'bairro': item.get('bairro'), 'preco': m.number(item.get('valor')),
                   'condominio': m.number(item.get('valorcondominio')), 'area': m.number(item.get('areaprincipal')),
                   'quartos': item.get('numeroquartos'), 'vagas': item.get('numerovagas'),
                   'elevador': 'Confirmado' if elev_ok else None, 'endereco': clean_addr,
                   'titulo': str(item.get('titulo') or '')[:250], 'data_publicacao': pub_date}
            if upd_date:
                row['data_atualizacao_preco'] = upd_date
            return {'row': row, 'primary': ok_p, 'secondary': ok_s}
        except Exception as e:
            return {'error': str(code) + ': ' + type(e).__name__}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(evaluate, items.items()))
    errors = [v['error'] for v in found if v and 'error' in v]
    rows_p = [dict(v['row'], elevador='Confirmado') for v in found if v and v.get('primary')]
    rows_s = [dict(v['row']) for v in found if v and v.get('secondary')]
    save(site, rows_p, errors, len(items), OUT, 'principal')
    save(site, rows_s, errors, len(items), OUT_SECUNDARIO, 'secundario')

def portal(site):
    path = source(site)
    if site == 'zap':
        import types
        stub = types.ModuleType('visual_analyzer')
        stub.VisualPropertyAnalyzer = lambda: None
        sys.modules['visual_analyzer'] = stub
    m = load('portal_' + site, path)
    cls = m.VivaRealMonitor if site == 'vivareal' else m.ZapImoveisMonitor
    monitor = cls('unused', 'unused')
    prof_p = [p for p in monitor.purchase_profiles if p['name'] == 'principal']
    prof_s = [p for p in monitor.purchase_profiles if p['name'] == 'paralelo']
    rows_p, rows_s, errors, total, page = [], [], [], 0, 1
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
            pricing_list = d.get('pricingInfos') or []
            price = next(
                (p for p in pricing_list if p.get('businessType') == 'SALE'),
                next((p for p in pricing_list if not p.get('businessType')), {}),
            )
            first = lambda v: v[0] if isinstance(v, list) and v else (None if isinstance(v, list) else v)
            item = {'id': d.get('id'), 'title': d.get('title'), 'price': price.get('price'), 'address': d.get('address') or {},
                    'bedrooms': first(d.get('bedrooms')), 'parkingSpaces': first(d.get('parkingSpaces')),
                    'usableAreas': first(d.get('usableAreas')), 'monthlyCondoFee': price.get('monthlyCondoFee'),
                    'unitFloor': d.get('unitFloor'), 'amenities': d.get('amenities', []), 'unitSubTypes': d.get('unitSubTypes', [])}
            num_price = monitor._numeric_value(item['price'])
            if num_price is None or num_price < 50000:
                continue
            amenities = item.get('amenities') or []
            amenity_text = ' '.join(map(str, amenities if isinstance(amenities, list) else [amenities]))
            title_and_amenities = (str(item.get('title') or '') + ' ' + amenity_text).casefold()
            collective = 'coletiv' in title_and_amenities
            has_elev = ('elevator' in amenity_text.casefold() or 'elevador' in amenity_text.casefold()
                        or ('elevador' in str(item.get('title') or '').casefold() and 'sem elevador' not in str(item.get('title') or '').casefold()))
            checked_item = dict(item)
            if collective and monitor._numeric_value(checked_item.get('parkingSpaces')) is None:
                checked_item['parkingSpaces'] = 1
            monitor.purchase_profiles = prof_p
            ok_p = monitor.matches_purchase_profile(checked_item)
            monitor.purchase_profiles = prof_s
            ok_s = monitor.matches_purchase_profile(checked_item)
            if ok_p or ok_s:
                base_row = {'site': site, 'id': item['id'], 'url': f'https://www.{"vivareal" if site == "vivareal" else "zapimoveis"}.com.br/imovel/{item["id"]}/',
                            'bairro': item['address'].get('neighborhood'), 'endereco': item['address'].get('street'),
                            'preco': num_price, 'condominio': monitor._numeric_value(item['monthlyCondoFee']),
                            'area': monitor._numeric_value(item['usableAreas']), 'quartos': item['bedrooms'], 'vagas': item['parkingSpaces'],
                            'elevador': 'Confirmado' if has_elev else None, 'titulo': item['title'], 'data_publicacao': d.get('createdAt')}
                if ok_p:
                    rows_p.append(dict(base_row, elevador='Confirmado'))
                if ok_s:
                    rows_s.append(dict(base_row))
        count = data.get('totalCount') or data['search'].get('totalCount') or result.get('totalCount')
        if page * monitor.page_size >= 1000 or (count is not None and page * monitor.page_size >= int(count)) or len(listings) < monitor.page_size: break
        page += 1
    save(site, rows_p, errors, total, OUT, 'principal')
    save(site, rows_s, errors, total, OUT_SECUNDARIO, 'secundario')

def invista():
    m = load('invista', source('invista'))
    monitor_p = m.MonitorImoveis('unused', 'unused')
    monitor_s = m.MonitorImoveis('unused', 'unused')
    monitor_p.purchase_profiles = [p for p in monitor_p.purchase_profiles if p['name'] == 'principal']
    monitor_s.purchase_profiles = [p for p in monitor_s.purchase_profiles if p['name'] == 'paralelo']
    items = monitor_p.buscar_imoveis_site()
    def evaluate(item):
        rooms = monitor_p._numero(item.get('numeroquartos'))
        area = monitor_p._numero(item.get('areaprincipal'))
        if (rooms is not None and rooms != 2) or (area is not None and area < 70):
            return None
        if not monitor_p.buscar_detalhes_imovel(item):
            return None
        ok_p = monitor_p.corresponde_a_perfil(item)
        ok_s = monitor_s.corresponde_a_perfil(item)
        if not ok_p and not ok_s:
            return None
        elev_ok = bool(monitor_p._numero(item.get('numeroelevador')))
        row = {'site': 'invista', 'id': item['codigo'], 'url': item['url'], 'bairro': item['bairro'],
               'preco': monitor_p._numero(item['valor']), 'condominio': monitor_p._numero(item['valorcondominio']),
               'area': monitor_p._numero(item['areaprincipal']), 'quartos': item['numeroquartos'], 'vagas': item['numerovagas'],
               'elevador': 'Confirmado' if elev_ok else None, 'endereco': item.get('endereco'),
               'titulo': item['titulo'], 'data_publicacao': published(item['url'], item['codigo'])}
        return {'row': row, 'primary': ok_p, 'secondary': ok_s}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        found = [x for x in pool.map(evaluate, items) if x]
    rows_p = [dict(x['row'], elevador='Confirmado') for x in found if x['primary']]
    rows_s = [dict(x['row']) for x in found if x['secondary']]
    errors = ['Busca retornou zero anúncios; possível falha de consulta'] if not items else []
    save('invista', rows_p, errors, len(items), OUT, 'principal')
    save('invista', rows_s, errors, len(items), OUT_SECUNDARIO, 'secundario')

def r3():
    m = load('r3', source('r3'))
    monitor_p = m.R3ImoveisMonitor('unused', 'unused')
    monitor_s = m.R3ImoveisMonitor('unused', 'unused')
    monitor_p.purchase_profiles = [p for p in monitor_p.purchase_profiles if p['name'] == 'principal']
    monitor_s.purchase_profiles = [p for p in monitor_s.purchase_profiles if p['name'] == 'paralelo']
    items, seen, errors = [], set(), []
    for page in range(1, 11):
        batch = monitor_p.fetch_properties(page)
        if not batch:
            if page == 1:
                errors.append('Primeira página vazia ou falha de conexão')
            break
        new = [x for x in batch if x['id'] not in seen]
        if not new: break
        seen.update(x['id'] for x in new)
        items.extend(x for x in new if monitor_p.passes_search_filters(x)[0] or monitor_s.passes_search_filters(x)[0])
    def evaluate(item):
        if not monitor_p.fetch_property_details(item):
            return None
        ok_p = monitor_p.passes_full_filters(item)[0]
        ok_s = monitor_s.passes_full_filters(item)[0]
        if not ok_p and not ok_s:
            return None
        elev_ok = bool(item.get('has_elevator'))
        row = {'site': 'r3', 'id': item['id'], 'url': item['url'], 'bairro': item['neighborhood'],
               'preco': item['price'], 'condominio': item.get('condo_fee'), 'area': item['area'],
               'quartos': item['bedrooms'], 'vagas': item['parking'],
               'elevador': 'Confirmado' if elev_ok else None, 'endereco': item.get('address'),
               'titulo': item['title'], 'data_publicacao': published(item['url'], item['id'])}
        return {'row': row, 'primary': ok_p, 'secondary': ok_s}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        found = [x for x in pool.map(evaluate, items) if x]
    rows_p = [dict(x['row'], elevador='Confirmado') for x in found if x['primary']]
    rows_s = [dict(x['row']) for x in found if x['secondary']]
    save('r3', rows_p, errors, len(seen), OUT, 'principal')
    save('r3', rows_s, errors, len(seen), OUT_SECUNDARIO, 'secundario')

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

if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('Uso: python relatorio_coleta.py all|FONTE')
    if sys.argv[1] == 'all':
        for site in ALL_SITES:
            try:
                collect(site)
            except Exception as exc:
                err = [type(exc).__name__ + ': ' + str(exc)[:250]]
                save(site, [], err, 0, OUT, 'principal')
                save(site, [], err, 0, OUT_SECUNDARIO, 'secundario')
    elif sys.argv[1] == 'retry':
        PRESERVE_ON_RETRY = True
        retry_sites = ['zap', 'r3', 'invista', 'chave_santos', 'maneco', 'torres_prime',
                       'viver_em_santos', 'bw', 'multiverso', 'chaves']
        for site in retry_sites:
            try:
                collect(site)
            except Exception as exc:
                err = [type(exc).__name__ + ': ' + str(exc)[:250]]
                save(site, [], err, 0, OUT, 'principal')
                save(site, [], err, 0, OUT_SECUNDARIO, 'secundario')
    else:
        for site in sys.argv[1:]:
            try:
                collect(site)
            except Exception as exc:
                err = [type(exc).__name__ + ': ' + str(exc)[:250]]
                save(site, [], err, 0, OUT, 'principal')
                save(site, [], err, 0, OUT_SECUNDARIO, 'secundario')
