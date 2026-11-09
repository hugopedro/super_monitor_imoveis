#!/usr/bin/env python3
"""
Monitor de Imóveis - ZapImóveis
Monitora novos imóveis e envia notificações via Telegram
"""

import requests
import cloudscraper
import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
import logging
import random
import hashlib
import re
from visual_analyzer import VisualPropertyAnalyzer

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ZapImoveisMonitor:
    """Monitor de novos imóveis no ZapImóveis"""
    
    def __init__(self, telegram_token: str, telegram_chat_id: str):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.state_file = Path("monitor_state.json")
        self.known_listings: Dict[str, dict] = {}
        self.property_signatures: Dict[str, List[str]] = {}  # Assinatura -> [IDs]
        self.enhanced_signatures: Dict[str, dict] = {}  # ID -> assinatura aprimorada
        self.min_area = 70  # Área mínima em m² para notificações
        self.base_url = "https://glue-api.zapimoveis.com.br/v2/listings"
        self.page_size = 20
        neighborhoods_a = {'aparecida', 'boqueirao', 'embare', 'gonzaga', 'pompeia'}
        neighborhoods_b = neighborhoods_a | {'campo grande', 'marape', 'jose menino'}
        self.purchase_profiles = [
            {'name': 'principal', 'neighborhoods': neighborhoods_a, 'max_price': 530000,
             'max_condo': 1100, 'require_elevator': True, 'exclude_avenue': True},
            {'name': 'paralelo', 'neighborhoods': neighborhoods_b, 'max_price': 426000,
             'max_condo': 800, 'require_elevator': False, 'exclude_avenue': False},
        ]
        self.neighborhood_locations = [
            ('Aparecida', 'BR>Sao Paulo>NULL>Santos>Barrios>Aparecida'),
            ('Boqueirão', 'BR>Sao Paulo>NULL>Santos>Barrios>Boqueirao'),
            ('Embaré', 'BR>Sao Paulo>NULL>Santos>Barrios>Embare'),
            ('Gonzaga', 'BR>Sao Paulo>NULL>Santos>Barrios>Gonzaga'),
            ('Pompéia', 'BR>Sao Paulo>NULL>Santos>Barrios>Pompeia'),
            ('Campo Grande', 'BR>Sao Paulo>NULL>Santos>Barrios>Campo Grande'),
            ('Marapé', 'BR>Sao Paulo>NULL>Santos>Barrios>Marape'),
            ('José Menino', 'BR>Sao Paulo>NULL>Santos>Barrios>Jose Menino'),
        ]
        
        # Inicializa analisador visual
        self.visual_analyzer = VisualPropertyAnalyzer()
        
        # Cria um scraper com cloudscraper (bypassa Cloudflare)
        self.session = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'desktop': True
            }
        )
        
        # Headers essenciais para a API
        self.session.headers.update({
            'X-Domain': 'www.zapimoveis.com.br',
            'Referer': 'https://www.zapimoveis.com.br/',
            'Origin': 'https://www.zapimoveis.com.br',
            'Accept': 'application/json, text/plain, */*'
        })
        
        # Parâmetros da busca (Santos, 2 quartos, etc.)
        self.search_params = {
            'bedrooms': '2',
            'business': 'SALE',
            'parkingSpaces': '1',
            'parentId': 'null',
            'listingType': 'USED',
            '__zt': 'mtc:deduplication2023',
            'priceMax': '530000',
            'addressCity': 'Santos,Santos,Santos,Santos,Santos',
            'addressZone': ',,,,',
            'addressStreet': ',,,,',
            'addressLocationId': (
                                     'BR>Sao Paulo>NULL>Santos>Barrios>Aparecida,BR>Sao Paulo>NULL>Santos>Barr'
                                     'ios>Embare,BR>Sao Paulo>NULL>Santos>Barrios>Gonzaga,BR>Sao Paulo>NULL,BR'
                                     '>Sao Paulo>NULL>Santos>Barrios>Pompeia'
                                 ),
            'addressState': 'São Paulo,São Paulo,São Paulo,São Paulo,São Paulo',
            'addressNeighborhood': 'Aparecida,Embaré,Gonzaga,Ponta da Praia,Pompeia',
            'addressPointLat': '-23.973538,-23.964803,-23.967382,,-23.966415',
            'addressPointLon': '-46.305518,-46.323585,-46.332815,,-46.342411',
            'addressType': 'neighborhood,neighborhood,neighborhood,neighborhood,neighborhood',
            'unitTypes': 'APARTMENT',
            'unitTypesV3': 'APARTMENT',
            'unitSubTypes': 'UnitSubType_NONE,DUPLEX,TRIPLEX',
            'usageTypes': 'RESIDENTIAL',
            'size': '20',  # Limite atual da API
            'from': '0',
            'images': 'webp',
            'categoryPage': 'RESULT',
            'includeFields': 'search(result(listings)),totalCount'
        }

        # Consulta ampla compartilhada pelas regras principal e paralela.
        locations = [item[1] for item in self.neighborhood_locations]
        neighborhoods = [item[0] for item in self.neighborhood_locations]
        location_filter = ' OR '.join(f'address.locationId:"{location}"' for location in locations)
        self.search_params.update({
            'priceMax': '530000',
            'addressCity': ','.join(['Santos'] * len(neighborhoods)),
            'addressZone': ','.join(['Bairros'] * len(neighborhoods)),
            'addressStreet': ','.join([''] * len(neighborhoods)),
            'addressLocationId': ','.join(locations),
            'addressState': ','.join(['São Paulo'] * len(neighborhoods)),
            'addressNeighborhood': ','.join(neighborhoods),
            'addressPointLat': ','.join([''] * len(neighborhoods)),
            'addressPointLon': ','.join([''] * len(neighborhoods)),
            'addressType': ','.join(['neighborhood'] * len(neighborhoods)),
            'size': str(self.page_size),
            'includeFields': self.search_params['includeFields'].replace(
                'floors,unitTypesV3', 'floors,unitFloor,amenities,unitTypesV3'
            ),
            'filter': (
                f'({location_filter}) AND pricingInfos.price<=530000 '
                'AND bedrooms>=2 AND bedrooms<=2 AND (parkingSpaces>=1 OR parkingSpaces="1") '
                'AND usableAreas>=70'
            ),
        })
        
        self.load_state()
        self._warm_up_session()
    
    def _warm_up_session(self):
        """Aquece a sessão fazendo uma requisição inicial"""
        try:
            logger.info("Inicializando sessão com ZapImóveis...")
            # Visita a página principal primeiro
            self.session.get('https://www.zapimoveis.com.br/', timeout=10)
            time.sleep(random.uniform(1, 2))
            logger.info("Sessão inicializada com sucesso")
        except Exception as e:
            logger.warning(f"Aviso ao inicializar sessão: {e}")
    
    def load_state(self):
        """Carrega o estado salvo (imóveis conhecidos)"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.known_listings = data.get('known_listings', {})
                    self.property_signatures = data.get('property_signatures', {})
                    self.enhanced_signatures = data.get('enhanced_signatures', {})
                logger.info(f"Estado carregado: {len(self.known_listings)} imóveis conhecidos")
                logger.info(f"Assinaturas únicas de imóveis: {len(self.property_signatures)}")
                logger.info(f"Assinaturas aprimoradas: {len(self.enhanced_signatures)}")
            except Exception as e:
                logger.error(f"Erro ao carregar estado: {e}")
                self.known_listings = {}
                self.property_signatures = {}
                self.enhanced_signatures = {}
        else:
            logger.info("Nenhum estado anterior encontrado. Iniciando novo.")
            self.known_listings = {}
            self.property_signatures = {}
            self.enhanced_signatures = {}
    
    def save_state(self):
        """Salva o estado atual (imóveis conhecidos)"""
        try:
            data = {
                'known_listings': self.known_listings,
                'property_signatures': self.property_signatures,
                'enhanced_signatures': self.enhanced_signatures,
                'last_update': datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Estado salvo: {len(self.known_listings)} imóveis")
            logger.debug(f"Assinaturas únicas: {len(self.property_signatures)}")
            logger.debug(f"Assinaturas aprimoradas: {len(self.enhanced_signatures)}")
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")
    
    def fetch_listings(self, page: int = 1, max_retries: int = 3) -> Optional[dict]:
        """Busca imóveis da API do ZapImóveis com retry automático"""
        params = self.search_params.copy()
        params['page'] = str(page)
        params['from'] = str((page - 1) * self.page_size)
        
        # Delay aleatório para não parecer bot
        if page > 1:
            time.sleep(random.uniform(1, 2))
        
        for attempt in range(max_retries):
            try:
                response = self.session.get(
                    self.base_url,
                    params=params,
                    timeout=30
                )
                
                # Debug: verifica se resposta tem conteúdo
                if not response.text or len(response.text) < 10:
                    logger.error(f"Resposta vazia ou muito curta da API (página {page})")
                    return None
                
                response.raise_for_status()
                
                # Tenta parsear JSON
                try:
                    return response.json()
                except json.JSONDecodeError as e:
                    logger.error(f"Erro ao parsear JSON (página {page}): {e}")
                    logger.error(f"Primeiros 200 caracteres: {response.text[:200]}")
                    return None
                    
            except requests.exceptions.HTTPError as e:
                logger.error(f"Erro HTTP ao buscar imóveis (página {page}): {e}")
                if e.response.status_code == 403:
                    logger.error(f"Acesso negado (403) - O Cloudflare pode estar bloqueando")
                    logger.info("Tentando reinicializar sessão...")
                    self._warm_up_session()
                return None
                
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait_time = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"Erro de conexão na página {page} (tentativa {attempt + 1}/{max_retries}): {e}")
                    logger.info(f"Aguardando {wait_time:.1f}s antes de tentar novamente...")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Erro de conexão ao buscar imóveis (página {page}) após {max_retries} tentativas: {e}")
                    return None
        
        return None
    
    def get_full_listing_data(self, listing_id: str, basic_data: dict) -> dict:
        """
        Obtém dados completos de um imóvel, incluindo imagens.
        Se não conseguir buscar detalhes, retorna os dados básicos.
        """
        try:
            # Tenta buscar dados detalhados do imóvel específico
            detail_url = f"https://glue-api.zapimoveis.com.br/v2/listings/{listing_id}"
            
            response = self.session.get(
                detail_url,
                headers={
                    'X-Domain': 'www.zapimoveis.com.br',
                    'Referer': f'https://www.zapimoveis.com.br/imovel/{listing_id}/',
                },
                timeout=10
            )
            
            if response.status_code == 200:
                detail_data = response.json()
                
                # Combina dados detalhados com básicos
                if 'listing' in detail_data:
                    full_data = detail_data['listing']
                    # Preserva dados básicos que podem não estar nos detalhes
                    for key, value in basic_data.items():
                        if key not in full_data:
                            full_data[key] = value
                    return full_data
                    
        except Exception as e:
            logger.debug(f"Não foi possível buscar detalhes do imóvel {listing_id}: {e}")
        
        # Retorna dados básicos se não conseguir detalhes
        return basic_data
    
    def get_all_current_listings(self) -> Dict[str, dict]:
        """Busca todos os imóveis disponíveis atualmente"""
        all_listings = {}
        page = 1
        
        logger.info("Buscando imóveis disponíveis...")
        
        while True:
            data = self.fetch_listings(page)
            
            if not data or 'search' not in data:
                break
            
            search_data = data['search']
            results = search_data.get('result', {})
            listings = results.get('listings', [])
            
            if not listings:
                break
            
            for listing in listings:
                listing_data = listing.get('listing', {})
                listing_id = listing_data.get('id')
                
                if listing_id:
                    # Extrai dados de preço
                    pricing_infos = listing_data.get('pricingInfos', [{}])
                    price = pricing_infos[0].get('price', 'N/A') if pricing_infos else 'N/A'
                    
                    # Extrai dados de quartos, vagas e área
                    bedrooms_list = listing_data.get('bedrooms', [])
                    bedrooms = bedrooms_list[0] if isinstance(bedrooms_list, list) and bedrooms_list else 0
                    
                    parking_list = listing_data.get('parkingSpaces', [])
                    parking = parking_list[0] if isinstance(parking_list, list) and parking_list else 0
                    
                    areas_list = listing_data.get('usableAreas', [])
                    area = areas_list[0] if isinstance(areas_list, list) and areas_list else 0
                    
                    # Armazena informações relevantes do imóvel
                    all_listings[listing_id] = {
                        'id': listing_id,
                        'title': listing_data.get('title', 'Sem título'),
                        'price': price,
                        'address': listing_data.get('address', {}),
                        'bedrooms': bedrooms,
                        'parkingSpaces': parking,
                        'usableAreas': area,
                        'monthlyCondoFee': pricing_infos[0].get('monthlyCondoFee') if pricing_infos else None,
                        'unitFloor': listing_data.get('unitFloor'),
                        'amenities': listing_data.get('amenities', []),
                        'unitSubTypes': listing_data.get('unitSubTypes', []),
                        'link': f"https://www.zapimoveis.com.br/imovel/{listing_id}/",
                        'found_at': datetime.now().isoformat()
                    }
            
            logger.info(f"Página {page}: {len(listings)} imóveis encontrados")
            
            # Verifica se há mais páginas
            total_count = search_data.get('totalCount') or results.get('totalCount')
            if total_count is not None:
                if page * self.page_size >= int(total_count):
                    break
            elif len(listings) < self.page_size:
                # Zap não expõe totalCount; continua até a última página vir incompleta.
                break
            
            page += 1
            time.sleep(1)  # Delay entre requisições
        
        logger.info(f"Total de imóveis disponíveis: {len(all_listings)}")
        return all_listings
    
    def normalize_text(self, text: str) -> str:
        """Normaliza texto para comparação mais eficaz"""
        if not text:
            return ""
        text = str(text)
        
        # Remove caracteres especiais e normaliza
        import unicodedata
        text = unicodedata.normalize('NFKD', text)
        text = ''.join([c for c in text if not unicodedata.combining(c)])
        
        # Lowercase e remove espaços extras
        text = text.lower().strip()
        text = ' '.join(text.split())  # Remove espaços múltiplos
        
        # Normaliza pontuação e remove palavras comuns como tokens inteiros,
        # sem apagar letras dentro de nomes como Aparecida ou Marapé.
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        ignored = {'apartamento', 'apto', 'residencial', 'a', 'venda', 'para',
                   'com', 'de', 'e', 'ou', 'em', 'no', 'na'}
        return ' '.join(word for word in text.split() if word not in ignored)

    @staticmethod
    def _numeric_value(value):
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, (int, float)):
            return float(value)
        if value is None:
            return None
        raw = str(value).strip().replace('R$', '').replace(' ', '')
        if ',' in raw:
            raw = raw.replace('.', '').replace(',', '.')
        elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', raw):
            raw = raw.replace('.', '')
        match = re.search(r'-?\d+(?:\.\d+)?', raw)
        return float(match.group(0)) if match else None

    def matches_purchase_profile(self, listing: dict) -> bool:
        address = listing.get('address') or {}
        neighborhood = self.normalize_text(address.get('neighborhood', ''))
        price = self._numeric_value(listing.get('price'))
        area = self._numeric_value(listing.get('usableAreas'))
        bedrooms = self._numeric_value(listing.get('bedrooms'))
        parking = self._numeric_value(listing.get('parkingSpaces'))
        condo = self._numeric_value(listing.get('monthlyCondoFee'))
        floor = self._numeric_value(listing.get('unitFloor'))
        floor_text = self.normalize_text(listing.get('unitFloor', ''))
        title = self.normalize_text(listing.get('title', ''))
        subtypes = listing.get('unitSubTypes') or []
        amenities = listing.get('amenities') or []
        if isinstance(subtypes, str):
            subtypes = [subtypes]
        if isinstance(amenities, str):
            amenities = [amenities]
        subtype_text = self.normalize_text(' '.join(map(str, subtypes)))
        amenity_text = self.normalize_text(' '.join(map(str, amenities)))
        street = str(address.get('street', '') or '').strip().lower()

        if (price is None or area is None or bedrooms is None or parking is None
                or neighborhood == '' or area < 70
                or bedrooms != 2 or parking < 1 or floor == 0 or 'terreo' in floor_text
                or 'terreo' in title or 'garden' in title or 'quintal' in title
                or 'garden' in subtype_text or 'quintal' in subtype_text):
            return False

        has_elevator = 'elevator' in amenity_text or 'elevador' in amenity_text
        is_avenue = bool(re.match(r'^(?:avenida|av\.?)(?:\s|$)', street))
        for profile in self.purchase_profiles:
            if (neighborhood in profile['neighborhoods']
                    and price <= profile['max_price']
                    and (condo is None or condo <= profile['max_condo'])
                    and (not profile['require_elevator'] or has_elevator)
                    and (not profile['exclude_avenue'] or not is_avenue)):
                return True
        return False
    
    def create_property_signature(self, listing: dict) -> str:
        """Cria uma assinatura básica baseada nas características do imóvel"""
        address = listing.get('address', {})
        street = self.normalize_text(address.get('street', ''))
        neighborhood = self.normalize_text(address.get('neighborhood', ''))
        
        # Características principais do imóvel
        bedrooms = listing.get('bedrooms', 0)
        area = listing.get('usableAreas', 0)
        bathrooms = listing.get('bathrooms', 0) if 'bathrooms' in listing else 0
        parking = listing.get('parkingSpaces', 0)
        
        # Normaliza o título
        title = self.normalize_text(listing.get('title', ''))
        
        # Cria assinatura combinando características únicas
        # Usa endereço + área + quartos como identificador principal
        signature = f"{street}|{neighborhood}|{bedrooms}|{area}|{bathrooms}|{parking}"
        
        # Se não tiver endereço completo, usa o título como fallback
        if not street and not neighborhood:
            signature = f"{title}|{bedrooms}|{area}|{bathrooms}|{parking}"
        
        return signature
    
    def create_enhanced_signature(self, listing: dict) -> dict:
        """
        Cria uma assinatura aprimorada com múltiplos níveis de identificação.
        Combina características físicas, localização e hash de conteúdo.
        """
        address = listing.get('address', {})
        
        # Extrai e normaliza todos os campos relevantes
        street = self.normalize_text(address.get('street', ''))
        neighborhood = self.normalize_text(address.get('neighborhood', ''))
        city = self.normalize_text(address.get('city', ''))
        
        # Extrai número do endereço se houver
        street_number = address.get('streetNumber', '')
        if not street_number and street:
            # Tenta extrair número do endereço
            import re
            numbers = re.findall(r'\d+', street)
            street_number = numbers[0] if numbers else ''
        
        # Características físicas
        bedrooms = listing.get('bedrooms', 0)
        bathrooms = listing.get('bathrooms', 0) if 'bathrooms' in listing else 0
        area = listing.get('usableAreas', 0)
        parking = listing.get('parkingSpaces', 0)
        
        # Características adicionais
        suites = listing.get('suites', 0) if 'suites' in listing else 0
        floors = listing.get('floors', 0) if 'floors' in listing else 0
        
        # Localização geográfica (se disponível)
        point = address.get('point', {})
        lat = point.get('lat', 0) if point else 0
        lon = point.get('lon', 0) if point else 0
        
        # Cria múltiplas assinaturas com diferentes níveis de especificidade
        signature = {
            # Assinatura primária (mais específica)
            'primary': f"{street}|{street_number}|{neighborhood}|{bedrooms}|{area}|{bathrooms}",
            
            # Assinatura secundária (menos específica)
            'secondary': f"{neighborhood}|{bedrooms}|{area}|{bathrooms}|{parking}",
            
            # Assinatura terciária (características físicas)
            'physical': f"{bedrooms}|{bathrooms}|{suites}|{area}|{parking}|{floors}",
            
            # Assinatura geográfica (se coordenadas disponíveis)
            'geographic': f"{lat:.5f}|{lon:.5f}" if lat and lon else "",
            
            # Hash do conteúdo completo para detecção exata
            'content_hash': hashlib.md5(
                json.dumps(listing, sort_keys=True).encode()
            ).hexdigest()
        }
        
        return signature
    
    def detect_new_listings(self, current_listings: Dict[str, dict]) -> List[dict]:
        """Detecta novos imóveis usando análise multi-nível (visual + características)"""
        new_listings = []
        duplicates_detected = []
        
        for listing_id, listing_data in current_listings.items():
            if not self.matches_purchase_profile(listing_data):
                continue
            # Verifica área mínima
            area = listing_data.get('usableAreas', 0)
            if area < self.min_area:
                logger.debug(f"Imóvel ID {listing_id} ignorado: área {area}m² < {self.min_area}m²")
                continue
            
            if listing_id not in self.known_listings:
                # Cria assinaturas aprimoradas
                basic_signature = self.create_property_signature(listing_data)
                enhanced_signature = self.create_enhanced_signature(listing_data)
                
                # Verifica duplicação por assinatura básica
                is_duplicate = False
                duplicate_reason = ""
                duplicate_ids = []
                
                # 1. Verificação por assinatura básica
                if basic_signature in self.property_signatures:
                    existing_ids = self.property_signatures[basic_signature]
                    is_duplicate = True
                    duplicate_reason = "assinatura básica"
                    duplicate_ids = existing_ids
                
                # 2. Verificação por assinaturas aprimoradas
                if not is_duplicate:
                    for sig_type in ['primary', 'secondary', 'physical']:
                        sig_value = enhanced_signature.get(sig_type, '')
                        if sig_value:
                            # Verifica se essa assinatura já existe
                            for known_id, known_data in self.enhanced_signatures.items():
                                if known_id != listing_id and known_data.get(sig_type) == sig_value:
                                    # Confirma se é realmente similar verificando múltiplos campos
                                    similarity_count = sum([
                                        enhanced_signature.get('physical') == known_data.get('physical'),
                                        enhanced_signature.get('secondary') == known_data.get('secondary'),
                                        abs(area - self.known_listings.get(known_id, {}).get('area', 0)) <= 5
                                    ])
                                    
                                    if similarity_count >= 2:  # Pelo menos 2 critérios devem coincidir
                                        is_duplicate = True
                                        duplicate_reason = f"assinatura {sig_type}"
                                        duplicate_ids = [known_id]
                                        break
                        
                        if is_duplicate:
                            break
                
                # 3. Verificação visual (mais pesada, só faz se ainda não detectou duplicata)
                if not is_duplicate and hasattr(self, 'visual_analyzer'):
                    try:
                        # Busca o listing completo da API se necessário
                        full_listing = self.get_full_listing_data(listing_id, listing_data)
                        
                        is_visual_duplicate, visual_similar_ids = self.visual_analyzer.is_duplicate_property(
                            listing_id, 
                            full_listing,
                            self.known_listings
                        )
                        
                        if is_visual_duplicate:
                            is_duplicate = True
                            duplicate_reason = "análise visual"
                            duplicate_ids = visual_similar_ids
                            logger.info(f"[VISUAL] Duplicata visual detectada: {listing_id} similar a {visual_similar_ids}")
                    except Exception as e:
                        logger.warning(f"Erro na análise visual do imóvel {listing_id}: {e}")
                
                # Processa resultado da detecção
                if is_duplicate:
                    duplicates_detected.append({
                        'new_id': listing_id,
                        'existing_ids': duplicate_ids,
                        'title': listing_data.get('title', 'Sem título'),
                        'area': area,
                        'reason': duplicate_reason
                    })
                    logger.warning(f"[DUPLICADO] Imóvel duplicado detectado via {duplicate_reason}: ID {listing_id}")
                    logger.warning(f"   Título: {listing_data.get('title', 'N/A')}")
                    logger.warning(f"   IDs similares: {', '.join(map(str, duplicate_ids))}")
                else:
                    # Este é realmente um imóvel novo!
                    new_listings.append(listing_data)
                    logger.info(f"[NOVO] Novo imóvel detectado: ID {listing_id} - {area}m²")
                    
                    # Armazena a assinatura aprimorada para futuras comparações
                    self.enhanced_signatures[listing_id] = enhanced_signature
        
        # Relatório de duplicatas detectadas
        if duplicates_detected:
            logger.info(f"[RESUMO] {len(duplicates_detected)} imóveis duplicados/repostados ignorados")
            by_reason = {}
            for dup in duplicates_detected:
                reason = dup['reason']
                if reason not in by_reason:
                    by_reason[reason] = 0
                by_reason[reason] += 1
                logger.info(f"   - {dup['title'][:50]}... ({dup['area']}m²) - via {reason}")
            
            logger.info("[ESTATÍSTICAS DE DETECÇÃO]")
            for reason, count in by_reason.items():
                logger.info(f"   {reason}: {count} duplicata(s)")
        
        return new_listings
    
    def send_telegram_notification(self, listing: dict):
        """Envia notificação via Telegram"""
        # Formata a mensagem
        address = listing.get('address', {})
        neighborhood = address.get('neighborhood', 'N/A')
        street = address.get('street', 'N/A')
        city = address.get('city', 'Santos')
        
        price = listing.get('price')
        if isinstance(price, (int, float)):
            price_text = f"R$ {price:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')
        else:
            price_text = str(price)
        
        bedrooms = listing.get('bedrooms', 'N/A')
        parking = listing.get('parkingSpaces', 'N/A')
        area = listing.get('usableAreas', 'N/A')
        
        message = f"""
🏠 *NOVO IMÓVEL ENCONTRADO!*

📍 *Endereço:*
{street}
{neighborhood}, {city}

💰 *Valor:* {price_text}
🛏️ *Quartos:* {bedrooms}
🚗 *Vagas:* {parking}
📐 *Área:* {area}m² ✅

🔗 *Link:* {listing.get('link', 'N/A')}

⏰ Detectado em: {datetime.now().strftime('%d/%m/%Y às %H:%M:%S')}

📌 _Somente imóveis >= 70m² são notificados_
"""
        
        # Envia para o Telegram
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            'chat_id': self.telegram_chat_id,
            'text': message,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': False
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Notificação enviada para imóvel ID {listing.get('id')}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar notificação: {e}")
            return False
    
    def update_known_listings(self, current_listings: Dict[str, dict]):
        """Atualiza a lista de imóveis conhecidos e suas assinaturas"""
        # Adiciona novos imóveis à lista de conhecidos
        for listing_id, listing_data in current_listings.items():
            if not self.matches_purchase_profile(listing_data):
                continue
            # Só processa imóveis com área >= mínima
            area = listing_data.get('usableAreas', 0)
            if area < self.min_area:
                continue
                
            if listing_id not in self.known_listings:
                # Adiciona às listagens conhecidas
                self.known_listings[listing_id] = {
                    'first_seen': listing_data.get('found_at'),
                    'title': listing_data.get('title', ''),
                    'area': area,
                    'bedrooms': listing_data.get('bedrooms', 0),
                    'bathrooms': listing_data.get('bathrooms', 0) if 'bathrooms' in listing_data else 0,
                    'parkingSpaces': listing_data.get('parkingSpaces', 0),
                    'address': listing_data.get('address', {})
                }
                
                # Atualiza assinaturas básicas para detecção de duplicatas
                signature = self.create_property_signature(listing_data)
                if signature not in self.property_signatures:
                    self.property_signatures[signature] = []
                if listing_id not in self.property_signatures[signature]:
                    self.property_signatures[signature].append(listing_id)
                
                # Cria e armazena assinatura aprimorada
                if listing_id not in self.enhanced_signatures:
                    enhanced_sig = self.create_enhanced_signature(listing_data)
                    self.enhanced_signatures[listing_id] = enhanced_sig
        
        # Remove imóveis que não estão mais disponíveis (opcional)
        # Mantendo histórico para melhor detecção de bumps
        current_ids = set(current_listings.keys())
        known_ids = set(self.known_listings.keys())
        removed_ids = known_ids - current_ids
        
        if removed_ids:
            logger.info(f"{len(removed_ids)} imóveis não estão mais disponíveis")
            # Mantém o histórico para detectar repostagens futuras
    
    def monitor_once(self, send_notifications: bool = True) -> int:
        """Executa uma verificação de monitoramento
        
        Args:
            send_notifications: Se False, não envia notificações (útil para inicialização)
        """
        logger.info("=" * 60)
        logger.info("Iniciando verificação de novos imóveis...")
        logger.info(f"Filtro ativo: área mínima de {self.min_area}m²")
        
        # Busca imóveis atuais
        current_listings = self.get_all_current_listings()
        
        if not current_listings:
            logger.warning("Nenhum imóvel encontrado ou erro na busca")
            return 0
        
        # Conta quantos imóveis atendem ao critério de área
        eligible_count = sum(1 for l in current_listings.values() if l.get('usableAreas', 0) >= self.min_area)
        logger.info(f"Imóveis com área >= {self.min_area}m²: {eligible_count} de {len(current_listings)} totais")
        
        # Detecta novos imóveis
        new_listings = self.detect_new_listings(current_listings)
        
        if new_listings:
            logger.info(f"[ENCONTRADO] {len(new_listings)} NOVO(S) IMOVEL(IS) ENCONTRADO(S)!")
            
            if send_notifications:
                # Envia notificações
                for listing in new_listings:
                    self.send_telegram_notification(listing)
                    time.sleep(1)  # Delay entre notificações
            else:
                logger.info("[AVISO] Modo de inicializacao: notificacoes desativadas")
        else:
            logger.info("Nenhum imóvel novo detectado")
        
        # Atualiza lista de imóveis conhecidos
        self.update_known_listings(current_listings)
        
        # Salva estado
        self.save_state()
        
        logger.info("Verificação concluída")
        logger.info("=" * 60)
        
        return len(new_listings)
    
    def monitor_loop(self, interval_minutes: int = 15):
        """Loop de monitoramento contínuo"""
        logger.info(f"Iniciando monitoramento contínuo (intervalo: {interval_minutes} minutos)")
        logger.info("Pressione Ctrl+C para parar")
        
        try:
            while True:
                self.monitor_once()
                logger.info(f"Aguardando {interval_minutes} minutos até próxima verificação...")
                time.sleep(interval_minutes * 60)
        except KeyboardInterrupt:
            logger.info("\nMonitoramento interrompido pelo usuário")
            self.save_state()


def main():
    """Função principal"""
    import sys
    
    # Configurações do Telegram
    TELEGRAM_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
    
    # Cria o monitor
    monitor = ZapImoveisMonitor(
        telegram_token=TELEGRAM_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID
    )

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("Credenciais do Telegram ausentes no ambiente")
        return

    if os.environ.get('MONITOR_BASELINE_ONLY') == '1':
        logger.info("Executando somente a linha de base; notificações desativadas")
        monitor.monitor_once(send_notifications=False)
        return
    
    # Verifica se é primeira execução (sem estado salvo)
    is_first_run = not monitor.state_file.exists() or len(monitor.known_listings) == 0
    
    if is_first_run:
        logger.warning("=" * 60)
        logger.warning("[AVISO] PRIMEIRA EXECUCAO DETECTADA")
        logger.warning("=" * 60)
        logger.warning("Esta e a primeira vez que o monitor executa.")
        logger.warning("Vou buscar todos os imoveis disponiveis e marcar como conhecidos,")
        logger.warning("SEM enviar notificacoes para nao spam no Telegram.")
        logger.warning("")
        logger.warning("A partir da proxima execucao, voce recebera notificacoes")
        logger.warning("apenas de imoveis NOVOS que entrarem no sistema.")
        logger.warning("=" * 60)
        
        # Primeira execução: popula o estado sem enviar notificações
        monitor.monitor_once(send_notifications=False)
        
        logger.info("")
        logger.info("[OK] Inicializacao concluida!")
        logger.info(f"[OK] {len(monitor.known_listings)} imoveis marcados como conhecidos")
        logger.info(f"[INFO] Somente imoveis com area >= {monitor.min_area}m² serao notificados")
        logger.info("")
        logger.info("[PRONTO] Agora voce pode executar o monitor novamente para comecar")
        logger.info("         a receber notificacoes de imoveis NOVOS!")
        logger.info("")
        logger.info("Execute novamente: python3 monitor.py")
        return
    
    # Escolha o modo de operação:
    
    # Opção 1: Executar uma única verificação
    # monitor.monitor_once()
    
    # Opção 2: Monitoramento contínuo (a cada 15 minutos)
    monitor.monitor_loop(interval_minutes=15)


if __name__ == "__main__":
    main()

