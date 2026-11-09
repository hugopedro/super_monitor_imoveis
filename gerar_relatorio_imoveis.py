import html
import json
import calendar
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TODAY = date.today()
cutoff_month = TODAY.month - 5
cutoff_year = TODAY.year
while cutoff_month <= 0:
    cutoff_month += 12
    cutoff_year -= 1
CUTOFF = date(cutoff_year, cutoff_month, min(TODAY.day, calendar.monthrange(cutoff_year, cutoff_month)[1]))
LABEL = {
    'vivareal': 'Viva Real', 'zap': 'Zap Imóveis', 'r3': 'R3 Imóveis', 'invista': 'Invista',
    'chaves': 'Chaves na Mão', 'roda': 'Roda Imóveis', 'rhema': 'Rhema Imóveis',
    'multiverso': 'Multiverso Imóveis', 'proprietario': 'Proprietário Direto',
    'chave_santos': 'Chave Santos Imóveis', 'maneco': 'Maneco Imóveis',
    'torres_prime': 'Torres Prime', 'myx': 'Myx Imóveis', 'raiz': 'Raiz Imobiliária',
    'mape': 'Mapê Negócios Imobiliários', 'listagem': 'Listagem Imobiliária',
    'expoente': 'Expoente Imobiliária', 'pousada': 'Imobiliária Pousada',
    'rochedo': 'Rochedo Imóveis', 'lopes_conceito': 'Lopes Conceito',
    'prime_trade': 'Prime Trade Imóveis', 'balduino': 'Balduino Imóveis',
    'cerejo': 'Cerejo Imóveis', 'casabella': 'Casabella Imóveis',
    'familia': 'Família Imóveis', 'viver_em_santos': 'Viver em Santos Imóveis',
    'gavea': 'Gávea Imobiliária', 'fabricio': 'Fabrício Corretor de Imóveis',
    'bw': 'BW Imóveis', 'remax_evoke_iv': 'RE/MAX Evoke IV',
}
LABEL_426 = {k: LABEL[k] for k in ('vivareal', 'zap', 'r3', 'invista', 'chaves', 'roda', 'rhema', 'multiverso', 'proprietario')}

def esc(value): return html.escape(str(value or ''), quote=True)
def money(value): return 'R$ ' + f'{value:,.0f}'.replace(',', '.')
def date_value(raw):
    try:
        if not raw: return None
        try:
            value = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        except ValueError:
            value = None
            for fmt in ('%d/%m/%Y %H:%M:%S', '%d/%m/%Y %H:%M', '%d/%m/%Y'):
                try:
                    value = datetime.strptime(str(raw).strip(), fmt)
                    break
                except ValueError:
                    continue
            if value is None:
                return None
        if value.tzinfo: value = value.astimezone(timezone(timedelta(hours=-3)))
        return value.date()
    except (ValueError, TypeError, AttributeError):
        return None

def row_score(item):
    condo = item.get('condominio')
    return (item['preco'] + 60 * condo) / item['area'] if condo is not None else None

def section_sort(item):
    score = row_score(item)
    return (score is None, score if score is not None else item['preco'] / item['area'])

def render_card(item, index):
    score = row_score(item)
    fee = money(item['condominio']) + '/mês' if score is not None else 'Não informado ou não confirmado'
    rank = money(score) + '/m²' if score is not None else 'Não comparável: condomínio não confirmado'
    stamp = date_value(item.get('data_publicacao'))
    published = stamp.strftime('%d/%m/%Y') if stamp else 'Não informada'
    updated = date_value(item.get('data_atualizacao_preco'))
    update_note = (f'<p class="address">Preço atualizado em {updated.strftime("%d/%m/%Y")}; a ficha também informa essa data como datePosted.</p>' if updated and item.get('site') == 'roda' else (f'<p class="address">Preço atualizado em {updated.strftime("%d/%m/%Y")}; não confirma a data de publicação.</p>' if updated else ''))
    district = str(item.get('bairro') or 'Bairro não informado').title()
    addr = item.get('endereco') or item.get('titulo') or 'Apartamento à venda em Santos'
    addr = str(addr)[:210]
    alternate = (f'<a class="alt" href="{esc(item["alternate_url"])}" target="_blank" rel="noopener noreferrer">Ver também no {esc(item["alternate_site"])} ↗</a>' if item.get('alternate_url') else '')
    key = item['site'] + ':' + str(item['id'])
    return f'''<article class="card" data-key="{esc(key)}" data-search="{esc((district + ' ' + addr + ' ' + LABEL.get(item['site'], item['site'])).lower())}">
      <div class="cardtop"><span class="badge">{esc(LABEL.get(item['site'], item['site']))}</span><span class="rank">#{index:02}</span></div>
      <h3>{esc(district)}</h3><p class="address">{esc(addr)}</p>
      <p class="price">{money(item['preco'])} <span>· {item['area']:g} m²</span></p>
      <div class="facts"><div><small>Condomínio</small><strong>{esc(fee)}</strong></div><div><small>Preço de compra / m²</small><strong>{money(item['preco']/item['area'])}</strong></div>
      <div><small>Vagas informadas</small><strong>{esc(item.get('vagas') or 'Não informadas')}</strong></div><div><small>Elevador</small><strong>{esc(item.get('elevador') or 'Não confirmado')}</strong></div><div><small>Cadastro/publicação</small><strong>{published}</strong></div></div>
      {update_note}<div class="score"><span>Índice em 5 anos por m²</span><b>{esc(rank)}</b></div>
      <a class="button" href="{esc(item['url'])}" target="_blank" rel="noopener noreferrer">Ver anúncio <span aria-hidden="true">↗</span></a>{alternate}
      <div class="actions"><button class="consider" type="button">☆ Considerar</button><button class="exclude" type="button">Excluir</button><button class="undo" type="button">Restaurar</button></div>
    </article>'''

def cards(rows):
    return '\n'.join(render_card(item, i) for i, item in enumerate(sorted(rows, key=section_sort), 1))

def build_report(data_dir, out_path, labels, title, profile_note, switch_href, switch_label):
    all_rows, statuses, seen, portal_ids = [], [], set(), {}
    for site, name in labels.items():
        path = data_dir / (site + '.json')
        if not path.exists():
            statuses.append((name, None, None, 'não concluída'))
            continue
        doc = json.loads(path.read_text(encoding='utf-8'))
        statuses.append((name, doc.get('total', 0), len(doc.get('rows', [])), 'parcial' if doc.get('errors') else 'concluída'))
        for item in doc.get('rows', []):
            key = (site, str(item.get('id')))
            if key in seen or not item.get('url') or not item.get('preco') or not item.get('area'): continue
            seen.add(key)
            item = dict(item)
            portal_id = str(item.get('id'))
            if site in ('vivareal', 'zap') and portal_id in portal_ids:
                existing = portal_ids[portal_id]
                if existing.get('preco') == item.get('preco') and existing.get('area') == item.get('area'):
                    existing['alternate_url'] = item['url']
                    existing['alternate_site'] = labels[site]
                    continue
            if site in ('vivareal', 'zap'):
                portal_ids[portal_id] = item
            all_rows.append(item)

    recent, unknown, older = [], [], []
    for item in all_rows:
        stamp = date_value(item.get('data_publicacao'))
        if not stamp or stamp > TODAY: unknown.append(item)
        elif stamp >= CUTOFF: recent.append(item)
        else: older.append(item)

    source_rows = ''.join('<tr><td>'+esc(name)+'</td><td>'+('—' if total is None else str(total))+'</td><td>'+('—' if matched is None else str(matched))+'</td><td>'+esc(status)+'</td></tr>' for name,total,matched,status in statuses)
    recent_cards = cards(recent) or '<p class="empty">Nenhum anúncio com data verificável dentro do período foi encontrado nesta coleta.</p>'
    unknown_cards = cards(unknown) or '<p class="empty">Nenhum anúncio nesta seção.</p>'
    content = f'''<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
.actions{{display:flex;gap:7px;margin-top:10px}}.actions button{{flex:1;padding:8px 5px;border:1px solid #cbd8d4;border-radius:7px;background:#fff;cursor:pointer;font-weight:650;font-size:.78rem}}.actions .consider{{color:#176c5c}}.actions .exclude{{color:#8d3636}}.actions .undo{{display:none}}.card.considered{{outline:3px solid #d8a21d;background:#fffdf3;order:-1}}.card.considered .consider{{background:#fff0bd;border-color:#d8a21d}}.card.excluded{{display:none}}.actions button:disabled{{opacity:.55;cursor:wait}}
.excluded-toggle{{margin:18px 8px 0 0;padding:9px 14px;border:1px solid #cbd8d4;border-radius:8px;background:#fff;color:#344c50;font-weight:650;cursor:pointer;text-decoration:none;display:inline-block}}body.show-excluded .card.excluded{{display:flex;opacity:.68}}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f5f5;color:#172931;font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}.hero{{background:#123d45;color:#fff;padding:52px max(24px,calc((100vw - 1120px)/2)) 48px}}.eyebrow{{text-transform:uppercase;letter-spacing:.12em;font-size:.73rem;font-weight:750;color:#a9d7ca}}h1{{font-size:clamp(2rem,5vw,3.3rem);line-height:1.08;max-width:800px;margin:12px 0 14px}}.lead{{max-width:760px;color:#d5e7e5;margin:0}}main{{max-width:1168px;margin:auto;padding:30px 24px 70px}}.stats{{display:flex;gap:12px;flex-wrap:wrap;margin-top:-55px;position:relative}}.stat{{background:#fff;border:1px solid #dbe4e1;border-radius:14px;padding:16px 20px;box-shadow:0 6px 25px #142c2810;min-width:180px}}.stat b{{display:block;font-size:1.5rem;line-height:1.1;color:#12544f}}.stat span{{font-size:.8rem;color:#556a70}}.note{{background:#fff;border-left:4px solid #3f8a79;border-radius:6px;padding:16px 20px;margin:28px 0;color:#374f55}}.note p{{margin:.4em 0}}h2{{font-size:1.55rem;letter-spacing:-.02em;margin:38px 0 5px}}.sub{{color:#566b70;margin:0 0 20px}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,315px),1fr));gap:15px}}.card{{background:white;border:1px solid #dce5e2;border-radius:14px;padding:19px;display:flex;flex-direction:column;box-shadow:0 5px 17px #102d2609}}.cardtop{{display:flex;justify-content:space-between;align-items:center}}.badge{{background:#e4f2ed;color:#196351;border-radius:999px;padding:4px 10px;font-size:.72rem;font-weight:750}}.rank{{color:#809390;font-size:.8rem}}h3{{font-size:1.2rem;margin:13px 0 0}}.address{{font-size:.85rem;color:#607377;min-height:2.7em;margin:2px 0 10px}}.price{{font-size:1.36rem;font-weight:800;letter-spacing:-.03em;margin:0 0 14px;color:#164b49}}.price span{{color:#748381;font-size:.85rem;font-weight:500;letter-spacing:0}}.facts{{display:grid;grid-template-columns:1fr 1fr;gap:11px;padding:14px 0;border-top:1px solid #edf0ef}}small{{display:block;font-size:.7rem;color:#708381}}.facts strong{{font-size:.82rem}}.score{{display:flex;justify-content:space-between;gap:10px;background:#f2f7f5;border-radius:8px;padding:10px;font-size:.78rem;margin:auto 0 14px}}.score b{{text-align:right;color:#125c4e}}.button{{display:block;text-align:center;text-decoration:none;color:white;background:#176c5c;border-radius:8px;padding:10px;font-weight:700;font-size:.9rem}}.button:hover{{background:#104b40}}details{{margin-top:24px}}summary{{cursor:pointer;font-weight:750;color:#12544f}}table{{border-collapse:collapse;width:100%;font-size:.85rem;margin-top:15px}}th,td{{text-align:left;border-bottom:1px solid #dde6e3;padding:9px}}.table-wrap{{overflow:auto}}.empty{{padding:18px;background:#fff;border-radius:10px}}footer{{color:#667b7d;font-size:.8rem;margin-top:40px}}@media(max-width:600px){{.hero{{padding-top:35px;padding-bottom:40px}}.stats{{margin-top:-45px}}.stat{{min-width:0;flex:1}}}}
</style></head><body><header class="hero"><div class="eyebrow">Pesquisa de apartamentos · Santos / SP</div><h1>Uma visão dos imóveis que se encaixam</h1><p class="lead">Comparação dos anúncios disponíveis nas fontes monitoradas, com as limitações de data e informações em destaque.</p></header>
<main><div class="stats"><div class="stat"><b>{len(recent)}</b><span>anúncios com data no período</span></div><div class="stat"><b>{len(unknown)}</b><span>sem data verificável</span></div><div class="stat"><b>{CUTOFF.strftime('%d %b')} – {TODAY.strftime('%d %b %Y')}</b><span>janela de cinco meses</span></div></div><button class="excluded-toggle" id="excludedToggle" type="button">Mostrar excluídos</button><a class="excluded-toggle" style="background:#d8a21d;color:#172931;border-color:#d8a21d;font-weight:800" href="relatorio_530mil_elevador.html">🏆 Ver Top 10 Curado (até R$ 530 mil c/ Elevador) ↗</a><a class="excluded-toggle" style="background:#d8a21d;color:#172931;border-color:#d8a21d;font-weight:800" href="index.html">🏆 Ver Top 10 Curado (até R$ 426 mil) ↗</a><a class="excluded-toggle" href="{esc(switch_href)}">{esc(switch_label)}</a>
<div class="note"><p><b>Como ler a lista.</b> O período usa a data de cadastro ou publicação que a fonte efetivamente informa; não é possível saber se o mesmo imóvel já era anunciado antes. Foram excluídos {len(older)} anúncios com data anterior ao período.</p>
<p><b>Ordenação:</b> menor <em>(preço de compra + 60 mensalidades de condomínio) ÷ área</em> aparece primeiro. É uma comparação ilustrativa, não uma previsão do custo total: não inclui IPTU, financiamento, taxas, reformas, reajustes ou qualidade do imóvel. Quando o condomínio está ausente ou zerado sem confirmação, o índice não é calculado; esses anúncios ficam depois dos comparáveis, ordenados pelo preço por m².</p>
<p>{profile_note}</p>
<p>Quando a fonte não informa a data de publicação/cadastro de forma verificável, o anúncio aparece separado e não entra na contagem do período. Data de atualização de preço não é tratada como data de publicação, salvo quando a página a fornece explicitamente como <code>datePosted</code>.</p>
<p>A coleta reflete os resultados que os sites entregaram em {TODAY.strftime('%d/%m/%Y')}, não uma garantia de cobertura completa. Anúncios de Viva Real e Zap com o mesmo identificador, preço e área foram reunidos; outros anúncios podem ser do mesmo imóvel, mas não foram unificados sem confirmação.</p></div>
<h2>Dentro dos últimos cinco meses</h2><p class="sub">Data de publicação/cadastro verificável entre {CUTOFF.strftime('%d/%m/%Y')} e {TODAY.strftime('%d/%m/%Y')}, inclusive. Ordem por menor índice em 5 anos por m².</p><div class="grid">{recent_cards}</div>
<details><summary>Ver também {len(unknown)} anúncios sem data verificável</summary><p class="sub">São candidatos aos mesmos filtros, mas <b>não foi possível confirmar se foram publicados nos últimos cinco meses</b>. Não estão incluídos na contagem acima.</p><div class="grid">{unknown_cards}</div></details>
<details><summary>Fontes e abrangência da coleta</summary><p class="sub">“Anúncios analisados” representa os resultados retornados pela busca de cada fonte; “candidatos” são os anúncios que passaram pelos filtros antes da verificação da data. Na R3, a consulta percorreu até dez páginas, como no monitor.</p><div class="table-wrap"><table><thead><tr><th>Fonte</th><th>Anúncios analisados</th><th>Candidatos</th><th>Consulta</th></tr></thead><tbody>{source_rows}</tbody></table></div></details>
<footer>Pesquisa feita em {TODAY.strftime('%d/%m/%Y')}. Preços, disponibilidade e características podem mudar; confirme todos os dados na ficha original. Não inclui aluguel. Para salvar exclusões e favoritos, abra por abrir_relatorio.bat.</footer></main>
<script>
const decisionCards=[...document.querySelectorAll('.card[data-key]')];
document.querySelector('#excludedToggle').onclick=event=>{{document.body.classList.toggle('show-excluded');event.currentTarget.textContent=document.body.classList.contains('show-excluded')?'Ocultar excluídos':'Mostrar excluídos'}};
async function setDecision(card,status){{const buttons=card.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);try{{const response=await fetch('/api/decision',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{key:card.dataset.key,status}})}});if(!response.ok)throw Error('save failed');card.classList.toggle('excluded',status==='excluded');card.classList.toggle('considered',status==='considered');card.querySelector('.undo').style.display=status?'block':'none'}}catch{{alert('Não foi possível salvar. Abra o relatório usando abrir_relatorio.bat.')}}finally{{buttons.forEach(b=>b.disabled=false)}}}}
decisionCards.forEach(card=>{{card.querySelector('.consider').onclick=()=>setDecision(card,'considered');card.querySelector('.exclude').onclick=()=>setDecision(card,'excluded');card.querySelector('.undo').onclick=()=>setDecision(card,null)}});
fetch('/api/decisions').then(r=>{{if(!r.ok)throw Error();return r.json()}}).then(saved=>decisionCards.forEach(card=>{{const status=saved[card.dataset.key];if(status){{card.classList.add(status);card.querySelector('.undo').style.display='block'}}}})).catch(()=>document.body.insertAdjacentHTML('afterbegin','<div style="position:sticky;top:0;background:#ffe9b2;padding:10px;text-align:center;z-index:9">Banco local desconectado. Abra abrir_relatorio.bat para carregar e salvar decisões.</div>'));
</script></body></html>'''
    out_path.write_text(content, encoding='utf-8')
    print(f'Relatório: {out_path}; recentes={len(recent)}, sem data={len(unknown)}, antigos={len(older)}')


build_report(
    ROOT / 'relatorio_coletado_principal',
    ROOT / 'apartamentos_santos.html',
    LABEL,
    'Apartamentos em Santos — perfil principal (até R$ 530 mil)',
    '<b>Perfil principal apenas.</b> Apartamentos à venda em Santos nos bairros Aparecida, Boqueirão, Embaré, Gonzaga e Pompéia; até R$ 530 mil; 2 quartos; mínimo de 70 m²; pelo menos uma vaga (coletiva aceita); não térreo; elevador confirmado; condomínio informado até R$ 1.100; avenidas excluídas. Condomínio e andar não informados não eliminam o anúncio.',
    'apartamentos_santos_426mil.html',
    'Ver relatório até R$ 426 mil ↗',
)

build_report(
    ROOT / 'relatorio_coletado',
    ROOT / 'apartamentos_santos_426mil.html',
    LABEL_426,
    'Apartamentos em Santos — até R$ 426 mil',
    '<b>Perfil paralelo (até R$ 426 mil).</b> Apartamentos à venda em Santos nos bairros Aparecida, Boqueirão, Campo Grande, Embaré, Gonzaga, José Menino, Marapé e Pompéia; até R$ 426 mil; 2 quartos; mínimo de 70 m²; pelo menos uma vaga (coletiva aceita); não térreo; condomínio informado até R$ 800. Condomínio e andar não informados não eliminam o anúncio.',
    'apartamentos_santos.html',
    'Ver relatório até R$ 530 mil ↗',
)
