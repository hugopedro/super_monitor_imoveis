#!/usr/bin/env python3
"""
Monitor de Imóveis - R3 Imóveis
Monitora novos imóveis e envia notificações via Telegram
"""

import requests
import cloudscraper
import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional
import logging
import hashlib
from bs4 import BeautifulSoup
import re
import unicodedata
from urllib.parse import urljoin

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


class R3ImoveisMonitor:
    """Monitor de novos imóveis no R3 Imóveis"""
    
    def __init__(self, telegram_token: str, telegram_chat_id: str):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.state_file = Path("monitor_state.json")
        self.known_listings: Dict[str, dict] = {}
        self.min_area = 70
        self.max_price = 530000
        self.min_bedrooms = 2
        self.max_bedrooms = 2
        self.min_parking = 1
        self.max_condo_fee = 1100
        neighborhoods_a = {'aparecida', 'boqueirao', 'embare', 'gonzaga', 'pompeia'}
        neighborhoods_b = neighborhoods_a | {'campo grande', 'marape', 'jose menino'}
        self.allowed_neighborhoods = neighborhoods_b
        self.purchase_profiles = [
            {'name': 'principal', 'neighborhoods': neighborhoods_a, 'max_price': 530000,
             'max_condo_fee': 1100, 'require_elevator': True, 'exclude_avenue': True},
            {'name': 'paralelo', 'neighborhoods': neighborhoods_b, 'max_price': 426000,
             'max_condo_fee': 800, 'require_elevator': False, 'exclude_avenue': False},
        ]
        self.max_pages_to_check = 10  # Número máximo de páginas para verificar
        self.stop_after_known_pages = 2  # Para de buscar após X páginas com apenas imóveis conhecidos
        
        # Rota pública atual da busca por apartamentos residenciais à venda em Santos.
        # Os critérios por bairro e preço são validados localmente para atender aos dois perfis.
        self.base_url = 'https://r3imoveis.com.br/imoveis/comprar-apartamento-residencial-para-venda-em-santos'
        
        self.load_state()
    
    def load_state(self):
        """Carrega o estado anterior do monitor"""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.known_listings = state.get('known_listings', {})
                    logger.info(f"Estado carregado: {len(self.known_listings)} imóveis conhecidos")
            except Exception as e:
                logger.error(f"Erro ao carregar estado: {e}")
                self.known_listings = {}
    
    def save_state(self):
        """Salva o estado atual do monitor"""
        try:
            state = {
                'known_listings': self.known_listings,
                'last_update': datetime.now().isoformat()
            }
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
            logger.info("Estado salvo com sucesso")
        except Exception as e:
            logger.error(f"Erro ao salvar estado: {e}")
    
    def parse_properties_from_page(self, html_content: str) -> List[dict]:
        """Extrai informações de imóveis da página HTML"""
        properties = []
        seen_ids = set()  # Para evitar duplicatas
        
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Links de detalhe; o portal também repete os links dentro do cartão.
            property_links = soup.select('a.linkdetail[href*="-AP"]')
            logger.info(f"Links com classe linkdetail encontrados: {len(property_links)}")
            
            # Se o portal mudar a classe, ainda aceita os links cujo caminho tem ID de imóvel.
            if not property_links:
                property_links = soup.find_all('a', href=re.compile(r'-AP\d+'))
                logger.info(f"Links alternativos de imóvel encontrados: {len(property_links)}")
            
            for link in property_links:
                try:
                    href = link.get('href', '')
                    property_id_match = re.search(r'-(AP\d+)(?:$|[/?#])', href)
                    if not property_id_match:
                        continue
                    
                    property_id = property_id_match.group(1)
                    
                    # Evita duplicatas
                    if property_id in seen_ids:
                        continue
                    seen_ids.add(property_id)
                    
                    title = link.get('title', '') or link.get_text(' ', strip=True)
                    
                    container = link.find_parent('div', class_='property-item')
                    if not container:
                        container = link.find_parent('div', class_='blii') or link.find_parent('div')
                    
                    price = 0
                    price_elem = container.find(class_='item-price') if container else None
                    if price_elem:
                        price = self.parse_brl_money(price_elem.get_text(' ', strip=True)) or 0
                    if not price:
                        price_match = re.search(r'R\$\s*[\d.]+(?:,\d{1,2})?', title)
                        price = self.parse_brl_money(price_match.group(0)) if price_match else 0
                    
                    area_match = re.search(r'(\d+(?:[.,]\d+)?)\s*m²', title, re.IGNORECASE)
                    area = self.parse_number(area_match.group(1)) if area_match else None

                    # O portal usa "dormitórios" no plural; aceitar singular e plural.
                    bed_match = re.search(
                        r'(\d+)\s*(?:dormit[oó]rio|quarto)s?\b', title, re.IGNORECASE
                    )
                    bedrooms = int(bed_match.group(1)) if bed_match else None

                    neighborhood = ''
                    neighborhood_match = re.search(r'\s-\s([^\-]+?)\s-\sSantos/SP', title, re.IGNORECASE)
                    if neighborhood_match:
                        neighborhood = neighborhood_match.group(1).strip()
                    
                    if not neighborhood and container:
                        address_elem = container.find('p', class_='dia_chi')
                        if address_elem:
                            address_text = address_elem.get_text(' ', strip=True)
                            neighborhood = address_text.split(',')[0].strip()
                    
                    image_url = ''
                    img_elem = container.find('img') if container else None
                    if img_elem:
                        image_url = img_elem.get('data-src', '') or img_elem.get('src', '')
                        if image_url and not image_url.startswith('http'):
                            image_url = f"https://r3imoveis.com.br{image_url}"
                    
                    property_data = {
                        'id': property_id,
                        'url': urljoin('https://r3imoveis.com.br/', href),
                        'title': title,
                        'price': int(price) if price else 0,
                        'neighborhood': neighborhood,
                        'area': area,
                        'bedrooms': bedrooms,
                        'bathrooms': None,
                        'parking': None,
                        'image_url': image_url,
                        'discovered_at': datetime.now().isoformat()
                    }
                    
                    # Só adiciona se tiver informações básicas
                    if property_id and property_data['price'] > 0:
                        properties.append(property_data)
                        logger.info(f"Imóvel extraído: {property_id} - {neighborhood} - R$ {property_data['price']}")
                    else:
                        logger.debug(f"Imóvel ignorado - ID: {property_id}, Preço: {price}")
                    
                except Exception as e:
                    logger.error(f"Erro ao processar link individual: {e}", exc_info=True)
                    continue
            
            logger.info(f"Extraídos {len(properties)} imóveis da página")
            
        except Exception as e:
            logger.error(f"Erro ao processar página HTML: {e}")
        
        return properties

    @staticmethod
    def normalize_text(value: str) -> str:
        """Normaliza texto para comparações sem acentos ou diferenças de caixa."""
        value = unicodedata.normalize('NFKD', value or '')
        value = ''.join(char for char in value if not unicodedata.combining(char))
        return re.sub(r'\s+', ' ', value).strip().casefold()

    @staticmethod
    def parse_number(value: str):
        if value is None:
            return None
        try:
            if isinstance(value, (int, float)):
                return float(value)
            text = str(value).strip()
            if ',' in text:
                text = text.replace('.', '').replace(',', '.')
            elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', text):
                text = text.replace('.', '')
            return float(text)
        except (TypeError, ValueError):
            return None

    @classmethod
    def parse_brl_money(cls, value: str):
        if not value:
            return None
        match = re.search(r'\d[\d.]*?(?:,\d{1,2})?(?=\D*$)', str(value).strip())
        if not match:
            return None
        return cls.parse_number(match.group(0))
    
    def fetch_properties(self, page: int = 1) -> List[dict]:
        """Busca propriedades de uma página específica"""
        try:
            url = f"{self.base_url}?page={page}"
            logger.info(f"Buscando imóveis da página {page}: {url}")
            
            # Cria uma nova sessão para cada requisição
            scraper = cloudscraper.create_scraper(
                browser={
                    'browser': 'chrome',
                    'platform': 'windows',
                    'desktop': True
                }
            )
            
            response = scraper.get(url, timeout=30)
            response.raise_for_status()
            
            logger.info(f"Response status: {response.status_code}, Content length: {len(response.text)}")
            
            # Salva HTML para debug
            with open('monitor_debug.html', 'w', encoding='utf-8') as f:
                f.write(response.text)
            logger.info("HTML salvo em monitor_debug.html para debug")
            
            # Usa o novo método para extrair propriedades
            properties = self.parse_properties_from_page(response.text)
            
            logger.info(f"Encontrados {len(properties)} imóveis na página {page}")
            return properties
            
        except Exception as e:
            logger.error(f"Erro ao buscar propriedades da página {page}: {e}")
            return []

    def passes_search_filters(self, property_data: dict):
        """Valida localmente os filtros básicos antes de buscar a página do anúncio."""
        neighborhood = self.normalize_text(property_data.get('neighborhood', ''))
        if neighborhood not in self.allowed_neighborhoods:
            return False, 'bairro fora da lista permitida'

        title = self.normalize_text(property_data.get('title', ''))
        if 'apartamento' not in title:
            return False, 'tipo diferente de apartamento'

        price = self.parse_number(property_data.get('price'))
        if price is None or price <= 0 or price > self.max_price:
            return False, 'preço ausente ou acima do limite'

        area = self.parse_number(property_data.get('area'))
        if area is None or area < self.min_area:
            return False, 'área ausente ou abaixo do mínimo'

        bedrooms = self.parse_number(property_data.get('bedrooms'))
        if bedrooms is None or bedrooms < self.min_bedrooms or bedrooms > self.max_bedrooms:
            return False, 'quantidade de quartos diferente do filtro'

        return True, 'filtros básicos aprovados'

    def fetch_property_details(self, property_data: dict) -> bool:
        """Busca a ficha do anúncio para validar vaga, condomínio e características."""
        try:
            scraper = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True}
            )
            response = scraper.get(property_data['url'], timeout=30)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            summary = soup.select_one('.property-summary')
            summary_text = ' '.join(summary.get_text(' ', strip=True).split()) if summary else ''
            features = soup.select_one('.property-features2')
            features_text = ' '.join(features.get_text(' ', strip=True).split()) if features else ''
            full_page_text = ' '.join(soup.get_text(' ', strip=True).split())

            area_match = re.search(r'Área útil:\s*([\d.,]+)\s*m²', summary_text, re.IGNORECASE)
            bedrooms_match = re.search(r'Dormitórios:\s*(\d+)', summary_text, re.IGNORECASE)
            parking_match = re.search(r'Vagas:\s*(\d+)', summary_text, re.IGNORECASE)
            price_match = re.search(r'R\$\s*([\d.]+(?:,\d{1,2})?)', summary_text)

            if area_match:
                property_data['area'] = self.parse_number(area_match.group(1))
            if bedrooms_match:
                property_data['bedrooms'] = int(bedrooms_match.group(1))
            if parking_match:
                property_data['parking'] = int(parking_match.group(1))
            if (property_data.get('parking', 0) < 1
                    and re.search(r'\bvaga\s+coletiva\b', full_page_text, re.IGNORECASE)):
                property_data['parking'] = 1
            if price_match:
                detail_price = self.parse_brl_money(price_match.group(0))
                if detail_price:
                    property_data['price'] = int(detail_price)

            # Na ficha do R3, o valor aparece imediatamente antes do rótulo COND.
            condo_label = soup.select_one('.property-condominio-label')
            condo_container = condo_label.parent if condo_label and condo_label.parent else condo_label
            condo_text = ' '.join(condo_container.get_text(' ', strip=True).split()) if condo_container else summary_text
            condo_match = re.search(
                r'R\$\s*([\d.]+(?:,\d{1,2})?)\s*(?:COND[.]|CONDOM[IÍ]NIO)',
                condo_text,
                re.IGNORECASE
            )
            if condo_match:
                property_data['condo_fee'] = self.parse_brl_money(condo_match.group(1))
            else:
                property_data['condo_fee'] = None

            normalized_features = self.normalize_text(features_text)
            elevator_match = re.search(
                r'Qtd[.]?\s*Elevador(?:es)?\s*:\s*(\d+)', full_page_text, re.IGNORECASE
            )
            if elevator_match:
                elevator_count = int(elevator_match.group(1))
                property_data['elevator_count'] = elevator_count
                property_data['has_elevator'] = elevator_count > 0
            else:
                property_data['elevator_count'] = None
                explicitly_no_elevator = bool(re.search(
                    r'\b(?:sem|nao possui|nao tem)\s+elevador(?:es)?\b', normalized_features
                ))
                explicitly_has_elevator = bool(re.search(
                    r'\b(?:com|possui|tem)\s+elevador(?:es)?\b|\belevador(?:es)?\s+(?:social|de servico)\b',
                    normalized_features
                ))
                property_data['has_elevator'] = explicitly_has_elevator and not explicitly_no_elevator

            # Procura restrições em descrição/ficha e endereço, sem confundir "perto de avenidas"
            # com imóvel localizado em uma avenida.
            combined_text = self.normalize_text(
                f"{property_data.get('title', '')} {features_text}"
            )
            street_parts = [
                element.get_text(' ', strip=True)
                for element in soup.select('address, [itemprop="streetAddress"], .property-address, .addresshouse')
            ]
            street_text = self.normalize_text(' '.join(street_parts))
            avenue_in_address = bool(re.search(r'\b(?:avenida|av\.?)\s+[a-z0-9]', street_text))
            avenue_in_description = bool(re.search(
                r'\b(?:localizado|localizada|situado|situada|fica)\s+(?:na|em|a)\s+(?:avenida|av\.?)\s+[a-z0-9]',
                combined_text
            ))
            property_data['is_on_avenue'] = avenue_in_address or avenue_in_description
            property_data['is_ground_floor'] = bool(
                re.search(r'\bterreo\b|\b(?:andar|pavimento)\s*:?\s*0(?:\b|o\b)', combined_text)
            )
            property_data['has_garden'] = bool(re.search(r'\b(?:garden|quintal)\b', combined_text))
            property_data['details_checked'] = True
            return True

        except Exception as e:
            logger.warning(f"Não foi possível validar a ficha de {property_data.get('id')}: {e}")
            return False

    def passes_full_filters(self, property_data: dict):
        """Filtro final, aplicado antes de qualquer notificação."""
        passes_basic, reason = self.passes_search_filters(property_data)
        if not passes_basic:
            return False, reason

        parking = self.parse_number(property_data.get('parking'))
        if parking is None or parking < self.min_parking:
            return False, 'sem vaga confirmada'

        if property_data.get('is_ground_floor') is True:
            return False, 'térreo'
        if property_data.get('has_garden') is True:
            return False, 'garden/quintal'

        price = self.parse_number(property_data.get('price'))
        condo_fee = self.parse_number(property_data.get('condo_fee'))
        neighborhood = self.normalize_text(property_data.get('neighborhood', ''))
        for profile in self.purchase_profiles:
            if neighborhood not in profile['neighborhoods']:
                continue
            if price is None or price > profile['max_price']:
                continue
            if condo_fee is not None and condo_fee > profile['max_condo_fee']:
                continue
            if profile['require_elevator'] and property_data.get('has_elevator') is not True:
                continue
            if profile['exclude_avenue'] and property_data.get('is_on_avenue') is True:
                continue
            return True, f"filtros do perfil {profile['name']} aprovados"

        return False, 'nenhum perfil de busca foi atendido'
    
    def is_new_listing(self, property_data: dict) -> bool:
        """Verifica se é um novo anúncio"""
        property_id = property_data['id']
        
        if property_id in self.known_listings:
            # Verifica se o preço mudou
            old_price = self.known_listings[property_id].get('price', 0)
            new_price = property_data.get('price', 0)
            
            if old_price != new_price and old_price > 0 and new_price > 0:
                logger.info(f"Preço alterado para {property_id}: {old_price} -> {new_price}")
                return True
            return False
        
        return True
    
    def send_telegram_notification(self, property_data: dict, is_price_update: bool = False):
        """Envia notificação via Telegram"""
        try:
            if is_price_update:
                old_price = self.known_listings[property_data['id']].get('price', 0)
                message = f"🔔 *PREÇO ALTERADO!*\n\n"
                message += f"De: R$ {old_price:,.2f}\n"
                message += f"Para: R$ {property_data['price']:,.2f}\n\n"
            else:
                message = f"🏠 *NOVO IMÓVEL ENCONTRADO!*\n\n"
            
            message += f"📍 *Bairro:* {property_data.get('neighborhood', 'N/A')}\n"
            message += f"💰 *Preço:* R$ {property_data.get('price', 0):,.2f}\n"
            if property_data.get('condo_fee') is not None:
                condo_text = f"R$ {property_data['condo_fee']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                message += f"🏢 *Condomínio:* {condo_text}\n"
            else:
                message += "🏢 *Condomínio:* Não informado\n"
            message += f"📐 *Área:* {property_data.get('area', 0)} m²\n"
            message += f"🛏 *Quartos:* {property_data.get('bedrooms', 0)}\n"
            message += f"🚿 *Banheiros:* {property_data.get('bathrooms', 0)}\n"
            message += f"🚗 *Vagas:* {property_data.get('parking', 0)}\n"
            message += f"🆔 *ID:* {property_data.get('id', 'N/A')}\n\n"
            message += f"🔗 [Ver detalhes]({property_data.get('url', '')})"
            
            # Envia mensagem
            telegram_url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': False
            }
            
            response = requests.post(telegram_url, json=payload, timeout=30)
            response.raise_for_status()
            
            # Se houver imagem, tenta enviar
            if property_data.get('image_url'):
                try:
                    photo_url = f"https://api.telegram.org/bot{self.telegram_token}/sendPhoto"
                    photo_payload = {
                        'chat_id': self.telegram_chat_id,
                        'photo': property_data['image_url'],
                        'caption': f"📸 {property_data.get('title', 'Imagem do imóvel')[:200]}"
                    }
                    requests.post(photo_url, json=photo_payload, timeout=30)
                except Exception as e:
                    logger.warning(f"Não foi possível enviar a imagem: {e}")
            
            logger.info(f"Notificação enviada para o imóvel {property_data['id']}")
            
        except Exception as e:
            logger.error(f"Erro ao enviar notificação: {e}")
    
    def monitor_once(self, send_notifications: bool = True):
        """Executa uma verificação completa"""
        try:
            logger.info("Iniciando verificação de novos imóveis...")
            logger.info(
                "Filtros locais: bairros permitidos, 2 quartos, 1+ vaga, área >= 70m², "
                "perfil principal até R$ 530.000 / R$ 1.100 de condomínio e perfil paralelo "
                "até R$ 426.000 / R$ 800 de condomínio"
            )
            logger.info(f"Buscando até {self.max_pages_to_check} páginas ou até encontrar {self.stop_after_known_pages} páginas consecutivas sem novidades")
            
            all_properties = []
            new_count = 0
            consecutive_known_pages = 0
            
            # Busca páginas de forma inteligente
            for page in range(1, self.max_pages_to_check + 1):
                properties = self.fetch_properties(page)
                
                if not properties:
                    logger.info(f"Página {page} vazia. Parando a busca.")
                    break
                
                # Verifica quantos imóveis são novos nesta página
                new_in_page = 0
                for prop in properties:
                    if prop['id'] not in self.known_listings:
                        new_in_page += 1
                
                all_properties.extend(properties)
                
                logger.info(f"Página {page}: {len(properties)} imóveis encontrados, {new_in_page} novos")
                
                # Se não houver novos imóveis na página
                if new_in_page == 0:
                    consecutive_known_pages += 1
                    if consecutive_known_pages >= self.stop_after_known_pages:
                        logger.info(f"Encontradas {consecutive_known_pages} páginas consecutivas sem novidades. Parando a busca.")
                        break
                else:
                    consecutive_known_pages = 0  # Reseta o contador se encontrar novos
                
                time.sleep(2)  # Aguarda entre requisições
            
            # A ficha é consultada somente para anúncios novos que passam pelos filtros básicos.
            # Assim, os anúncios antigos do estado não são reenviados após a atualização.
            for property_data in all_properties:
                if not property_data or not property_data.get('id'):
                    continue

                property_id = property_data['id']
                existing = self.known_listings.get(property_id)
                if existing is not None:
                    # Preserva os campos detalhados verificados anteriormente; o cartão da busca
                    # não contém condomínio/elevador e não pode apagá-los.
                    updated = dict(existing)
                    for key in ('title', 'url', 'price', 'neighborhood', 'area', 'bedrooms', 'image_url'):
                        value = property_data.get(key)
                        if value not in (None, ''):
                            updated[key] = value
                    updated['last_seen_at'] = datetime.now().isoformat()

                    # Estado legado não tem confirmação dos novos critérios; ele é mantido como
                    # conhecido, sem gerar notificações de transição em massa.
                    if existing.get('filters_verified') is True:
                        eligible, reason = self.passes_full_filters(updated)
                        if eligible and self.is_new_listing(updated):
                            logger.info(
                                f"Preço alterado: {property_id} - {updated.get('neighborhood')} "
                                f"- R$ {updated.get('price')}"
                            )
                            if send_notifications:
                                self.send_telegram_notification(updated, is_price_update=True)
                                new_count += 1
                                time.sleep(1)
                            else:
                                logger.info("Linha de base: atualização conhecida registrada sem notificação")
                        elif not eligible:
                            logger.info(f"Imóvel {property_id} deixou de atender aos filtros: {reason}")

                    self.known_listings[property_id] = updated
                    continue

                passes_basic, reason = self.passes_search_filters(property_data)
                if not passes_basic:
                    logger.info(f"Imóvel {property_id} ignorado: {reason}")
                    property_data['filters_verified'] = False
                    self.known_listings[property_id] = property_data
                    continue

                if not self.fetch_property_details(property_data):
                    # Não registra falha transitória: o anúncio será tentado novamente na próxima
                    # varredura, mas não haverá alerta sem confirmação da ficha completa.
                    continue

                eligible, reason = self.passes_full_filters(property_data)
                property_data['filters_verified'] = eligible
                if eligible:
                    logger.info(
                        f"Novo imóvel aprovado: {property_id} - {property_data.get('neighborhood')} "
                        f"- R$ {property_data.get('price')} - condomínio R$ {property_data.get('condo_fee')}"
                    )
                    if send_notifications:
                        self.send_telegram_notification(property_data, is_price_update=False)
                        new_count += 1
                        time.sleep(1)
                    else:
                        logger.info("Linha de base: anúncio atual registrado sem notificação")
                else:
                    logger.info(f"Imóvel {property_id} ignorado pelos filtros completos: {reason}")

                # Mesmo anúncios reprovados ficam conhecidos para não reavaliar nem alertar a cada ciclo.
                self.known_listings[property_id] = property_data
            
            # Salva o estado
            self.save_state()
            
            logger.info(f"Verificação concluída. {new_count} novos imóveis/atualizações encontrados. Total monitorado: {len(self.known_listings)}")
            
        except Exception as e:
            logger.error(f"Erro durante monitoramento: {e}")
    
    def run(self, interval_minutes: int = 10):
        """Executa o monitor em loop contínuo"""
        logger.info(f"Monitor iniciado. Verificando a cada {interval_minutes} minutos...")
        logger.info(f"Área mínima configurada: {self.min_area}m²")

        if os.environ.get('MONITOR_BASELINE_ONLY') == '1':
            logger.info("Executando somente a linha de base; notificações desativadas")
            self.monitor_once(send_notifications=False)
            return
        
        # Executa primeira verificação
        self.monitor_once()
        
        # Loop principal
        while True:
            try:
                time.sleep(interval_minutes * 60)
                self.monitor_once()
            except KeyboardInterrupt:
                logger.info("Monitor interrompido pelo usuário")
                break
            except Exception as e:
                logger.error(f"Erro no loop principal: {e}")
                time.sleep(60)  # Aguarda 1 minuto em caso de erro


def main():
    """Função principal."""
    telegram_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    if not telegram_token or not telegram_chat_id:
        logger.critical("Variáveis TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID ausentes no ambiente.")
        raise SystemExit(1)

    check_interval = 10
    monitor = R3ImoveisMonitor(telegram_token, telegram_chat_id)
    try:
        monitor.run(interval_minutes=check_interval)
    except KeyboardInterrupt:
        logger.info("Monitor finalizado")


if __name__ == "__main__":
    main()
