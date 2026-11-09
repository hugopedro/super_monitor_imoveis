#!/usr/bin/env python3
"""Monitora as buscas públicas de Rhema e Multiverso, com base inicial silenciosa."""
import html
import base64
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
    'chave_santos': ('https://www.chavesantosimoveis.com.br/', 'assets/js/objImovel.js', 'retornar-imoveis-disponiveis'),
    'maneco': ('https://www.manecoimoveis.com.br/', 'assets/js/objImovel.js', 'retornar-imoveis-disponiveis'),
    'torres_prime': ('https://www.torresprime.com.br/', '', ''),
    'myx': ('https://www.myximoveis.com.br/', '', ''),
    'raiz': ('https://www.raizimobiliariasantos.com.br/', '', ''),
    'mape': ('https://www.mapenegocios.com.br/', '', ''),
    'listagem': ('https://www.listagemimobiliaria.com.br/', '', ''),
    'expoente': ('https://www.expoenteimobiliaria.com.br/', '', ''),
    'pousada': ('https://imobiliariapousada.com.br/', '', ''),
    'rochedo': ('https://rochedoadmdebens.com.br/', '', ''),
    'lopes_conceito': ('https://www.lopesconceito.com.br/', '', ''),
    'prime_trade': ('https://www.primetradeimoveis.com.br/', '', ''),
    'balduino': ('https://balduinocorretordeimoveis.com.br/', '', ''),
    'cerejo': ('https://cerejoimoveis.com.br/', '', ''),
    'casabella': ('https://imobiliaria.imoveiscasabella.com.br/', '', ''),
    'familia': ('https://familiaimoveis.com.br/', '', ''),
    'viver_em_santos': ('https://www.viveremsantosimoveis.com.br/', '', ''),
    'gavea': ('https://www.gaveaimobi.com.br/', '', ''),
    'fabricio': ('https://www.fabricioimoveiseseguros.com.br/', '', ''),
    'bw': ('https://www.zapimoveis.com.br/', '', ''),
    'remax_evoke_iv': ('https://www.remax.com.br/', '', ''),
    'rhema': ('https://www.rhemaimoveis.com.br/', 'assets/js/objImovel.js', 'retornar-imoveis-disponiveis'),
    'multiverso': ('https://www.multiversoimob.com.br/', 'assets/js/busca/busca.js', 'imoveis/ajax/'),
    'roda': ('https://rodaimoveis.com.br/', '', ''),
    'proprietario': ('https://www.proprietariodireto.com.br/', '', ''),
    'chaves': ('https://www.chavesnamao.com.br/', '', ''),
}
KENLO = {'torres_prime', 'myx', 'raiz', 'mape', 'listagem', 'expoente', 'casabella'}
UNSOFT = {'rhema', 'chave_santos', 'maneco'}
DIRECT_DETAIL_SITES = {'pousada', 'rochedo', 'lopes_conceito', 'prime_trade', 'balduino', 'cerejo', 'familia', 'viver_em_santos', 'gavea', 'fabricio'}
B_ONLY_SITES = {'pousada', 'rochedo', 'lopes_conceito', 'prime_trade', 'balduino', 'cerejo', 'casabella', 'familia', 'viver_em_santos', 'gavea', 'fabricio', 'bw', 'remax_evoke_iv'}
SITE_LABEL = {
    'chave_santos': 'Chave Santos Imóveis', 'torres_prime': 'Torres Prime',
    'myx': 'Myx Imóveis', 'raiz': 'Raiz Imobiliária', 'mape': 'Mapê Imóveis',
    'listagem': 'Listagem Imobiliária', 'expoente': 'Expoente Imobiliária',
    'maneco': 'Maneco Imóveis', 'pousada': 'Imobiliária Pousada',
    'rochedo': 'Rochedo Imóveis', 'lopes_conceito': 'Lopes Conceito',
    'prime_trade': 'Prime Trade Imóveis', 'balduino': 'Balduino Imóveis',
    'cerejo': 'Cerejo Imóveis', 'casabella': 'Casabella Imóveis',
    'familia': 'Família Imóveis', 'viver_em_santos': 'Viver em Santos Imóveis',
    'gavea': 'Gávea Imobiliária', 'fabricio': 'Fabrício Corretor de Imóveis',
    'bw': 'BW Imóveis', 'remax_evoke_iv': 'RE/MAX Evoke IV',
}
BW_ADVERTISER_ID = '9a9d0a8e-9dc0-41fc-08b3-66017eb1d79e'
REMAX_EVOKE_IV_OFFICE_ID = 69120
A = {'aparecida', 'boqueirao', 'embare', 'gonzaga', 'pompeia'}
B = A | {'campo grande', 'marape', 'jose menino'}
STATE = Path('state.json')
REPORT_PRIMARY_ONLY = False
SESSION = requests.Session()
SESSION.headers.update({'User-Agent': 'Mozilla/5.0', 'X-Requested-With': 'XMLHttpRequest'})
BW_SESSION = None


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
    if site in KENLO:
        return fetch_kenlo(site)
    if site == 'pousada':
        return fetch_pousada()
    if site == 'rochedo':
        return fetch_rochedo()
    if site == 'lopes_conceito':
        return fetch_lopes_conceito()
    if site == 'prime_trade':
        return fetch_prime_trade()
    if site == 'balduino':
        return fetch_balduino()
    if site == 'cerejo':
        return fetch_cerejo()
    if site == 'familia':
        return fetch_familia()
    if site == 'viver_em_santos':
        return fetch_viver_em_santos()
    if site == 'gavea':
        return fetch_gavea()
    if site == 'fabricio':
        return fetch_fabricio()
    if site == 'bw':
        return fetch_bw()
    if site == 'remax_evoke_iv':
        return fetch_remax_evoke_iv()
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
        if site in UNSOFT:
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


def parse_card_item(code, url, text, neighborhood, tipo='Apartamento'):
    """Normaliza os campos comuns que aparecem nas listas públicas."""
    normalized = norm(text)
    prices = re.findall(r'R\$\s*([\d.,]+)', text, re.I)
    price = prices[-1] if re.search(r'\bpor\s+R\$', text, re.I) and prices else (prices[0] if prices else None)
    area_match = re.search(r'([\d.,]+)\s*m\s*(?:²|2)\b', normalized)
    if not area_match:
        area_match = re.search(r'([\d.,]+)\s*m\s*(?:²|2)\b', text, re.I)
    room_match = re.search(r'\b(\d+)\s*(?:quartos?|dormit[oó]rios?)\b', normalized)
    if not room_match:
        room_match = re.search(r'\b(?:quartos?|dormit[oó]rios?)\s*[:\-]?\s*(\d+)\b', normalized)
    spot_match = re.search(r'\b(\d+)\s*vagas?\b', normalized)
    if not spot_match:
        spot_match = re.search(r'\bvagas?\s*[:\-]?\s*(\d+)\b', normalized)
    address_match = re.search(
        r'\b(?:rua|avenida|av\.?|alameda|travessa|pra[cç]a)\s+[^,|\n]{2,90}', text, re.I)
    normalized_type = norm(tipo)
    if normalized_type == 'apartamento':
        for candidate in ('apartamento', 'casa', 'sobrado', 'sala', 'kitnet', 'cobertura', 'studio', 'terreno'):
            if re.search(r'\b' + candidate + r'\b', normalized):
                tipo = 'Apartamento' if candidate == 'cobertura' else candidate.title()
                break
    item = {
        'codigo': str(code), 'url': url, 'cidade': 'Santos', 'tipo': tipo,
        'bairro': neighborhood, 'valor': price,
        'areaprincipal': area_match.group(1) if area_match else None,
        'numeroquartos': room_match.group(1) if room_match else None,
        'numerovagas': spot_match.group(1) if spot_match else None,
        'tipovagas': 'coletiva' if 'vaga coletiva' in normalized or 'garagem coletiva' in normalized else '',
        'endereco': address_match.group(0).strip() if address_match else '',
        'titulo': ' '.join(text.split())[:300],
    }
    return item


def fetch_pousada():
    """Busca apartamentos até R$ 426 mil e confirma a paginação do Praedium."""
    base = SITE['pousada'][0]
    result, expected = {}, None
    for page in range(1, 101):
        response = SESSION.get(base + 'apartamento/a-venda/santos-sp',
                               params={'preco-maximo': '530000' if REPORT_PRIMARY_ONLY else '426000',
                                       'pagina': page}, timeout=40)
        response.raise_for_status()
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, 'html.parser')
        title = soup.title.get_text(' ', strip=True) if soup.title else ''
        count_match = re.match(r'\s*(\d+)\s+', title)
        if not count_match:
            raise RuntimeError('Pousada: total de resultados não reconhecido')
        count = int(count_match.group(1))
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError('Pousada: total mudou durante a paginação')
        links = soup.select('a.property-card-link.d-block:not(.image_area)')
        before = len(result)
        for link in links:
            href = urljoin(base, link.get('href', ''))
            match = re.search(r'id-(\d+)', href)
            if not match or urlparse(href).netloc != urlparse(base).netloc:
                continue
            text = link.get_text(' ', strip=True)
            card = link.find_parent('div', class_='thumbnail_one')
            card_text = card.get_text(' ', strip=True) if card else text
            place = re.search(r'\s-\s*([^,]+),\s*Santos(?:-SP|,|\s)', text, re.I)
            neighborhood = place.group(1).strip() if place else ''
            result[match.group(1)] = parse_card_item(match.group(1), href, card_text, neighborhood)
        if len(result) >= expected:
            return result
        if not links or len(result) == before:
            raise RuntimeError('Pousada: paginação incompleta ou repetida')
        time.sleep(0.2)
    raise RuntimeError('Pousada: limite de páginas excedido')


def fetch_rochedo():
    """Lê todas as páginas da busca de apartamentos à venda da Rochedo."""
    base = SITE['rochedo'][0]
    filters = json.dumps({'city': '9636', 'tour_360_url': None,
                          'max_price': 530000 if REPORT_PRIMARY_ONLY else 426000, 'order': 3},
                         separators=(',', ':'))
    encoded = base64.b64encode(filters.encode()).decode()
    result, expected = {}, None
    for page in range(1, 101):
        response = SESSION.get(base + 'busca/comprar/santos-sp/apartamento',
                               params={'filters': encoded, 'page': page}, timeout=40)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        text_page = soup.get_text(' ', strip=True)
        count_match = re.search(r'(\d+)\s+Apartamentos?\s+para\s+Comprar\s+em\s+Santos', text_page, re.I)
        if not count_match:
            count_match = re.search(r'(\d+)\s+Apartamento\s+para\s+Comprar\s+em\s+Santos', text_page, re.I)
        if not count_match:
            raise RuntimeError('Rochedo: total de resultados não reconhecido')
        count = int(count_match.group(1))
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError('Rochedo: total mudou durante a paginação')
        cards = soup.select('article.box-construction-8')
        before = len(result)
        for card in cards:
            card_text = card.get_text(' ', strip=True)
            code = re.search(r'\bCod\s*:\s*(\d+)', card_text, re.I)
            link = card.select_one('a[href*="/detalhes/imovel/"]')
            if not code or not link:
                continue
            href = urljoin(base, link.get('href', ''))
            if urlparse(href).netloc != urlparse(base).netloc:
                raise RuntimeError('Rochedo: domínio de anúncio inesperado')
            place = re.search(r'Santos\s*-\s*([^,]+)\s+Apartamento', card_text, re.I)
            neighborhood = place.group(1).strip() if place else ''
            item = parse_card_item(code.group(1), href, card_text, neighborhood)
            area_match = re.search(r'\bárea\s+m\s*2\s*([\d.,]+)', card_text, re.I)
            if area_match:
                item['areaprincipal'] = area_match.group(1)
            result[code.group(1)] = item
        if len(result) >= expected:
            return result
        if not cards or len(result) == before:
            raise RuntimeError('Rochedo: paginação incompleta ou repetida')
        time.sleep(0.2)
    raise RuntimeError('Rochedo: limite de páginas excedido')


def fetch_lopes_conceito():
    """Busca o catálogo filtrado da Lopes Conceito, paginação por id REO."""
    base = SITE['lopes_conceito'][0]
    result, expected = {}, None
    for page in range(1, 101):
        response = SESSION.get(base + 'imoveis/comprar/br/sp/santos', params={
            'price_max': '530000' if REPORT_PRIMARY_ONLY else '426000',
            'bedrooms_min': '2', 'bedrooms_max': '2',
            'area_min': '70', 'page': page,
        }, timeout=40)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        title = soup.title.get_text(' ', strip=True) if soup.title else ''
        count_match = re.match(r'\s*(\d+)\s+', title)
        if not count_match:
            raise RuntimeError('Lopes Conceito: total de resultados não reconhecido')
        count = int(count_match.group(1))
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError('Lopes Conceito: total mudou durante a paginação')
        cards = soup.select('article.vp-property-card')
        before = len(result)
        for card in cards:
            link = card.select_one('a[href*="/imovel/"]')
            if not link:
                continue
            href = urljoin(base, link.get('href', ''))
            match = re.search(r'/imovel/((?:REO|REM)\d+)', href)
            if not match:
                continue
            code = match.group(1)
            card_text = card.get_text(' ', strip=True)
            district = re.search(r'\b(?:REO|REM)\d+\s+([^,]+),\s*Santos\s*-\s*SP\b', card_text, re.I)
            neighborhood = district.group(1).strip() if district else ''
            result[code] = parse_card_item(code, href, card_text, neighborhood)
        if len(result) >= expected:
            return result
        if not cards or len(result) == before:
            raise RuntimeError('Lopes Conceito: paginação incompleta ou repetida')
        time.sleep(0.2)
    raise RuntimeError('Lopes Conceito: limite de páginas excedido')


def fetch_prime_trade():
    """Busca e pagina as ofertas publicadas no portal oficial Prime Trade."""
    base = SITE['prime_trade'][0]
    result, expected, observed = {}, None, 0
    neighborhood_names = sorted(B, key=len, reverse=True)
    for page in range(1, 101):
        response = SESSION.get(base + 'imoveis/venda', params={'ordem': 'neighborhood', 'page': page}, timeout=40)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        title = soup.title.get_text(' ', strip=True) if soup.title else ''
        count_match = re.match(r'\s*(\d+)\s+', title)
        if not count_match:
            raise RuntimeError('Prime Trade: total de resultados não reconhecido')
        count = int(count_match.group(1))
        if expected is None:
            expected = count
        elif count != expected:
            raise RuntimeError('Prime Trade: total mudou durante a paginação')
        cards = soup.select('mat-card')
        observed += len(cards)
        before = len(result)
        for card in cards:
            link = card.select_one('a[href*="/imovel/"]')
            if not link:
                raise RuntimeError('Prime Trade: cartão sem link de imóvel')
            href = urljoin(base, link.get('href', ''))
            match = re.search(r'-code-([\w]+)', href)
            if not match or urlparse(href).netloc != urlparse(base).netloc:
                raise RuntimeError('Prime Trade: link ou código de imóvel inválido')
            code = match.group(1)
            card_text = card.get_text(' ', strip=True)
            slug = norm(urlparse(href).path)
            neighborhood = next((n for n in neighborhood_names if n in slug), '')
            item = parse_card_item(code, href, card_text, neighborhood)
            if not item['numeroquartos']:
                m = re.search(r'\bbed\s*(\d+)\b', norm(card_text))
                item['numeroquartos'] = m.group(1) if m else None
            if not item['numerovagas']:
                m = re.search(r'directions car\s*(\d+)', norm(card_text))
                item['numerovagas'] = m.group(1) if m else None
            result[code] = item
        if observed >= expected:
            if observed != expected:
                raise RuntimeError('Prime Trade: número de cartões difere do total publicado')
            if len(result) != expected:
                log.warning('Prime Trade: %d cartões correspondem a %d códigos distintos; códigos repetidos ignorados',
                            observed, len(result))
            return result
        if not cards or len(result) == before:
            raise RuntimeError('Prime Trade: paginação incompleta ou repetida')
        time.sleep(0.2)
    raise RuntimeError('Prime Trade: limite de páginas excedido')


def fetch_balduino():
    """Busca a página pública de apartamentos à venda com dois dormitórios."""
    base = SITE['balduino'][0]
    response = SESSION.get(base + 'p-apartamento-venda-2_dormitorios.html', timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    cards = soup.select('article.box-result')
    if not cards:
        raise RuntimeError('Balduino: cartões de imóveis não encontrados')
    result = {}
    for card in cards:
        text = card.get_text(' ', strip=True)
        code = re.search(r'\bCod\.?\s*:\s*(\d+)', text, re.I)
        link = card.select_one('a.link[href]') or card.select_one('a[href*="apartamento-em-santos"]')
        if not code or not link:
            continue
        href = urljoin(base, link.get('href', ''))
        district = re.search(r'Apartamento\s+em\s+Santos,\s*([^\d]+?)\s+\d+\s+dorm', text, re.I)
        neighborhood = district.group(1).strip() if district else ''
        item = parse_card_item(code.group(1), href, text, neighborhood)
        structured_rooms = re.search(r'\b(\d+)\s+dorm', norm(text))
        if structured_rooms:
            item['numeroquartos'] = structured_rooms.group(1)
        area_match = re.search(r'([\d.,]+)\s*m²', text, re.I)
        if area_match:
            item['areaprincipal'] = area_match.group(1)
        if 'garagem coletiva' in norm(text):
            item['tipovagas'] = 'coletiva'
            item['numerovagas'] = item['numerovagas'] or '1'
        result[code.group(1)] = item
    return result


def fetch_cerejo():
    """Varre as páginas públicas de apartamentos à venda em Santos."""
    base = SITE['cerejo'][0]
    result, expected = {}, None
    for page in range(1, 101):
        response = SESSION.get(base + f'comprar/sp/santos/apartamento/pagina-{page}/', timeout=40)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        page_text = soup.get_text(' ', strip=True)
        count_match = re.search(r'(\d+)\s+Apartamentos?\s+à\s+venda\s+encontrados?', page_text, re.I)
        if not count_match:
            count_match = re.search(r'(\d+)\s+Apartamentos?\s+a\s+venda\s+encontrados?', page_text, re.I)
        count = int(count_match.group(1)) if count_match else None
        if expected is None and count is not None:
            expected = count
        elif count is not None and expected is not None and count != expected:
            raise RuntimeError('Cerejo: total mudou durante a paginação')
        links = soup.select('a.link_resultado[href]')
        before = len(result)
        for link in links:
            href = urljoin(base, link.get('href', ''))
            match = re.search(r'/(\d{6,})/?$', urlparse(href).path)
            if not match:
                continue
            code = match.group(1)
            text = link.get_text(' ', strip=True)
            parts = urlparse(href).path.strip('/').split('/')
            neighborhood = parts[-3].replace('-', ' ') if len(parts) >= 4 else ''
            if neighborhood == 'apartamento':
                neighborhood = ''
            item = parse_card_item(code, href, text, neighborhood)
            if item['valor'] is None:
                m = re.search(r'R\$\s*([\d.,]+)', text)
                item['valor'] = m.group(1) if m else None
            result[code] = item
        if expected is not None and len(result) >= expected:
            return result
        if not links or len(result) == before:
            if expected is None or len(result) >= expected:
                return result
            raise RuntimeError('Cerejo: paginação incompleta ou repetida')
        if expected is None and len(links) < 12:
            return result
        time.sleep(0.2)
    raise RuntimeError('Cerejo: limite de páginas excedido')


def fetch_fabricio():
    """Lê as ofertas públicas de venda da Fabrício Corretor de Imóveis."""
    base = SITE['fabricio'][0]
    response = SESSION.get(base + 'imoveis_listagem.php', params={'neg': 'venda'},
                           headers={'X-Requested-With': None}, timeout=40)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    cards = soup.select('li.li-imovel')
    if not cards:
        text = norm(soup.get_text(' ', strip=True))
        if any(phrase in text for phrase in ('nenhum imovel encontrado', 'nao encontramos imoveis')):
            return {}
        raise RuntimeError('Fabrício: cartões de imóveis não encontrados')
    result = {}
    for card in cards:
        link = card.select_one('a[href*="imoveis_detalhes.php"]')
        if link is None:
            raise RuntimeError('Fabrício: cartão sem link de ficha')
        url = urljoin(base, link.get('href', ''))
        if urlparse(url).netloc != urlparse(base).netloc:
            raise RuntimeError('Fabrício: domínio de anúncio inesperado')
        code_match = re.search(r'[?&]id=(\d+)', url)
        if not code_match:
            raise RuntimeError('Fabrício: anúncio sem código')
        code = code_match.group(1)
        category = card.select_one('.li-imovel__categoria')
        category_text = category.get_text(' ', strip=True) if category else ''
        category_norm = norm(category_text)
        if 'apartamento' in category_norm:
            tipo = 'Apartamento'
        elif 'casa' in category_norm or 'sobrado' in category_norm:
            tipo = 'Casa'
        else:
            tipo = category_text or 'Imóvel'
        neighborhood = card.select_one('.li-imovel__bairro')
        city = card.select_one('.li-imovel__cidade')
        title = card.select_one('.li-imovel__titulo')
        item = parse_card_item(code, url, card.get_text(' ', strip=True),
                               neighborhood.get_text(' ', strip=True) if neighborhood else '', tipo)
        item['cidade'] = city.get_text(' ', strip=True) if city else ''
        item['titulo'] = title.get_text(' ', strip=True) if title else item['titulo']
        result[code] = item
    return result


def fetch_bw():
    """Busca apenas os anúncios da conta BW Imóveis na API pública do ZAP."""
    global BW_SESSION
    if BW_SESSION is None:
        import cloudscraper
        BW_SESSION = cloudscraper.create_scraper(
            browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
        BW_SESSION.headers.update({
            'X-Domain': 'www.zapimoveis.com.br',
            'Referer': 'https://www.zapimoveis.com.br/',
            'Origin': 'https://www.zapimoveis.com.br',
            'Accept': 'application/json, text/plain, */*',
        })
    endpoint = 'https://glue-api.zapimoveis.com.br/v2/listings'
    result = {}
    offset = 0
    for _ in range(100):
        params = {
            'business': 'SALE', 'advertiserId': BW_ADVERTISER_ID,
            'size': '20', 'from': str(offset), 'images': 'webp',
            'includeFields': 'search(result(listings)),totalCount',
        }
        response = BW_SESSION.get(endpoint, params=params, timeout=40)
        response.raise_for_status()
        data = response.json()
        listings = data.get('search', {}).get('result', {}).get('listings')
        if not isinstance(listings, list):
            raise RuntimeError('BW/ZAP: resposta de anúncios não reconhecida')
        if not listings:
            return result
        page_codes = set()
        for entry in listings:
            raw = entry.get('listing') if isinstance(entry, dict) else None
            if not isinstance(raw, dict) or raw.get('advertiserId') != BW_ADVERTISER_ID:
                raise RuntimeError('BW/ZAP: filtro do anunciante não confirmado')
            code = str(raw.get('id') or '')
            if not code or code in page_codes or code in result:
                raise RuntimeError('BW/ZAP: código ausente ou paginação repetida')
            page_codes.add(code)
            address = raw.get('address') or {}
            pricing = (raw.get('pricingInfos') or [{}])[0]
            unit_types = raw.get('unitTypes') or []
            title = raw.get('title') or ''
            tipo = 'Apartamento' if 'APARTMENT' in unit_types else title
            areas = raw.get('usableAreas') or []
            bedrooms = raw.get('bedrooms') or []
            parking = raw.get('parkingSpaces') or []
            url = 'https://www.zapimoveis.com.br/imovel/' + code + '/'
            result[code] = {
                'codigo': code, 'url': url, 'cidade': address.get('city'),
                'bairro': address.get('neighborhood'), 'tipo': tipo,
                'titulo': title, 'valor': pricing.get('price'),
                'valorcondominio': pricing.get('monthlyCondoFee'),
                'areaprincipal': areas[0] if areas else None,
                'numeroquartos': bedrooms[0] if bedrooms else None,
                'numerovagas': parking[0] if parking else None,
                'tipovagas': 'coletiva' if re.search(r'\b(?:vaga|garagem)\s+coletiva\b', norm(raw.get('description'))) else '',
                'numeroandar': raw.get('unitFloor'),
                'descricao': BeautifulSoup(raw.get('description') or '', 'html.parser').get_text(' ', strip=True),
                '_bw_amenities': raw.get('amenities') or [],
            }
        offset += len(listings)
        if len(listings) < 20:
            return result
        time.sleep(0.2)
    raise RuntimeError('BW/ZAP: limite de páginas excedido')


def fetch_familia():
    """Busca as páginas de 2 dormitórios de cada bairro pelo endpoint de scroll."""
    base = SITE['familia'][0]
    neighborhoods = {
        'Aparecida': 'aparecida', 'Boqueirão': 'boqueirao', 'Embaré': 'embare',
        'Gonzaga': 'gonzaga', 'Pompéia': 'pompeia', 'Campo Grande': 'campo-grande',
        'Marapé': 'marape', 'José Menino': 'jose-menino',
    }
    sparams = base64.b64encode(
        json.dumps({'finalidade': 'venda', 'ordenar': 'relevancia'}, separators=(',', ':')).encode()
    ).decode()
    result = {}
    for neighborhood, slug in neighborhoods.items():
        route = base + f'venda/apartamento/santos/{slug}/2-dormitorios/'
        session = requests.Session()
        session.headers.update({'User-Agent': SESSION.headers['User-Agent']})
        response = session.get(route, timeout=40)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        phrase = soup.select_one('.result-totals-phrase')
        count_match = re.search(r'Encontramos\s+([\d.,]+)\s+im[oó]veis', phrase.get_text(' ', strip=True), re.I) if phrase else None
        if not count_match:
            raise RuntimeError(f'Família: total não reconhecido para {neighborhood}')
        expected = int(number(count_match.group(1)))
        if expected == 0:
            continue

        def collect_cards(card_soup):
            before = len(result)
            for card in card_soup.select('.imovel-box-single'):
                code = str(card.get('data-codigo') or '')
                link = card.select_one('a[href*="/imovel/"]')
                if not code or not link:
                    raise RuntimeError('Família: cartão sem código ou link')
                href = urljoin(base, link.get('href', ''))
                if urlparse(href).netloc != urlparse(base).netloc:
                    raise RuntimeError('Família: link de anúncio fora do domínio')
                text = card.get_text(' ', strip=True)
                item = parse_card_item(code, href, text, neighborhood)
                discounted = re.search(
                    r'\bvenda\s*:?\s*de\s*R\$\s*[\d.,]+\s+por\s*:?\s*R\$\s*([\d.,]+)', text, re.I)
                sale = re.search(r'\bvenda\s*:?\s*R\$\s*([\d.,]+)', text, re.I)
                if discounted or sale:
                    item['valor'] = (discounted or sale).group(1)
                fee = re.search(r'\bcondom[ií]nio\s*R\$\s*([\d.,]+)', text, re.I)
                if fee:
                    item['valorcondominio'] = fee.group(1)
                result[code] = item
            return len(result) - before

        collect_cards(soup)
        cursor = ''
        cursor_for = base + route.removeprefix(base)
        fetched = len([code for code, item in result.items() if norm(item.get('bairro')) == norm(neighborhood)])
        for page in range(2, 101):
            if fetched >= expected:
                break
            params = {'queryData': '', 'reload': '0', 'cursor': cursor, 'sParams': sparams}
            response = session.get(base + 'u-sr.php', params=params, headers={
                'X-Requested-With': 'XMLHttpRequest', 'Referer': cursor_for,
            }, timeout=45)
            response.raise_for_status()
            fragment = BeautifulSoup(response.text, 'html.parser')
            added = collect_cards(fragment)
            cursor_match = re.search(r"query-cursor'\)\.val\('([^']+)", response.text)
            cursor = cursor_match.group(1) if cursor_match else ''
            fetched = len([code for code, item in result.items() if norm(item.get('bairro')) == norm(neighborhood)])
            if not added or not cursor:
                if fetched < expected:
                    raise RuntimeError(f'Família: paginação incompleta para {neighborhood} ({fetched}/{expected})')
                break
            time.sleep(0.2)
        if fetched != expected:
            raise RuntimeError(f'Família: quantidade divergente para {neighborhood} ({fetched}/{expected})')
        time.sleep(0.2)
    return result


def fetch_viver_em_santos():
    """Usa a API pública Universal Software com venda, preço, área, quartos e bairros."""
    base = SITE['viver_em_santos'][0]
    session = requests.Session()
    session.headers.update({'User-Agent': SESSION.headers['User-Agent'],
                            'X-Requested-With': 'XMLHttpRequest'})
    neighborhoods = {'aparecida', 'boqueirao', 'campo grande', 'embare', 'gonzaga',
                     'marape', 'jose menino', 'pompeia'}
    response = session.post(base + 'bairroAjax', data={}, timeout=35)
    response.raise_for_status()
    try:
        available = response.json()
    except ValueError as exc:
        raise RuntimeError('Viver em Santos: lista de bairros inválida') from exc
    selected = {norm(item.get('nomeOriginal')): item for item in available
                if norm(item.get('nome_cidade')) == 'santos' and norm(item.get('nomeOriginal')) in neighborhoods}
    if set(selected) != neighborhoods:
        raise RuntimeError('Viver em Santos: lista de bairros incompleta')

    result = {}
    expected = None
    for page in range(1, 101):
        data = [
            ('imovel[finalidade]', 'venda'),
            ('imovel[codigoTipo][codigo][]', '2'),
            ('imovel[codigoTipo][tipo][]', 'apartamento'),
            ('imovel[codigocidade]', '2'),
            ('imovel[numeroquartos]', '2'),
            ('imovel[quartoqtdeexata]', 'true'),
            ('imovel[numerovagas]', '0'),
            ('imovel[valorde]', '0'),
            ('imovel[valorate]', '530000' if REPORT_PRIMARY_ONLY else '426000'),
            ('imovel[areade]', '70'),
            ('imovel[areaate]', '0'),
            ('imovel[numeropagina]', str(page)),
            ('imovel[numeroregistros]', '50'),
            ('imovel[ordenacao]', 'valordesc'),
            ('imovel[pagina]', str(page)),
            ('imovel[codigocondominio]', '0'),
        ]
        for item in selected.values():
            data.extend([('imovel[codigosbairros][codigo][]', str(item['codigo'])),
                         ('imovel[codigosbairros][nome][]', item['nome'])])
        response = session.post(base + 'imoveis/ajax/', data=data, timeout=45)
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError('Viver em Santos: JSON de imóveis inválido') from exc
        if not isinstance(payload, dict) or not isinstance(payload.get('lista'), list):
            raise RuntimeError('Viver em Santos: resposta incompleta')
        count = number(payload.get('quantidade'))
        if count is None:
            raise RuntimeError('Viver em Santos: total não informado')
        if expected is None:
            expected = int(count)
        elif expected != int(count):
            raise RuntimeError('Viver em Santos: total mudou durante a paginação')
        items = payload['lista']
        for raw in items:
            code = str(raw.get('codigo') or '')
            if not code:
                raise RuntimeError('Viver em Santos: imóvel sem código')
            slug = str(raw.get('titulo') or '').strip('/')
            url = raw.get('urlpublica') or (base + 'imovel/' + slug + '/' + code if slug else '')
            if not url or urlparse(url).netloc != urlparse(base).netloc:
                raise RuntimeError('Viver em Santos: link de imóvel inválido')
            result[code] = {
                'codigo': code, 'tipo': raw.get('tipo'), 'cidade': raw.get('cidade'),
                'bairro': raw.get('bairro'), 'titulo': raw.get('titulo'), 'url': url,
                'valor': raw.get('valor'), 'valorcondominio': raw.get('valorcondominio'),
                'areaprincipal': raw.get('areaprincipal'), 'numeroquartos': raw.get('numeroquartos'),
                'numerovagas': raw.get('numerovagas'), 'tipovagas': raw.get('tipovagas'),
                'endereco': raw.get('endereco'), 'numeroandar': raw.get('numeroandar'),
                'descricao': raw.get('descricao') or '',
            }
        if len(result) >= expected:
            return result
        if not items:
            raise RuntimeError('Viver em Santos: paginação incompleta')
        time.sleep(0.2)
    raise RuntimeError('Viver em Santos: limite de páginas excedido')


def decode_seroval(node):
    """Decodifica os tipos simples usados na resposta pública TanStack/Seroval da Gávea."""
    if not isinstance(node, dict):
        return node
    tag = node.get('t')
    if tag in (0, 1):
        return node.get('s')
    if tag == 2:
        return True if node.get('s') == 2 else False if node.get('s') == 3 else None
    if tag == 9:
        return [decode_seroval(value) for value in node.get('a', [])]
    if tag == 10:
        props = node.get('p') or {}
        return {key: decode_seroval(value) for key, value in zip(props.get('k', []), props.get('v', []))}
    return None


def fetch_gavea():
    """Lê o dataset público da Gávea e normaliza os imóveis de venda."""
    base = SITE['gavea'][0]
    response = SESSION.get(base + '_serverFn/bc79b56e4e7336e62bec8d0478a0ca50c836947ae1c91697bd517c7b2bda2c76',
                          headers={'Referer': base + 'site/imoveis?modo=venda',
                                   'x-tsr-serverFn': 'true',
                                   'Accept': 'application/x-tss-framed, application/x-ndjson, application/json'},
                          timeout=60)
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError('Gávea: resposta pública de imóveis inválida') from exc
    try:
        raw_items = decode_seroval(payload['p']['v'][0])
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError('Gávea: estrutura da busca mudou') from exc
    if not isinstance(raw_items, list):
        raise RuntimeError('Gávea: lista de anúncios ausente')
    result = {}
    for raw in raw_items:
        if not isinstance(raw, dict) or not raw.get('codigo'):
            raise RuntimeError('Gávea: anúncio sem código')
        code = str(raw['codigo'])
        result[code] = {
            'codigo': code, 'tipo': raw.get('tipo'), 'cidade': raw.get('cidade'),
            'bairro': raw.get('bairro'), 'titulo': raw.get('titulo'),
            'valor': raw.get('valor_venda'), 'valorcondominio': raw.get('condominio'),
            'areaprincipal': raw.get('area_util'), 'numeroquartos': raw.get('dormitorios'),
            'numerovagas': raw.get('vagas'), 'tipovagas': '',
            'endereco': raw.get('endereco') or '', 'url': base + 'site/imovel/' + code,
        }
    return result


def fetch_remax_evoke_iv():
    """Consulta o índice público da RE/MAX filtrado para a unidade IV de Santos."""
    base = SITE['remax_evoke_iv'][0]
    endpoint = base + 'search/listing-search/docs/search'
    headers = {
        'Content-Type': 'application/json', 'Referer': base + 'evokeiv',
        'Origin': base.rstrip('/'), 'User-Agent': 'Mozilla/5.0',
    }
    filter_text = (
        'content/OnHoldListing eq false and content/IsRegionalOffice eq false '
        'and content/IsViewable eq true and content/TenantId eq 6 '
        'and content/MacroRegionId eq 55 and content/OfficeId eq ' + str(REMAX_EVOKE_IV_OFFICE_ID)
    )
    expected, skip, result = None, 0, {}
    for _ in range(100):
        query = {
            'count': True, 'skip': skip, 'top': 100, 'filter': filter_text,
            'searchMode': 'all', 'queryType': 'full', 'search': '*',
        }
        response = SESSION.post(endpoint, headers=headers, json=query, timeout=45)
        response.raise_for_status()
        data = response.json()
        total, values = data.get('@odata.count'), data.get('value')
        if not isinstance(total, int) or not isinstance(values, list):
            raise RuntimeError('RE/MAX Evoke IV: resposta do índice não reconhecida')
        if expected is None:
            expected = total
        elif expected != total:
            raise RuntimeError('RE/MAX Evoke IV: total mudou durante a paginação')
        for entry in values:
            raw = entry.get('content') if isinstance(entry, dict) else None
            if (not isinstance(raw, dict) or raw.get('OfficeId') != REMAX_EVOKE_IV_OFFICE_ID
                    or raw.get('TenantId') != 6 or raw.get('MacroRegionId') != 55):
                raise RuntimeError('RE/MAX Evoke IV: filtro da filial não confirmado')
            code = str(raw.get('MLSID') or raw.get('ListingKey') or '')
            if not code or code in result:
                raise RuntimeError('RE/MAX Evoke IV: código ausente ou repetido')
            short_links = raw.get('ShortLinks') or []
            link = next((x.get('ShortLink') for x in short_links
                         if x.get('ISOLanguageCode') == 'pt' and x.get('ShortLink')), None)
            if not link:
                raise RuntimeError('RE/MAX Evoke IV: link público não encontrado')
            url = urljoin(base, link.lstrip('/'))
            meta = next((x.get('MetaTitle') for x in (raw.get('ListingMetaTags') or [])
                         if x.get('LanguageCode') == 'pt-BR' and x.get('MetaTitle')), '')
            descriptions = ' '.join(x.get('Description', '') for x in (raw.get('ListingDescriptions') or [])
                                    if isinstance(x, dict))
            description_text = BeautifulSoup(descriptions, 'html.parser').get_text(' ', strip=True)
            type_uid = raw.get('MacroPropertyTypeUID')
            is_apartment = type_uid == 2667 or 'apartamento' in norm(meta)
            result[code] = {
                'codigo': code, 'url': url, 'cidade': raw.get('City'),
                'bairro': raw.get('LocalZone'),
                'tipo': 'Apartamento' if is_apartment else (meta or 'Outro imóvel'),
                'titulo': meta or description_text[:250], 'valor': raw.get('ListingPrice'),
                'valorcondominio': raw.get('CondoFees'),
                'areaprincipal': raw.get('BuiltArea') or raw.get('LivingArea'),
                'numeroquartos': raw.get('NumberOfBedrooms'),
                'numerovagas': (raw.get('NumberOfGarages') if raw.get('NumberOfGarages') is not None
                                else raw.get('ParkingSpaces')),
                'numeroandar': (raw.get('FloorLevelNumber') if raw.get('FloorLevelNumber') is not None
                                else raw.get('FloorNumber')),
                'endereco': raw.get('StreetName') or '', 'descricao': description_text,
            }
        skip += len(values)
        if skip >= expected:
            return result
        if not values:
            raise RuntimeError('RE/MAX Evoke IV: paginação incompleta')
        time.sleep(0.2)
    raise RuntimeError('RE/MAX Evoke IV: limite de páginas excedido')


def fetch_kenlo(site):
    """Varre o resultado de venda em Santos e confere o total e paginação."""
    base = SITE[site][0]
    seen, result, expected = set(), {}, None
    for page in range(1, 101):
        max_price = 530000 if REPORT_PRIMARY_ONLY or site not in B_ONLY_SITES else 426000
        response = SESSION.get(base + 'imoveis/a-venda/apartamento/santos',
                               params={'preco-de-venda': f'~{max_price}', 'pagina': page},
                               headers={'X-Requested-With': None}, timeout=40)
        if site == 'casabella' and response.status_code == 404:
            empty = BeautifulSoup(response.content, 'html.parser')
            empty_text = norm(' '.join([
                empty.title.get_text(' ', strip=True) if empty.title else '',
                empty.get_text(' ', strip=True),
            ]))
            if 'nenhum imovel encontrado' in empty_text or 'nao encontramos imoveis para esta busca' in empty_text:
                return {}
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        title = soup.title.get_text(' ', strip=True) if soup.title else ''
        total_match = re.match(r'\s*(\d+)\s+', title)
        if not total_match:
            total_match = re.search(r'\bExibindo\s+(\d+)\s+Apartamentos?\b', soup.get_text(' ', strip=True), re.I)
        if not total_match:
            raise RuntimeError('Kenlo: total de resultados não reconhecido')
        count = int(total_match.group(1))
        if expected is None:
            expected = count
        elif expected != count:
            raise RuntimeError('Kenlo: total mudou durante a paginação')
        cards = soup.select('a.card-with-buttons[href*="/imovel/"]')
        previous = len(seen)
        for card in cards:
            url = urljoin(base, card.get('href', ''))
            if urlparse(url).netloc != urlparse(base).netloc:
                raise RuntimeError('Kenlo: domínio inesperado')
            code = urlparse(url).path.rstrip('/').split('/')[-1]
            if not code:
                raise RuntimeError('Kenlo: anúncio sem código')
            seen.add(code)
            text = card.get_text(' ', strip=True)
            district = re.search(r'\bApartamento\s+(.+?)\s+-\s+Santos\s+-\s+SP\b', text, re.I)
            if not district or norm(district.group(1)) not in B:
                continue
            price = re.search(r'\bVenda\s+R\$\s*([\d.,]+)', text, re.I)
            area = re.search(r'(\d+(?:[.,]\d+)?)\s*m²', text, re.I)
            rooms = re.search(r'\b(\d+)\s+Quartos?\b', text, re.I)
            spots = re.search(r'\b(\d+)\s+Vagas?\b', text, re.I)
            result[code] = {'codigo': code, 'url': url, 'cidade': 'Santos', 'tipo': 'Apartamento',
                            'bairro': district.group(1), 'titulo': text[:250],
                            'valor': price.group(1) if price else None,
                            'areaprincipal': area.group(1) if area else None,
                            'numeroquartos': rooms.group(1) if rooms else None,
                            'numerovagas': spots.group(1) if spots else None}
        if len(seen) >= expected:
            return result
        if not cards or len(seen) == previous:
            raise RuntimeError('Kenlo: paginação incompleta ou repetida')
        time.sleep(0.2)
    raise RuntimeError('Kenlo: limite de páginas excedido')


def matches_kenlo(site, item):
    price = number(item.get('valor'))
    area = number(item.get('areaprincipal'))
    rooms = number(item.get('numeroquartos'))
    if price is None or price <= 0 or price > 530000 or (area is not None and area < 70) or (rooms is not None and rooms != 2):
        return False, ''
    url = item['url']
    response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    description = soup.select_one('.box-description')
    if description is None:
        raise ValueError('Kenlo: descrição da ficha não encontrada')
    sections = [s.get_text(' ', strip=True) for s in soup.select('section.box-detail')
                if s.find(['h2','h3']) and norm(s.find(['h2','h3']).get_text(' ', strip=True)) == 'caracteristicas']
    text = norm(' '.join([description.get_text(' ', strip=True), *sections]))
    if re.search(r'\bsem\s+vaga\b|\b(?:andar|pavimento)\s*:?[ ]*0\b|\bterreo\b|\bgarden\b|\bquintal\b', text):
        return False, url
    if re.search(r'\b(?:vaga|garagem)\s+coletiva\b', text):
        item['tipovagas'] = 'coletiva'
    taxes = soup.select('.taxes .tax')
    for tax in taxes:
        label = tax.get_text(' ', strip=True)
        if norm(label).startswith('condominio'):
            amount = re.search(r'R\$\s*([\d.,]+)', label)
            if amount:
                item['valorcondominio'] = amount.group(1)
            break
    address = soup.select_one('address.address-card__content__address')
    item['endereco'] = address.get_text(' ', strip=True) if address else ''
    item['numeroelevador'] = 1 if re.search(r'\belevador(?:es)?\b', text) and not re.search(r'\bsem\s+elevador\b', text) else 0
    item['_kenlo_text'] = text
    item['_kenlo_validated'] = True
    return matches(site, item)


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
    item['_report_detail_text'] = description + ' ' + features
    address_node = soup.select_one('h2.column')
    street = norm(address_node.get_text(' ', strip=True) if address_node else item.get('endereco'))
    if street:
        item['endereco'] = street
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
    item['_report_detail_text'] = normalized
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
    if site in KENLO:
        return item['url'], item['_kenlo_text']
    if site == 'maneco' and item.get('_unsoft_text') is not None:
        return item['_unsoft_url'], item['_unsoft_text']
    if site in DIRECT_DETAIL_SITES:
        url = item.get('url', '')
        if not url or urlparse(url).netloc != urlparse(base).netloc:
            raise ValueError('Link do anúncio ausente ou inválido')
        response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=35)
        if response.status_code in (404, 410):
            item['_unavailable'] = True
            return url, ''
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        scope = soup.select_one('main') or soup.select_one('article') or soup.body or soup
        raw_text = ' '.join(scope.get_text(' ', strip=True).split())
        normalized = norm(raw_text)
        item['descricao'] = raw_text

        if site == 'familia':
            discounted = re.search(
                r'\bvenda\s*:?\s*de\s*R\$\s*[\d.,]+\s+por\s*:?\s*R\$\s*([\d.,]+)', raw_text, re.I)
            sale = re.search(r'\bvenda\s*:?\s*R\$\s*([\d.,]+)', raw_text, re.I)
            if discounted or sale:
                item['valor'] = (discounted or sale).group(1)

        if item.get('valorcondominio') is None:
            fee = re.search(r'\bcondom[ií]nio\b\s*(?:[:\-]\s*)?(?:R\$\s*)?([\d.,]+)', raw_text, re.I)
            if fee:
                item['valorcondominio'] = fee.group(1)
        if item.get('tipovagas') is None or not item.get('tipovagas'):
            if re.search(r'\b(?:vaga|garagem)\s+coletiva\b', normalized):
                item['tipovagas'] = 'coletiva'
                if number(item.get('numerovagas')) is None:
                    item['numerovagas'] = '1'
        if re.search(r'\b(?:sem|nao tem|nao possui)\s+elevador\b', normalized):
            item['numeroelevador'] = 0
        elif re.search(r'\belevador(?:es)?\b', normalized):
            item['numeroelevador'] = 1
        if re.search(r'\bterreo\b', normalized):
            item['numeroandar'] = 0
        else:
            floor = re.search(r'\b(?:andar|pavimento)\s*[:\-]?\s*(\d+)\b', normalized)
            if floor:
                item['numeroandar'] = floor.group(1)

        address = soup.select_one('address')
        if address is not None and not item.get('endereco'):
            item['endereco'] = address.get_text(' ', strip=True)
        if not item.get('endereco'):
            street = re.search(r'\b(?:rua|avenida|av\.?|alameda|travessa|pra[cç]a)\s+[^,|.;]{3,90}', raw_text, re.I)
            if street:
                item['endereco'] = street.group(0).strip()

        normalized_item = parse_card_item(item.get('codigo', ''), url, raw_text,
                                          item.get('bairro', ''), item.get('tipo', 'Apartamento'))
        for key in ('areaprincipal', 'numeroquartos', 'numerovagas', 'valor'):
            if item.get(key) in (None, '') and normalized_item.get(key) not in (None, ''):
                item[key] = normalized_item[key]
        if not item.get('tipovagas') and normalized_item.get('tipovagas'):
            item['tipovagas'] = normalized_item['tipovagas']
        return url, normalized
    if site == 'roda':
        url = item.get('url')
    else:
        slug = item.get('url_amigavel') if site in UNSOFT else item.get('titulo')
        url = base + 'imovel/' + str(slug).strip('/') + '/' + str(item['codigo']) if slug else None
    if not url or not url.startswith(base):
        raise ValueError('Link do anúncio ausente ou inválido')
    response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=30)
    response.raise_for_status()
    if site in UNSOFT:
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


def matches_b(item):
    """Aplica o perfil paralelo B: Santos, oito bairros, R$ 426 mil e os limites associados."""
    neighborhood = norm(item.get('bairro'))
    kind = norm(item.get('tipo'))
    title = norm(item.get('titulo'))
    description = norm(item.get('descricao'))
    price, condo = number(item.get('valor')), number(item.get('valorcondominio'))
    area, rooms = number(item.get('areaprincipal')), number(item.get('numeroquartos'))
    spots = number(item.get('numerovagas'))
    collective = ('coletiv' in norm(item.get('tipovagas'))
                  or bool(re.search(r'\b(?:vaga|garagem)\s+coletiva\b', description)))
    text = ' '.join([kind, title, description])
    floor = number(item.get('numeroandar'))
    if (norm(item.get('cidade')) != 'santos' or neighborhood not in B
            or 'apartamento' not in kind or 'garden' in kind or 'terreo' in kind
            or price is None or price <= 0 or price > 426000
            or area is None or area < 70 or rooms != 2
            or (condo is not None and (condo < 0 or condo > 800))
            or ((spots is None or spots < 1) and not collective)
            or floor == 0 or re.search(r'\bterreo\b|\bgarden\b|\bquintal\b', text)):
        return False, item.get('url', '')
    return True, item.get('url', '')


def matches(site, item):
    if site in {'bw', 'remax_evoke_iv'}:
        return matches_b(item)
    if site in KENLO and not item.get('_kenlo_validated'):
        return matches_kenlo(site, item)
    if site == 'maneco' and not item.get('_maneco_validated'):
        return matches_maneco(item)
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
    direct = site in DIRECT_DETAIL_SITES
    if (price is None or price <= 0 or price > 530000 or (condo is not None and condo < 0)
            or (area is None and not direct) or (area is not None and area < 70)
            or (rooms is None and not direct) or (rooms is not None and rooms != 2)
            or ((spots is None or spots < 1) and not collective and not direct)):
        return False, ''
    if condo is not None and condo > 1100:
        return False, ''
    # Consulta a ficha para verificar descrições e manter link válido.
    url, description = detail(site, item)
    item['_report_detail_text'] = description
    if item.get('_unavailable'):
        return False, url
    if direct:
        price = number(item.get('valor'))
        area = number(item.get('areaprincipal'))
        rooms = number(item.get('numeroquartos'))
        spots = number(item.get('numerovagas'))
        condo = number(item.get('valorcondominio'))
        collective = 'coletiv' in norm(item.get('tipovagas'))
        if (price is None or price <= 0 or price > 530000
                or area is None or area < 70 or rooms != 2
                or ((spots is None or spots < 1) and not collective)):
            return False, url
        if condo is not None and (condo < 0 or condo > 1100):
            return False, url
    combined = ' '.join([title, kind, norm(item.get('descricao')), description])
    floor = number(item.get('numeroandar'))
    if (floor == 0 or re.search(r'\bterreo\b|\bgarden\b|\bquintal\b', combined)
            or norm(item.get('quintal')) in {'1', 'true', 'sim'}):
        return False, url
    if site in B_ONLY_SITES:
        return price <= 426000 and (condo is None or 0 <= condo <= 800), url
    if price <= 426000 and (condo is None or condo <= 800):
        return True, url
    elevator = number(item.get('numeroelevador'))
    has_elevator = (elevator is not None and elevator > 0) or bool(
        re.search(r'\b(?:com|possui|tem) elevador\b|\belevador social\b', combined))
    if site in UNSOFT and re.search(r'\belevador(?:es)?\b', description):
        has_elevator = True
    if re.search(r'\bsem elevador\b', combined):
        has_elevator = False
    street = norm(item.get('endereco'))
    known_street = bool(re.match(r'^(rua|avenida|av|alameda|travessa|praca|estrada|rodovia|largo)\b', street))
    avenue = bool(item.get('_address_unverified')) or not known_street or bool(re.match(r'^(avenida|av)\b', street))
    return (neighborhood in A and price <= 530000 and (condo is None or condo <= 1100)
            and has_elevator and not avenue), url


def matches_maneco(item):
    """A API reduzida da Maneco usa areainterna e não devolve o condomínio."""
    item['areaprincipal'] = item.get('areaprincipal') or item.get('areainterna')
    price, area, rooms = number(item.get('valor')), number(item.get('areaprincipal')), number(item.get('numeroquartos'))
    if (norm(item.get('cidade')) != 'santos' or norm(item.get('bairro')) not in B
            or 'apartamento' not in norm(item.get('tipo')) or price is None or price <= 0 or price > 530000
            or area is None or area < 70 or rooms != 2):
        return False, ''
    base = SITE['maneco'][0]
    slug = item.get('url_amigavel')
    if not slug:
        raise ValueError('Maneco: ficha sem caminho')
    url = base + 'imovel/' + str(slug).strip('/') + '/' + str(item['codigo'])
    response = SESSION.get(url, headers={'X-Requested-With': None}, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    scope = soup.select_one('.container-esquerda')
    description = scope.select_one('p.descricao') if scope else None
    if description is None:
        raise ValueError('Maneco: descrição não encontrada')
    features = [node.get_text(' ', strip=True) for node in scope.select('li.caracteristicas-extras')
                if 'extras-none' not in (node.get('class') or [])]
    heading = scope.find('h1')
    text = norm(' '.join([heading.get_text(' ', strip=True) if heading else '', description.get_text(' ', strip=True), *features]))
    if re.search(r'\bsem\s+vaga\b|\b(?:andar|pavimento)\s*0\b', text):
        return False, url
    for label in soup.select('p.p-cinza'):
        if norm(label.get_text(' ', strip=True)) == 'condominio':
            value = label.find_next_sibling(['h6','span','p'])
            if value:
                item['valorcondominio'] = value.get_text(' ', strip=True)
            break
    if item.get('valorcondominio') is None:
        fee = re.search(r'Condom[ií]nio\s*:?\s*R\$\s*([\d.,]+)', description.get_text(' ', strip=True), re.I)
        if fee:
            item['valorcondominio'] = fee.group(1)
    if re.search(r'\b(?:vaga|garagem)\s+coletiva\b', text):
        item['tipovagas'] = 'coletiva'
    item['_unsoft_text'], item['_unsoft_url'], item['_maneco_validated'] = text, url, True
    return matches('maneco', item)


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
    message = (f"Novo apartamento - {SITE_LABEL.get(site, site.replace('_', ' ').title())}\n"
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
    name = SITE_LABEL.get(site, names.get(site, site))
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
