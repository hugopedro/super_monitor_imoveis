#!/usr/bin/env python3
"""Monitora as buscas públicas de Rhema e Multiverso, com base inicial silenciosa."""
import html
import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('monitor_universal')
SITE = {
    'rhema': ('https://www.rhemaimoveis.com.br/', 'assets/js/objImovel.js', 'retornar-imoveis-disponiveis'),
    'multiverso': ('https://www.multiversoimob.com.br/', 'assets/js/busca/busca.js', 'imoveis/ajax/'),
    'roda': ('https://rodaimoveis.com.br/', '', ''),
    'proprietario': ('https://www.proprietariodireto.com.br/', '', ''),
    'chaves': ('https://www.chavesnamao.com.br/', '', ''),
}
A = {'aparecida', 'boqueirao', 'embare', 'gonzaga', 'pompeia'}
B = A | {'campo grande', 'marape', 'jose menino'}
STATE = Path('state.json')
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest'})


def norm(value):
    value = unicodedata.normalize('NFKD', str(value or '').lower())
    value = ''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^a-z0-9]+', ' ', value).split())


def number(value):
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return None
    raw = re.sub(r'[^0-9,.-]', '', str(value))
    if not raw:
        return None
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', raw):
        raw = raw.replace('.', '')
    try:
        return float(raw)
    except ValueError:
        return None


def defaults(site):
    base, js, _ = SITE[site]
    response = SESSION.get(base + js, timeout=30)
    response.raise_for_status()
    source = response.text.split('var paramentros')[0]
    values = {}
    for key, value in re.findall(r'imovel\.(\w+)\s*=\s*([^;\n]+)', source):
        value = value.strip().split('//')[0].strip()
        if re.fullmatch(r"'[^']*'|\d+|true|false", value):
            values[key] = value.strip("'")
    if len(values) < 15:
        raise RuntimeError('Estrutura da busca mudou; consulta cancelada')
    values.update({'finalidade': 'venda', 'numeroquartos': '2', 'valorate': '530000',
                   'areade': '70', 'numeroregistros': '20'})
    return values


def fetch(site):
    if site == 'roda':
        return fetch_roda()
    if site == 'proprietario':
        return fetch_proprietario()
    if site == 'chaves':
        return fetch_chaves()
    base, _, endpoint = SITE[site]
    values = defaults(site)
    all_items = {}
    previous = None
    for page in range(1, 101):
        values.update({'numeropagina': str(page), 'pagina': str(page)})
        if site == 'rhema':
            data = dict(values)
        else:
            data = {f'imovel[{k}]': v for k, v in values.items()}
            data['imovel[codigoTipo][codigo]'] = ''
        response = SESSION.post(base + endpoint, data=data, timeout=45)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or 'lista' not in result or 'quantidade' not in result:
            raise RuntimeError('Resposta incompleta da busca')
        items = result['lista']
        ids = frozenset(str(item['codigo']) for item in items if item.get('codigo'))
        if ids and ids == previous:
            raise RuntimeError('A paginação repetiu resultados')
        previous = ids
        for item in items:
            if item.get('codigo'):
                all_items[str(item['codigo'])] = item
        total = number(result['quantidade'])
        if not items or len(items) < 20:
            if total is not None and len(all_items) < total:
                raise RuntimeError('Busca retornou menos anúncios que o total informado')
            return all_items
        if total is not None and len(all_items) >= total:
            return all_items
        time.sleep(0.5)
    raise RuntimeError('Busca excedeu o limite de páginas')


def fetch_roda():
    """Divide por bairro e, se necessário, preço para evitar páginas incompletas."""
    neighborhoods = {'aparecida': '23963', 'boqueirao': '23966', 'campo grande': '23967',
                     'embare': '23974', 'gonzaga': '23977', 'jose menino': '23980',
                     'marape': '23982', 'pompeia': '51757'}
    result = {}

    def search(neighborhood, code, low, high):
        params = [('finalidade', 'sale'), ('tipo[5]', '5'), ('cidade[]', '9636'),
                  ('bairro[]', code), ('dormitorio', '2'), ('medida[MIN]', '70'),
                  ('valor[MIN]', str(low)), ('valor[MAX]', str(high)), ('order', 'data_cadastro')]
        response = SESSION.get('https://rodaimoveis.com.br/imoveis/', params=params,
                               headers={'X-Requested-With': None}, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = norm(soup.get_text(' ', strip=True))
        cards = soup.select('div.LI_Imovel')
        match = re.search(r'foram encontrados\s+(\d+)\s+imoveis', page_text)
        if 'nao foi encontrado nenhum imovel' in page_text:
            total = 0
        elif 'foi encontrado apenas um imovel' in page_text:
            total = 1
        elif match:
            total = int(match.group(1))
        else:
            raise RuntimeError('Roda não informou o total de resultados')
        if total > len(cards):
            if high - low <= 1:
                raise RuntimeError('Roda: resultados excedem o limite da página')
            mid = (low + high) // 2
            search(neighborhood, code, low, mid)
            search(neighborhood, code, mid, high)
            return
        if total != len(cards):
            raise RuntimeError('Roda: quantidade de cartões inconsistente')
        for card in cards:
            def text(selector):
                node = card.select_one(selector)
                return node.get_text(' ', strip=True) if node else ''
            link = card.select_one('a.Title[href]') or card.select_one('a.ImovelLinkClick[href]')
            code_id = card.get('id')
            if not code_id or not link:
                raise RuntimeError('Roda: cartão sem identificação ou link')
            address = text('.Endereco')
            if 'santos' not in norm(address) or neighborhood not in norm(address):
                continue
            result[str(code_id)] = {
                'codigo': str(code_id), 'tipo': 'Apartamento', 'cidade': 'Santos',
                'bairro': neighborhood, 'valor': text('.ImovelValor .ValorMoeda.valorNaoNulo'),
                'valorcondominio': text('.buildingCondominiumValue .ValorMoeda'),
                'numeroquartos': text('.ResumoItem.BEDROOM'),
                'numerovagas': text('.ResumoItem.GARAGE'),
                'tipovagas': 'coletiva' if 'vaga coletiva' in norm(card.get_text(' ', strip=True)) else '',
                'areaprincipal': text('.ResumoItem.AREA_USEFUL'),
                'numeroelevador': 1 if card.select_one('.Elevador') else 0,
                'titulo': text('a.Title'), 'endereco': address,
                '_address_unverified': True, 'url': link.get('href'),
            }
    for neighborhood, code in neighborhoods.items():
        search(neighborhood, code, 0, 530000)
    return result


def next_data(soup):
    chunks = []
    for script in soup.select('script'):
        value = script.string or ''
        if value.startswith('self.__next_f.push('):
            try:
                payload = json.loads(value[len('self.__next_f.push('):-1])
                if len(payload) > 1 and isinstance(payload[1], str):
                    chunks.append(payload[1])
            except (ValueError, TypeError):
                continue
    return ''.join(chunks)


def fetch_chaves():
    url = SITE['chaves'][0] + 'apartamentos-a-venda/sp-santos/2-quartos/'
    result = {}
    total_pages = None
    previous = None
    page = 1
    while total_pages is None or page <= total_pages:
        if page > 1000:
            raise RuntimeError('Chaves: limite de páginas excedido')
        response = SESSION.get(url, params={'filtro': 'pmax:530000,amin:70', 'pg': str(page)},
                               headers={'X-Requested-With': None}, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        data = next_data(soup)
        paging = re.search(r'"pagination":(\d+),"totalPages":(\d+)', data)
        if not paging or int(paging.group(1)) != page:
            raise RuntimeError('Chaves: estrutura de busca ou página não reconhecida')
        pages_now = int(paging.group(2))
        if total_pages is None:
            total_pages = pages_now
        elif pages_now != total_pages:
            log.warning('chaves: total de páginas variou durante a busca; mantendo o total inicial %d', total_pages)
        offers = None
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                schema = json.loads(script.string or script.get_text())
            except (ValueError, TypeError):
                continue
            if isinstance(schema, dict) and schema.get('@type') == 'RealEstateListing':
                offers = (schema.get('offers') or {}).get('itemListElement')
                break
        if not isinstance(offers, list):
            raise RuntimeError('Chaves: lista estruturada de anúncios ausente')
        ids = frozenset(match.group(1) for offer in offers
                        if (match := re.search(r'/id-(\d+)', offer.get('url', ''))))
        if ids and ids == previous:
            raise RuntimeError('Chaves: página repetida')
        previous = ids
        cards = {str(card.get('id', '')).removeprefix('rc-'): card
                 for card in soup.find_all('div', class_=re.compile(r'card_card__'))
                 if str(card.get('id', '')).startswith('rc-')}
        all_links = {}
        for link in soup.select('a[href]'):
            href = link.get('href', '')
            match = re.search(r'/id-(\d+)', href)
            if match and href.startswith(('/imovel/', '/lancamento/')):
                all_links[match.group(1)] = href
        missing = [code for code in cards if code not in ids and all_links.get(code, '').startswith('/imovel/')]
        if missing:
            raise RuntimeError('Chaves: dados de cartão incompletos')
        for offer in offers:
            href = offer.get('url') or ''
            parsed = urlparse(href)
            match = re.search(r'/id-(\d+)', parsed.path)
            if not match or parsed.netloc != urlparse(SITE['chaves'][0]).netloc or not parsed.path.startswith('/imovel/'):
                continue
            code = match.group(1)
            details = offer.get('itemOffered') or {}
            location = details.get('address') or {}
            neighborhood = location.get('addressLocality')
            if 'santos' not in norm(location.get('addressRegion')) or norm(neighborhood) not in B:
                continue
            price = offer.get('price')
            if number(price) is None or number(price) <= 0 or number(price) > 530000:
                continue
            card = cards.get(code)
            floor_text = str((details.get('floorSize') or {}).get('unitText') or '')
            area_match = re.fullmatch(r'\s*([\d.,]+)\s*m²\s*', floor_text, re.I)
            area = number(area_match.group(1)) if area_match else None
            rooms = number(details.get('numberOfBedrooms'))
            spots = condo = None
            street = location.get('streetAddress')
            if card:
                for node in card.select('p[aria-label]'):
                    label = node.get('aria-label', '')
                    normalized = norm(label)
                    if 'area util' in normalized:
                        area = number(label)
                    elif re.match(r'^\d+\s+quarto', normalized):
                        rooms = number(label)
                    elif re.match(r'^\d+\s+vaga', normalized):
                        spots = number(label)
                condo_node = card.find(attrs={'aria-label': re.compile('^Condom', re.I)})
                condo = number(condo_node.get_text(' ', strip=True)) if condo_node else None
                street_node = card.find('p', class_=re.compile('addressStreet'))
                street = street_node.get_text(' ', strip=True) if street_node else None
            result[code] = {'codigo': code, 'tipo': 'Apartamento', 'cidade': 'Santos',
                            'bairro': neighborhood, 'valor': price,
                            'areaprincipal': area, 'numeroquartos': rooms, 'numerovagas': spots,
                            'valorcondominio': condo, 'titulo': offer.get('name', ''),
                            'endereco': street, 'url': href}
        log.info('chaves: página %d/%d lida; %d candidatos acumulados', page, total_pages, len(result))
        page += 1
        time.sleep(0.3)
    return result


def matches_chaves(item):
    price = number(item.get('valor'))
    neighborhood = norm(item.get('bairro'))
    area = number(item.get('areaprincipal'))
    rooms = number(item.get('numeroquartos'))
    condo = number(item.get('valorcondominio'))
    if (neighborhood not in B or price is None or price <= 0 or price > 530000
            or (area is not None and area < 70) or (rooms is not None and rooms != 2)
            or (condo is not None and condo > 1100)):
        return False, ''
    url = item.get('url', '')
    if not url.startswith(SITE['chaves'][0] + 'imovel/'):
        raise ValueError('Link do Chaves na Mão inválido')
    response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=35)
    if response.status_code in (404, 410):
        return False, url
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    heading = soup.find('h1')
    area_node = soup.select_one('p[aria-label="area-util"]')
    rooms_node = soup.select_one('p[aria-label="Quartos"]')
    spots_node = soup.select_one('p[aria-label="Garagens"]')
    if heading is None:
        raise ValueError('Ficha do Chaves na Mão não reconhecida')
    main = heading.find_parent('div')
    description = norm(main.get_text(' ', strip=True) if main else heading.get_text(' ', strip=True))
    feature_parts = []
    for label in soup.find_all(string=re.compile(r'^Área (?:privativa|comum)$', re.I)):
        group = label.find_parent('span')
        if group:
            feature_parts.append(norm(group.get_text(' ', strip=True)))
    features = ' '.join(feature_parts)
    code = re.escape(str(item['codigo']))
    data = next_data(soup)
    prices_match = re.search(r'"url":"[^"]*id-' + code + r'/?",\s*"prices":(\{[^{}]+\})', data)
    if not prices_match:
        raise ValueError('Preços da ficha do Chaves não encontrados')
    prices = json.loads(prices_match.group(1))
    price = number(prices.get('rawPrice'))
    condo = number(prices.get('condominiumFee'))
    area = number(area_node.get_text(' ', strip=True)) if area_node else None
    rooms = number(rooms_node.get_text(' ', strip=True)) if rooms_node else None
    spots = number(spots_node.get_text(' ', strip=True)) if spots_node else None
    collective = bool(re.search(r'\bvaga\s+coletiva\b', description))
    if (price is None or price <= 0 or price > 530000
            or (condo is not None and (condo < 0 or condo > 1100)) or area is None or area < 70 or rooms != 2
            or ((spots is None or spots < 1) and not collective)
            or re.search(r'\bterreo\b|\bgarden\b|\bquintal\b', description + ' ' + features)):
        return False, url
    item.update({'valor': prices.get('main') or price, 'valorcondominio': prices.get('condominiumFee'),
                 'areaprincipal': area, 'numeroquartos': int(rooms),
                 'numerovagas': int(spots) if spots and spots >= 1 else '1 coletiva',
                 'tipovagas': 'coletiva' if collective else ''})
    if price <= 426000 and (condo is None or condo <= 800):
        return True, url
    elevator = bool(re.search(r'\belevador(?:es)?\b', description + ' ' + features)) and not bool(
        re.search(r'\bsem\s+elevador\b', description))
    address_node = soup.select_one('h2.column')
    street = norm(address_node.get_text(' ', strip=True) if address_node else item.get('endereco'))
    avenue = (not street or 'aproximada' in street or 'indisponivel' in street
              or bool(re.match(r'^(avenida|av)\b', street)))
    return neighborhood in A and price <= 530000 and elevator and not avenue, url


def fetch_proprietario():
    neighborhoods = {'aparecida': 'aparecida', 'boqueirao': 'boqueirao', 'embare': 'embare',
                     'gonzaga': 'gonzaga', 'pompeia': 'pompeia', 'campo grande': 'campo-grande',
                     'marape': 'marape', 'jose menino': 'jose-menino'}
    result = {}
    base = SITE['proprietario'][0]
    for neighborhood, slug in neighborhoods.items():
        url = base + 'venda/apartamento/sp/santos/' + slug + '/direto-com-proprietario'
        visited = set()
        while url:
            if url in visited or len(visited) >= 100 or urlparse(url).netloc != urlparse(base).netloc:
                raise RuntimeError('Paginação inválida no Proprietário Direto')
            visited.add(url)
            response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=40)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            container = soup.select_one('.pd-search-cards')
            if container is None:
                raise RuntimeError('Lista de imóveis do Proprietário Direto não encontrada')
            cards = {}
            for link in container.select('a[href*="/comprar-apartamento-"]'):
                card = link.find_parent('div', class_=re.compile(r'^style_card-property--(?:row|grid)__'))
                href = urljoin(base, link.get('href', ''))
                code = re.search(r'/(\d+)/?$', urlparse(href).path)
                if not card or not code or urlparse(href).netloc != urlparse(base).netloc:
                    continue
                cards[code.group(1)] = (card, href)
            if container.select('a[href*="/comprar-apartamento-"]') and not cards:
                raise RuntimeError('Cartões do Proprietário Direto não reconhecidos')
            for code, (card, href) in cards.items():
                text = card.get_text(' ', strip=True)
                clean = norm(text)
                address_node = card.find('div', class_=re.compile(r'^style_card-property__addr__'))
                address = address_node.get_text(' ', strip=True) if address_node else ''
                price = re.search(r'\bvenda\s*R\$\s*([\d.,]+)', text, re.I)
                area = re.search(r'([\d.,]+)\s*m²', text, re.I)
                rooms = re.search(r'\b(\d+)\s+dormitorio', clean)
                spots = re.search(r'\b(\d+)\s+vaga', clean)
                result[code] = {
                    'codigo': code, 'tipo': 'Apartamento', 'cidade': 'Santos',
                    'bairro': neighborhood, 'valor': price.group(1) if price else None,
                    'areaprincipal': area.group(1) if area else None,
                    'numeroquartos': rooms.group(1) if rooms else None,
                    'numerovagas': spots.group(1) if spots else None,
                    'tipovagas': 'coletiva' if 'vaga coletiva' in clean else '',
                    'titulo': text, 'endereco': address, 'url': href,
                }
            next_link = soup.select_one('a[rel="next"][href]')
            url = urljoin(base, next_link['href']) if next_link else None
    return result


def matches_proprietario(item):
    price = number(item.get('valor'))
    area = number(item.get('areaprincipal'))
    rooms = number(item.get('numeroquartos'))
    neighborhood = norm(item.get('bairro'))
    if price is None or price <= 0 or price > 530000 or area is None or area < 70 or rooms != 2:
        return False, ''
    url = item.get('url', '')
    if not url.startswith(SITE['proprietario'][0] + 'comprar-apartamento-'):
        raise ValueError('Link do Proprietário Direto inválido')
    response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    root = soup.select_one('.pd-property-show-root')
    if root is None:
        raise ValueError('Ficha do Proprietário Direto não reconhecida')
    content = root.get_text(' ', strip=True)
    normalized = norm(content + ' ' + str(item.get('titulo', '')))
    condo = None
    for row in root.select('.pd-cost-row'):
        row_text = row.get_text(' ', strip=True)
        if norm(row_text).startswith('condominio'):
            match = re.search(r'R\$\s*([\d.,]+)', row_text)
            if match:
                raw = match.group(1)
                # O site apresenta milhares com vírgula: R$ 1,100.
                condo = float(raw.replace(',', '')) if re.fullmatch(r'\d{1,3}(?:,\d{3})+', raw) else number(raw)
            break
    spots = number(item.get('numerovagas'))
    collective = bool(re.search(r'\bvaga\s+coletiva\b', normalized))
    if ((condo is not None and (condo < 0 or condo > 1100))
            or ((spots is None or spots < 1) and not collective)
            or re.search(r'\bterreo\b|\bgarden\b|\bquintal\b', normalized)):
        return False, url
    item['valorcondominio'] = 'Não informado' if condo is None else 'R$ ' + f'{condo:,.2f}'.replace(',', '_').replace('.', ',').replace('_', '.')
    if collective and (spots is None or spots < 1):
        item['numerovagas'] = '1 coletiva'
    if price <= 426000 and (condo is None or condo <= 800):
        return True, url
    elevator = bool(re.search(r'\belevador(?:es)?\b', normalized)) and not bool(
        re.search(r'\bsem\s+elevador\b', normalized))
    street = norm(item.get('endereco'))
    known_street = bool(re.match(r'^(rua|avenida|av|alameda|travessa|praca|estrada|rodovia|largo)\b', street))
    avenue = not known_street or bool(re.match(r'^(avenida|av)\b', street))
    return neighborhood in A and price <= 530000 and elevator and not avenue, url


def detail(site, item):
    base = SITE[site][0]
    if site == 'roda':
        url = item.get('url')
    else:
        slug = item.get('url_amigavel') if site == 'rhema' else item.get('titulo')
        url = base + 'imovel/' + str(slug).strip('/') + '/' + str(item['codigo']) if slug else None
    if not url or not url.startswith(base):
        raise ValueError('Link do anúncio ausente ou inválido')
    response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=30)
    response.raise_for_status()
    if site == 'rhema':
        soup = BeautifulSoup(response.text, 'html.parser')
        scope = soup.select_one('.container-esquerda')
        description = scope.select_one('p.descricao') if scope else None
        if not description:
            raise ValueError('Descrição da Rhema não encontrada')
        active_features = [node.get_text(' ', strip=True)
                           for node in scope.select('li.caracteristicas-extras')
                           if 'extras-none' not in (node.get('class') or [])]
        heading = scope.find('h1')
        return url, norm(' '.join([heading.get_text(' ', strip=True) if heading else '',
                                   description.get_text(' ', strip=True), *active_features]))
    text = re.sub(r'<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>', ' ', response.text, flags=re.I | re.S)
    return url, norm(html.unescape(re.sub(r'<[^>]+>', ' ', text)))


def matches(site, item):
    if site == 'proprietario':
        return matches_proprietario(item)
    if site == 'chaves':
        return matches_chaves(item)
    neighborhood = norm(item.get('bairro'))
    if norm(item.get('cidade')) != 'santos' or neighborhood not in B:
        return False, ''
    kind = norm(item.get('tipo'))
    title = norm(item.get('titulo'))
    if 'apartamento' not in kind or 'garden' in kind or 'terreo' in kind:
        return False, ''
    price, condo = number(item.get('valor')), number(item.get('valorcondominio'))
    area, rooms = number(item.get('areaprincipal')), number(item.get('numeroquartos'))
    spots = number(item.get('numerovagas'))
    collective = 'coletiv' in norm(item.get('tipovagas'))
    if (price is None or price <= 0 or price > 530000 or (condo is not None and condo < 0)
            or area is None or area < 70 or rooms != 2
            or ((spots is None or spots < 1) and not collective)):
        return False, ''
    if condo is not None and condo > 1100:
        return False, ''
    # Consulta a ficha para verificar descrições e manter link válido.
    url, description = detail(site, item)
    combined = ' '.join([title, kind, norm(item.get('descricao')), description])
    floor = number(item.get('numeroandar'))
    if (floor == 0 or re.search(r'\bterreo\b|\bgarden\b|\bquintal\b', combined)
            or norm(item.get('quintal')) in {'1', 'true', 'sim'}):
        return False, url
    if price <= 426000 and (condo is None or condo <= 800):
        return True, url
    elevator = number(item.get('numeroelevador'))
    has_elevator = (elevator is not None and elevator > 0) or bool(
        re.search(r'\b(?:com|possui|tem) elevador\b|\belevador social\b', combined))
    if site == 'rhema' and re.search(r'\belevador(?:es)?\b', description):
        has_elevator = True
    if re.search(r'\bsem elevador\b', combined):
        has_elevator = False
    street = norm(item.get('endereco'))
    known_street = bool(re.match(r'^(rua|avenida|av|alameda|travessa|praca|estrada|rodovia|largo)\b', street))
    avenue = bool(item.get('_address_unverified')) or not known_street or bool(re.match(r'^(avenida|av)\b', street))
    return (neighborhood in A and price <= 530000 and (condo is None or condo <= 1100)
            and has_elevator and not avenue), url


def load_state():
    if STATE.exists():
        with STATE.open(encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(state):
    temp = STATE.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False)
    os.replace(temp, STATE)


def notify(site, item, url):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    chat = os.environ['TELEGRAM_CHAT_ID']
    message = (f"Novo apartamento - {site.title()}\n"
               f"{item.get('bairro')} - Santos\n"
               f"Preço: {item.get('valor')} | Condomínio: {item.get('valorcondominio') if item.get('valorcondominio') is not None else 'Não informado'}\n"
               f"Área: {item.get('areaprincipal')} m² | Quartos: {item.get('numeroquartos')}\n"
               f"Vagas: {item.get('numerovagas')} {item.get('tipovagas') or ''}\n{url}")
    response = SESSION.post('https://api.telegram.org/bot' + token + '/sendMessage',
                            data={'chat_id': chat, 'text': message}, timeout=20)
    if not response.ok or not response.json().get('ok'):
        raise RuntimeError('Telegram não confirmou o envio')


def notify_health(site, recovered=False):
    names = {'rhema': 'Rhema', 'multiverso': 'Multiverso', 'roda': 'Roda',
             'proprietario': 'Proprietário Direto', 'chaves': 'Chaves na Mão'}
    name = names.get(site, site)
    if recovered:
        message = f'✅ Monitor {name}: a busca voltou a funcionar.'
    else:
        message = (f'⚠️ Monitor {name}: a busca falhou em três verificações consecutivas. '
                   'Pode ser mudança ou indisponibilidade do site; é preciso verificar.')
    try:
        response = SESSION.post('https://api.telegram.org/bot' + os.environ['TELEGRAM_BOT_TOKEN'] + '/sendMessage',
                                data={'chat_id': os.environ['TELEGRAM_CHAT_ID'], 'text': message}, timeout=20)
        return bool(response.ok and response.json().get('ok'))
    except (requests.RequestException, ValueError, KeyError):
        log.error('%s: não foi possível enviar o aviso de funcionamento ao Telegram', site)
        return False


def check(site, state):
    items = fetch(site)
    record = state.setdefault(site, {'initialized': False, 'seen': []})
    if os.environ.get('MONITOR_REBASE') == '1':
        record['initialized'] = False
        if site == 'chaves':
            record['rejected'] = {}
            record['baseline_pending'] = []
    seen = set(record['seen'])
    eligible = []
    baseline = not record['initialized']
    pending = set(record.get('baseline_pending', [])) if site == 'chaves' else set()
    rejected = record.setdefault('rejected', {}) if site == 'chaves' else {}
    newly_rejected = {}
    checked = 0
    for code, item in items.items():
        if code in seen:
            continue
        signature = f"{item.get('valor')}|{norm(item.get('bairro'))}"
        cached = rejected.get(code, {})
        if (site == 'chaves' and cached.get('signature') == signature
                and time.time() - cached.get('checked_at', 0) < 86400):
            continue
        try:
            ok, url = matches(site, item)
            checked += 1
            if site == 'chaves' and checked % 25 == 0:
                log.info('chaves: %d candidatos avaliados', checked)
            if ok:
                eligible.append((code, item, url))
            elif site == 'chaves':
                pending.discard(code)
                newly_rejected[code] = {'signature': signature, 'checked_at': time.time()}
        except (requests.RequestException, ValueError) as exc:
            log.warning('%s: falha ao validar ficha %s (%s)', site, code, type(exc).__name__)
            if site == 'chaves' and (baseline or code in pending):
                pending.add(code)
                continue
            if not record['initialized']:
                raise RuntimeError('Linha de base incompleta') from exc
    for code, item, url in eligible:
        if record['initialized'] and code not in pending:
            notify(site, item, url)
        seen.add(code)
        pending.discard(code)
        record['seen'] = sorted(seen)
        save_state(state)
    record['initialized'] = True
    record['seen'] = sorted(seen)
    if site == 'chaves':
        rejected.update(newly_rejected)
        record['baseline_pending'] = sorted(pending)
    save_state(state)
    log.info('%s: busca concluída; %d anúncios, %d elegíveis novos; notificações %s',
             site, len(items), len(eligible), 'desativadas na linha de base' if baseline else 'ativas')
    if pending:
        log.warning('%s: %d fichas anteriores aguardam validação silenciosa', site, len(pending))


def main():
    if not os.environ.get('TELEGRAM_BOT_TOKEN') or not os.environ.get('TELEGRAM_CHAT_ID'):
        raise SystemExit('Credenciais Telegram ausentes')
    state = load_state()
    selected = os.environ.get('MONITOR_SITE')
    if selected and selected not in SITE:
        raise SystemExit('Site desconhecido')
    selected_many = os.environ.get('MONITOR_SITES')
    sites = [selected] if selected else (selected_many.split(',') if selected_many else list(SITE))
    if any(site not in SITE for site in sites):
        raise SystemExit('Lista de sites desconhecida')
    failures = {site: 0 for site in sites}
    warned = set()
    while True:
        failed = False
        for site in sites:
            try:
                check(site, state)
                failures[site] = 0
                if site in warned and notify_health(site, recovered=True):
                    warned.remove(site)
            except Exception as exc:
                failed = True
                failures[site] += 1
                log.error('%s: ciclo não concluído (%s)', site, type(exc).__name__)
                if (os.environ.get('MONITOR_ONCE') != '1' and failures[site] >= 3
                        and site not in warned and notify_health(site)):
                    warned.add(site)
        if os.environ.get('MONITOR_ONCE') == '1':
            if failed:
                raise SystemExit(1)
            return
        time.sleep(15 * 60)


if __name__ == '__main__':
    main()
