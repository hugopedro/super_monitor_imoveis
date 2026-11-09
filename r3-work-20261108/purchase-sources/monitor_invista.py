#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Monitor de Imóveis - Invistaii.com.br
Monitora novos imóveis e envia notificações via Telegram
"""

import requests
import json
import time
import logging
import html
from datetime import datetime
from typing import Set, List, Dict
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urljoin, urlparse

def load_env_file():
    """Carrega variáveis de ambiente do arquivo .env"""
    env_file = Path('.env')
    if env_file.exists():
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

# Carrega variáveis de ambiente do arquivo .env
load_env_file()

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('monitor_imoveis.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


class MonitorImoveis:
    """Classe para monitorar novos imóveis no site invistaii.com.br"""
    
    def __init__(self, telegram_bot_token: str = None, telegram_chat_id: str = None):
        """
        Inicializa o monitor
        
        Args:
            telegram_bot_token: Token do bot do Telegram
            telegram_chat_id: ID do chat para receber notificações
        """
        self.api_url = "https://www.invistaii.com.br/retornar-imoveis-disponiveis"
        self.api_parametros_url = "https://www.invistaii.com.br/retornar-parametros-gerais"
        self.neighborhoods_a = {'aparecida', 'boqueirao', 'embare', 'gonzaga', 'pompeia'}
        self.neighborhoods_b = self.neighborhoods_a | {'campo grande', 'marape', 'jose menino'}
        self.purchase_profiles = [
            {'name': 'principal', 'neighborhoods': self.neighborhoods_a, 'max_price': 530000,
             'max_condo': 1100, 'require_elevator': True, 'exclude_avenue': True},
            {'name': 'paralelo', 'neighborhoods': self.neighborhoods_b, 'max_price': 426000,
             'max_condo': 800, 'require_elevator': False, 'exclude_avenue': False},
        ]
        self.telegram_bot_token = telegram_bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = telegram_chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.codigos_conhecidos: Set[int] = set()
        self.db_file = Path('imoveis_conhecidos.json')
        self.parametros_url = None
        self.bairros_completos = {}  # Cache dos dados completos dos bairros
        self.tipos_completos = {}    # Cache dos dados completos dos tipos
        
        # Carrega códigos já conhecidos
        self._carregar_codigos_conhecidos()
        
        # A API legada foi descontinuada; a busca usa a página pública atual.
    
    def configurar_filtros(self, parametros: Dict = None):
        """
        Configura os filtros de busca
        
        Args:
            parametros: Dicionário com os parâmetros de filtro da busca
        """
        if parametros:
            self.parametros_url = parametros
        else:
            # Filtros padrão baseados no exemplo fornecido
            self.parametros_url = {
                "finalidade": ["venda"],
                "tipos": ["apartamento"],
                "cidades": ["santos"],
                "bairros": [
                 'aparecida',
                 'boqueirao',
                 'embare',
                 'gonzaga',
                 'pompeia',
                 'campo-grande',
                 'marape',
                 'jose-menino',
                           ],
                "condominio": ["todos-os-condominios"],
                "param": ["2-quartos"],
                "area": ["70", 0],
                "valor": [
                             0,
                              '530.000,00',
                         ]
            }
        
        logger.info(f"Filtros configurados: {json.dumps(self.parametros_url, indent=2, ensure_ascii=False)}")

    @staticmethod
    def _normalizar_texto(value) -> str:
        text = unicodedata.normalize('NFKD', str(value or '').lower())
        text = ''.join(char for char in text if not unicodedata.combining(char))
        return ' '.join(re.sub(r'[^\w\s]', ' ', text).split())

    @staticmethod
    def _numero(value):
        if isinstance(value, list):
            value = value[0] if value else None
        if isinstance(value, (int, float)):
            return float(value)
        if value is None:
            return None
        raw = re.sub(r'[^\d,.-]', '', str(value).strip())
        if not raw:
            return None
        if ',' in raw:
            raw = raw.replace('.', '').replace(',', '.')
        elif re.fullmatch(r'\d{1,3}(?:\.\d{3})+', raw):
            raw = raw.replace('.', '')
        match = re.search(r'-?\d+(?:\.\d+)?', raw)
        return float(match.group(0)) if match else None

    def corresponde_a_perfil(self, imovel: Dict) -> bool:
        bairro = self._normalizar_texto(imovel.get('bairro'))
        preco = self._numero(imovel.get('valor'))
        condominio = self._numero(imovel.get('valorcondominio'))
        area = self._numero(imovel.get('areaprincipal'))
        quartos = self._numero(imovel.get('numeroquartos'))
        vagas_value = imovel.get('numerovagas')
        vagas = self._numero(vagas_value)
        andar_text = self._normalizar_texto(imovel.get('andar'))
        andar = self._numero(imovel.get('andar'))
        text = self._normalizar_texto(' '.join(str(imovel.get(key, '') or '') for key in (
            'titulo', 'descricao', 'tipo', 'endereco', 'logradouro', 'complemento',
            'numerovagas', 'numeroelevador', 'elevador'
        )))
        has_collective_parking = 'coletiva' in text or 'coletivo' in text
        if (bairro == '' or preco is None or area is None or quartos is None
                or area < 70 or quartos != 2 or (vagas is None and not has_collective_parking)
                or (vagas is not None and vagas < 1 and not has_collective_parking)
                or andar == 0 or 'terreo' in andar_text or 'terreo' in text
                or 'garden' in text or 'quintal' in text):
            return False

        elevator_value = self._numero(imovel.get('numeroelevador'))
        has_elevator = elevator_value is not None and elevator_value > 0
        if not has_elevator:
            has_elevator = bool(re.search(r'\b(?:elevador|elevadores)\b', text)
                                and not re.search(r'\b(?:sem|nao possui|nao tem)\s+elevador', text))
        street = self._normalizar_texto(' '.join(str(imovel.get(key, '') or '') for key in (
            'endereco', 'logradouro'
        )))
        is_avenue = bool(imovel.get('is_on_avenue')) or bool(re.search(r'\b(?:avenida|av)\b', street))

        for profile in self.purchase_profiles:
            if (bairro in profile['neighborhoods']
                    and preco <= profile['max_price']
                    and (condominio is None or condominio <= profile['max_condo'])
                    and (not profile['require_elevator'] or has_elevator)
                    and (not profile['exclude_avenue'] or not is_avenue)):
                return True
        return False
    
    def _carregar_parametros_gerais(self):
        """Carrega parâmetros gerais da API (bairros, tipos, etc.)"""
        try:
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'
            }
            
            response = requests.post(self.api_parametros_url, json={}, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            # Indexa bairros por nome URL
            for bairro in data.get('bairros', []):
                nome_url = bairro.get('nomeUrl', '')
                if nome_url:
                    self.bairros_completos[nome_url] = bairro
            
            # Indexa tipos por nome URL  
            for tipo in data.get('tipos', []):
                nome_url = tipo.get('url_amigavel', '')
                if nome_url:
                    self.tipos_completos[nome_url] = tipo
            
            logger.info(f"Carregados {len(self.bairros_completos)} bairros e {len(self.tipos_completos)} tipos da API")
            
        except Exception as e:
            logger.error(f"Erro ao carregar parâmetros gerais: {e}")
            logger.info("Continuando com dados padrão...")
    
    def _carregar_codigos_conhecidos(self):
        """Carrega os códigos de imóveis já conhecidos do arquivo"""
        if self.db_file.exists():
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.codigos_conhecidos = set(data.get('codigos', []))
                    logger.info(f"Carregados {len(self.codigos_conhecidos)} imóveis conhecidos")
            except Exception as e:
                logger.error(f"Erro ao carregar códigos conhecidos: {e}")
                self.codigos_conhecidos = set()
        else:
            logger.info("Arquivo de imóveis conhecidos não existe. Será criado.")
    
    def _salvar_codigos_conhecidos(self):
        """Salva os códigos de imóveis conhecidos no arquivo"""
        try:
            data = {
                'codigos': list(self.codigos_conhecidos),
                'ultima_atualizacao': datetime.now().isoformat()
            }
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.debug(f"Salvos {len(self.codigos_conhecidos)} códigos conhecidos")
        except Exception as e:
            logger.error(f"Erro ao salvar códigos conhecidos: {e}")
    
    def buscar_imoveis_site(self) -> List[Dict]:
        """Busca a página pública atual da Invista e extrai os cartões de apartamentos."""
        bairros = [
            'aparecida', 'boqueirao', 'embare', 'gonzaga', 'pompeia',
            'campo-grande', 'marape', 'jose-menino'
        ]
        params = [('tipo[]', 'apartamento')]
        params.extend(('bairro[]', bairro) for bairro in bairros)
        params.extend([
            ('quartos', '2'),       # O site trata este campo como mínimo; validamos 2 exatos abaixo.
            ('valor_max', '530000'),
            ('area_min', '70'),
        ])
        headers = {
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Referer': 'https://invistaii.com.br/imovel/comprar/',
        }
        try:
            response = requests.get(
                'https://invistaii.com.br/imovel/comprar/',
                params=params,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            found = {}
            hrefs = re.findall(r'href=[\"\']([^\"\']*/imovel/[^\"\']+/\d+/?)[\"\']', response.text, re.IGNORECASE)
            for href in hrefs:
                url = urljoin('https://invistaii.com.br/', html.unescape(href))
                parsed = urlparse(url)
                if parsed.netloc.lower() != 'invistaii.com.br':
                    continue
                code_match = re.search(r'/(\d+)/?$', parsed.path)
                segments = parsed.path.rstrip('/').split('/')
                if not code_match or len(segments) < 3:
                    continue
                slug = segments[-2]
                code = code_match.group(1)
                area_match = re.search(r'-(\d+)m2(?:-|$)', slug)
                bedrooms_match = re.search(r'com-(\d+)-dormitorios?', slug)
                neighborhood_match = re.search(r'no-bairro-(.+?)-com-', slug)
                found[code] = {
                    'codigo': code,
                    'titulo': slug.replace('-', ' ').title(),
                    'bairro': neighborhood_match.group(1).replace('-', ' ') if neighborhood_match else '',
                    'cidade': 'Santos',
                    'tipo': 'apartamento',
                    'areaprincipal': area_match.group(1) if area_match else None,
                    'numeroquartos': bedrooms_match.group(1) if bedrooms_match else None,
                    'numerovagas': None,
                    'valor': None,
                    'valorcondominio': None,
                    'url': url,
                }
            logger.info(f"Invista: {len(found)} anúncios encontrados na busca pública atual")
            return list(found.values())
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao consultar a busca pública da Invista: {e}")
            return []

    def buscar_detalhes_imovel(self, imovel: Dict) -> bool:
        """Completa os dados do cartão usando a página pública do anúncio."""
        try:
            response = requests.get(
                imovel['url'],
                headers={'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0 Safari/537.36'},
                timeout=30,
            )
            response.raise_for_status()
            page_html = html.unescape(response.text)
            plain = ' '.join(re.sub(r'<[^>]+>', ' ', page_html).split())
            normalized = self._normalizar_texto(plain)

            price_match = re.search(r'R\$\s*([\d.]+(?:,\d{1,2})?)', plain)
            condo_match = re.search(r'Condom.nio\s*R\$\s*([\d.]+(?:,\d{1,2})?)', plain, re.IGNORECASE)
            parking_match = re.search(r'(\d+)\s+vagas?\b', plain, re.IGNORECASE)
            if not parking_match:
                parking_match = re.search(r'Vagas\s*(\d+)\b', plain, re.IGNORECASE)
            collective_parking = bool(re.search(r'vaga\s+coletiva', normalized))
            if price_match:
                imovel['valor'] = price_match.group(1)
            if condo_match:
                imovel['valorcondominio'] = condo_match.group(1)
            if parking_match:
                imovel['numerovagas'] = parking_match.group(1)
            elif collective_parking:
                imovel['numerovagas'] = '1 coletiva'
            imovel['andar'] = 0 if re.search(r'\bterreo\b|\b(?:andar|pavimento)\s*0\b', normalized) else None
            has_elevator = bool(re.search(r'\belevador(?:es)?\b', normalized))
            explicitly_no_elevator = bool(re.search(r'\bsem\s+elevador(?:es)?\b', normalized))
            imovel['numeroelevador'] = 1 if has_elevator and not explicitly_no_elevator else 0
            imovel['descricao'] = plain
            imovel['is_ground_floor'] = imovel['andar'] == 0
            imovel['has_garden'] = bool(re.search(r'\bgarden\b|\bquintal\b', normalized))
            imovel['is_on_avenue'] = bool(re.search(r'\b(?:avenida|av)\s+[a-z0-9]', normalized))
            return True
        except requests.exceptions.RequestException as e:
            logger.warning(f"Não foi possível consultar os detalhes do anúncio {imovel.get('codigo')}: {e}")
            return False

    def buscar_imoveis(self) -> List[Dict]:
        """Usa a busca pública atual da Invista."""
        return self.buscar_imoveis_site()
    def detectar_novos_imoveis(self, imoveis: List[Dict]) -> List[Dict]:
        """
        Detecta imóveis novos comparando com os códigos conhecidos
        
        Args:
            imoveis: Lista de imóveis da API
            
        Returns:
            Lista de imóveis novos
        """
        novos = []
        
        for imovel in imoveis:
            codigo = imovel.get('codigo')
            if codigo and codigo not in self.codigos_conhecidos:
                novos.append(imovel)
                self.codigos_conhecidos.add(codigo)
        
        if novos:
            logger.info(f"Detectados {len(novos)} novos imóveis!")
            self._salvar_codigos_conhecidos()
        
        return novos
    
    def formatar_mensagem_imovel(self, imovel: Dict) -> str:
        """
        Formata os dados do imóvel para a mensagem de notificação
        
        Args:
            imovel: Dicionário com dados do imóvel
            
        Returns:
            Mensagem formatada
        """
        titulo = imovel.get('titulo', 'Sem título')
        codigo = imovel.get('codigo', 'N/A')
        valor = imovel.get('valor', 'Não informado')
        valor_anterior = imovel.get('valoranterior', 'R$ 0,00')
        bairro = imovel.get('bairro', 'N/A')
        cidade = imovel.get('cidade', 'N/A')
        area = imovel.get('areaprincipal', 'N/A')
        quartos = imovel.get('numeroquartos', 'N/A')
        vagas = imovel.get('numerovagas', 'N/A')
        condominio = imovel.get('valorcondominio') or 'Não informado'
        
        # Verifica se teve desconto
        desconto_info = ""
        if valor_anterior and valor_anterior != "R$ 0,00":
            desconto_info = f"\n💰 Valor anterior: {valor_anterior}"
        
        mensagem = f"""🏠 NOVO IMÓVEL DISPONÍVEL!

📋 Código: {codigo}
📍 {titulo}

🏘️ Localização: {bairro} - {cidade}
💵 Valor: {valor}{desconto_info}
🏢 Condomínio: {condominio}

📐 Área: {area} m²
🛏️ Quartos: {quartos}
🚗 Vagas: {vagas}

🔗 Ver detalhes: https://www.invistaii.com.br/imovel/{codigo}
"""
        
        return mensagem.strip()
    
    def enviar_notificacao_telegram(self, mensagem: str, foto_url: str = None):
        """
        Envia notificação via Telegram
        
        Args:
            mensagem: Texto da mensagem
            foto_url: URL da foto do imóvel (opcional)
        """
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.warning("Credenciais do Telegram não configuradas. Notificação não enviada.")
            return
        
        try:
            base_url = f"https://api.telegram.org/bot{self.telegram_bot_token}"
            
            # Envia foto se disponível
            if foto_url:
                url = f"{base_url}/sendPhoto"
                payload = {
                    'chat_id': self.telegram_chat_id,
                    'photo': foto_url,
                    'caption': mensagem
                }
            else:
                url = f"{base_url}/sendMessage"
                payload = {
                    'chat_id': self.telegram_chat_id,
                    'text': mensagem
                }
            
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info("Notificação enviada com sucesso!")
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro ao enviar notificação: {e}")
    
    def notificar_novos_imoveis(self, novos_imoveis: List[Dict]):
        """
        Envia notificações para cada imóvel novo
        
        Args:
            novos_imoveis: Lista de imóveis novos
        """
        for imovel in novos_imoveis:
            if not self.corresponde_a_perfil(imovel):
                logger.info(f"Imóvel {imovel.get('codigo')} ignorado: não atende aos perfis ativos")
                continue
            mensagem = self.formatar_mensagem_imovel(imovel)
            foto_url = imovel.get('urlfotoprincipalp')
            # Exibe no console
            print("\n" + "="*60)
            print(mensagem)
            print("="*60 + "\n")
            # Envia para o Telegram
            self.enviar_notificacao_telegram(mensagem, foto_url)
            # Pequeno delay entre mensagens para não sobrecarregar a API do Telegram
            time.sleep(1)
    
    def iniciar_monitoramento(self, intervalo_minutos: int = 15):
        """
        Inicia o monitoramento contínuo
        
        Args:
            intervalo_minutos: Intervalo entre verificações em minutos
        """
        logger.info(f"Iniciando monitoramento (verificação a cada {intervalo_minutos} minutos)")
        logger.info("Pressione Ctrl+C para parar")
        
        # Primeira execução imediata
        self.executar_verificacao(primeira_execucao=True)
        if os.environ.get('MONITOR_BASELINE_ONLY') == '1':
            logger.info("Linha de base concluída; encerrando execução única")
            return
        
        try:
            while True:
                time.sleep(intervalo_minutos * 60)
                self.executar_verificacao()
                
        except KeyboardInterrupt:
            logger.info("\nMonitoramento interrompido pelo usuário")
        except Exception as e:
            logger.error(f"Erro no monitoramento: {e}")
    
    def executar_verificacao(self, primeira_execucao: bool = False):
        """
        Executa uma verificação de novos imóveis
        
        Args:
            primeira_execucao: Se é a primeira execução (não notifica)
        """
        logger.info(f"Verificando novos imóveis... ({datetime.now().strftime('%d/%m/%Y %H:%M:%S')})")
        
        imoveis = self.buscar_imoveis()
        
        if not imoveis:
            logger.warning("Nenhum imóvel retornado na busca")
            return

        imoveis_elegiveis = []
        for imovel in imoveis:
            codigo = imovel.get('codigo')
            if not codigo or codigo in self.codigos_conhecidos:
                continue
            if not self.buscar_detalhes_imovel(imovel):
                continue
            if self.corresponde_a_perfil(imovel):
                imoveis_elegiveis.append(imovel)
            else:
                # Registra também os anúncios novos que já foram avaliados,
                # para não baixar repetidamente o mesmo detalhe em cada ciclo.
                self.codigos_conhecidos.add(codigo)
        self._salvar_codigos_conhecidos()
        logger.info(f"Imóveis que atendem a um dos perfis: {len(imoveis_elegiveis)} de {len(imoveis)}")
        
        novos = self.detectar_novos_imoveis(imoveis_elegiveis)
        
        if novos and not primeira_execucao:
            self.notificar_novos_imoveis(novos)
        elif novos and primeira_execucao:
            logger.info(f"Primeira execução: {len(novos)} imóveis carregados (notificações não enviadas)")
        else:
            logger.info("Nenhum imóvel novo detectado")


def main():
    """Função principal"""
    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║     Monitor de Imóveis - Invistaii.com.br            ║
    ║     Notificações via Telegram                         ║
    ╚═══════════════════════════════════════════════════════╝
    """)
    
    # Cria instância do monitor
    monitor = MonitorImoveis()
    
    # Configura filtros (usa os padrões do exemplo)
    monitor.configurar_filtros()
    
    # Inicia monitoramento (verificação a cada 15 minutos)
    monitor.iniciar_monitoramento(intervalo_minutos=15)


if __name__ == "__main__":
    main()
