import re
import unicodedata
from urllib.parse import quote_plus


BRAND_HOME_PAGES = {
    'FIAT': 'https://www.fiat.com.br/',
    'CHEVROLET': 'https://www.chevrolet.com.br/',
    'VOLKSWAGEN': 'https://www.vw.com.br/',
    'RENAULT': 'https://www.renault.com.br/',
    'HYUNDAI': 'https://www.hyundai.com.br/',
    'FORD': 'https://www.ford.com.br/',
    'TOYOTA': 'https://www.toyota.com.br/',
    'STELLANTIS': 'https://www.stellantis.com/br',
    'HONDA': 'https://www.honda.com.br/',
    'YAMAHA': 'https://www.yamaha-motor.com.br/',
    'SUZUKI': 'https://www.suzukimotos.com.br/',
    'KAWASAKI': 'https://www.kawasaki.com.br/',
    'MERCEDES BENZ': 'https://www.mercedes-benz.com.br/',
    'MERCEDES-BENZ': 'https://www.mercedes-benz.com.br/',
    'SCANIA': 'https://www.scania.com/br/pt/home.html',
    'VOLVO': 'https://www.volvo.com/',
    'IVECO': 'https://www.iveco.com/brasil',
    'DAF': 'https://www.daf.com/',
}

REFERENCE_SEARCH_ENGINES = [
    'Google Search',
    'Google Imagens',
    'UOL Busca',
    'Yahoo Search',
    'Webmotors',
    'OLX',
    'Mercado Livre',
    'Amazon',
    'FIPE API aberta',
    'NetCarShow',
    'Cars.com Research',
    'Edmunds',
    'Automobile Catalog',
    'Inmetro / PBE Veicular',
]

REFERENCE_ANALYSIS_ENGINES = [
    'analise_visual_local_heuristica',
    'assinaturas_componentes_geometricas',
    'comparacao_fontes_abertas',
    'checagem_forense_de_caracteristicas',
    'comparacao_catalagos_publicos',
    'validacao_pbe_veicular',
]

BASE_CHECKLIST = [
    'Comparar formato da lanterna traseira (vertical/horizontal), altura relativa e posicao lateral.',
    'Comparar desenho da tampa traseira e recorte do para-choque.',
    'Comparar assinatura dos farois, grade dianteira e emblema frontal quando visivel.',
    'Comparar retrovisores, molduras de vidro e linha de cintura.',
    'Validar faixa de ano/modelo por FIPE e cruzar com anuncios reais.',
    'Cruzar com catalogos de autopecas (lataria/farol/lanterna/grade) para confirmar aplicacao por modelo.',
]

CHECKLIST_BY_CATEGORY = {
    'MOTOCICLETA': [
        'Comparar tanque, carenagem, rabeta, farol e formato do conjunto traseiro.',
        'Comparar posicao de retrovisores, escapamento e desenho das rodas.',
        'Validar compatibilidade de frente, laterais e rabeta por ano/modelo.',
    ],
    'CAMINHAO': [
        'Comparar cabine, conjunto optico, para-choque, grade e espelhos laterais.',
        'Comparar quantidade de eixos, implemento traseiro e proporcao da cabine.',
        'Validar faixa de ano por configuracao de cabine e conjunto frontal.',
    ],
}

BASE_CRITERIA = [
    'Emblema frontal: posicao, geometria (circular/oval/barra) e contraste.',
    'Conjunto optico dianteiro: desenho interno, recorte externo e alinhamento lateral.',
    'Grade frontal: proporcao da abertura central, trama e area de contorno.',
    'Conjunto optico traseiro: orientacao (vertical/horizontal), separacao e altura relativa.',
    'Portas e lateral: vincos, coluna B, alinhamento de macanetas e linha de cintura.',
    'Capo e tampa traseira: vincos principais, recortes e relacao com para-choques.',
    'Carroceria geral: proporcao hatch/sedan, entre-eixos aparente e simetria visual.',
    'Sinais forenses: possivel amassado, diferenca de pintura, retrovisor danificado e adesivos.',
]

CRITERIA_BY_CATEGORY = {
    'MOTOCICLETA': [
        'Conjunto frontal: farol, carenagem, guidon e retrovisores.',
        'Lateral: tanque, rabeta, posicao das pedaleiras e desenho das rodas.',
        'Traseira: lanterna, suporte de placa e escapamento.',
    ],
    'CAMINHAO': [
        'Cabine: grade, farois, retrovisores e para-choque.',
        'Chassi/rodado: quantidade de eixos e proporcao do conjunto.',
        'Implemento: bau, grade, tanque ou carreta conforme aplicacao.',
    ],
}


def normalize_text(value):
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.strip().upper()
    text = re.sub(r'[^A-Z0-9 ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_category(value):
    category = normalize_text(value or '')
    if category in ('AUTO', 'CARRO', 'AUTOMOVEL', 'AUTOMOVEIS', 'HATCH', 'SEDAN', 'SUV', 'PICAPE'):
        return 'AUTOMOVEL'
    if category in ('MOTO', 'MOTOCICLETA', 'MOTOS', 'SCOOTER', 'BIKE'):
        return 'MOTOCICLETA'
    if category in ('CAMINHAO', 'TRUCK', 'UTILITARIO PESADO', 'PESADO'):
        return 'CAMINHAO'
    return 'AUTOMOVEL'


def _normalize_target(fabricante, modelo):
    target = normalize_text(f'{fabricante or ""} {modelo or ""}')
    return target or 'VEICULO COMPARATIVO'


def _google_search_url(query):
    return 'https://www.google.com/search?q=' + quote_plus(query)


def _dedupe_sources(sources):
    seen = set()
    deduped = []
    for item in sources:
        if not isinstance(item, dict):
            continue
        fonte = normalize_text(item.get('fonte', ''))
        url = str(item.get('url', '')).strip()
        key = (fonte, url)
        if not url or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _add_source(sources, fonte, nome, familia, url, objetivo, prioridade=0.0, tipo='consulta'):
    sources.append({
        'fonte': str(fonte),
        'nome': str(nome),
        'familia': str(familia),
        'tipo': str(tipo),
        'prioridade': round(float(prioridade), 2),
        'url': str(url),
        'objetivo': str(objetivo),
    })


def get_reference_checklist(category='AUTOMOVEL'):
    normalized = normalize_category(category)
    items = list(BASE_CHECKLIST)
    items.extend(CHECKLIST_BY_CATEGORY.get(normalized, []))
    return items


def get_reference_criteria(category='AUTOMOVEL'):
    normalized = normalize_category(category)
    items = list(BASE_CRITERIA)
    items.extend(CRITERIA_BY_CATEGORY.get(normalized, []))
    return items


def get_reference_search_engines():
    return list(REFERENCE_SEARCH_ENGINES)


def get_reference_analysis_engines():
    return list(REFERENCE_ANALYSIS_ENGINES)


def build_visual_reference_query_specs(fabricante, modelo, category='AUTOMOVEL', model_conclusive=True):
    target = _normalize_target(fabricante, modelo)
    normalized = normalize_category(category)

    specs = [
        (f'site:toyota.com.br ("press kit" OR "media kit" OR "vehicle gallery" OR imprensa) {target}', 'geral'),
        (f'site:ford.com.br ("midia kit" OR "press kit" OR imprensa) {target}', 'geral'),
        (f'site:stellantis.com (press kit OR imprensa OR photos OR videos) {target}', 'geral'),
        (f'site:vw.com.br ("press kit" OR imprensa OR galeria) {target}', 'geral'),
        (f'site:netcarshow.com {target}', 'geral'),
        (f'site:cars.com/research {target}', 'geral'),
        (f'site:edmunds.com {target}', 'geral'),
        (f'site:automobile-catalog.com {target}', 'geral'),
        (f'site:gov.br "PBE Veicular" {target}', 'geral'),
        (f'manual do proprietario {target}', 'geral'),
        (f'{target} detalhes visuais emblema grade farol lanterna', 'geral'),
        (f'site:quatrorodas.abril.com.br {target} teste', 'geral'),
        (f'site:webmotors.com.br {target} fotos', 'geral'),
        (f'site:olx.com.br {target}', 'geral'),
        (f'site:mercadolivre.com.br {target}', 'geral'),
        (f'site:amazon.com.br {target}', 'geral'),
        (f'{target} ficha tecnica comparativo visual', 'geral'),
    ]

    if normalized == 'MOTOCICLETA':
        specs.extend([
            (f'site:honda.com.br ("press kit" OR "midia kit" OR imprensa) {target}', 'geral'),
            (f'site:yamaha-motor.com.br ("press kit" OR imprensa) {target}', 'geral'),
            (f'site:suzukimotos.com.br {target} moto ficha tecnica', 'geral'),
            (f'site:kawasaki.com.br {target} moto ficha tecnica', 'geral'),
            (f'site:motoo.com.br {target} teste', 'geral'),
            (f'site:motonline.com.br {target} ficha tecnica', 'geral'),
            (f'site:webmotors.com.br/motos {target}', 'geral'),
        ])
    elif normalized == 'CAMINHAO':
        specs.extend([
            (f'site:scania.com ("press kit" OR imprensa) {target}', 'geral'),
            (f'site:volvo.com ("press kit" OR trucks OR imprensa) {target}', 'geral'),
            (f'site:mercedes-benz.com.br ("press kit" OR imprensa) {target}', 'geral'),
            (f'site:iveco.com.br ("press kit" OR imprensa) {target}', 'geral'),
            (f'site:daf.com ("press kit" OR imprensa) {target}', 'geral'),
            (f'site:caminhoes-e-carretas.com {target} ficha tecnica', 'geral'),
            (f'site:blogdocaminhoneiro.com {target}', 'geral'),
            (f'site:estradao.estadao.com.br {target}', 'geral'),
        ])

    if not model_conclusive:
        specs.append((f'comparativo visual automotivo {target}', 'geral'))

    deduped = []
    seen = set()
    for query, hint in specs:
        key = (normalize_text(query), normalize_text(hint))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((query, hint))
    return deduped


def build_visual_reference_sources(fabricante, modelo, category='AUTOMOVEL', view_type='indefinida', model_conclusive=True):
    target = _normalize_target(fabricante, modelo)
    normalized = normalize_category(category)
    brand_key = normalize_text(fabricante)

    sources = []
    _add_source(
        sources,
        'manual_proprietario',
        'Manual do proprietario',
        'research_search',
        _google_search_url(f'manual do proprietario {target}'),
        'manual oficial e diagramas',
        4.5,
    )
    _add_source(
        sources,
        'google_imagens',
        'Google Imagens',
        'research_search',
        _google_search_url(f'{target} detalhes visuais emblema grade farol lanterna'),
        'comparacao visual por imagens',
        4.4,
    )

    official_press_queries = [
        ('toyota_vehicle_gallery', 'Toyota Vehicle Gallery / press kits', 'site:toyota.com.br ("press kit" OR "media kit" OR "vehicle gallery" OR imprensa) {target}', 'catalogos oficiais, releases e fotos por ano/modelo'),
        ('ford_brasil_midia_kits', 'Ford Brasil Midia Kits', 'site:ford.com.br ("midia kit" OR "press kit" OR imprensa) {target}', 'press kits e galerias de imprensa do fabricante'),
        ('stellantis_press_portal', 'Stellantis press portal', 'site:stellantis.com (press kit OR imprensa OR photos OR videos) {target}', 'press kits oficiais e fotos de lancamento'),
        ('volkswagen_press_kits', 'Volkswagen press kits', 'site:vw.com.br ("press kit" OR imprensa OR galeria) {target}', 'press kits e fotos oficiais por facelift e geracao'),
    ]
    for fonte, nome, template, objetivo in official_press_queries:
        query = template.format(target=target)
        _add_source(
            sources,
            fonte,
            nome,
            'official_press_kit',
            _google_search_url(query),
            objetivo,
            5.0,
        )

    if normalized == 'MOTOCICLETA':
        extra_official = [
            ('honda_brasil_press', 'Honda Brasil imprensa', 'site:honda.com.br ("press kit" OR "midia kit" OR imprensa) {target}', 'galeria e press kit oficiais de motocicletas'),
            ('yamaha_press_portal', 'Yamaha press portal', 'site:yamaha-motor.com.br ("press kit" OR imprensa) {target}', 'galeria oficial e lancamentos de motos'),
            ('suzuki_motos_press', 'Suzuki motos imprensa', 'site:suzukimotos.com.br ("press kit" OR imprensa) {target}', 'press kits e fotos oficiais de motocicletas'),
            ('kawasaki_press_portal', 'Kawasaki press portal', 'site:kawasaki.com.br ("press kit" OR imprensa) {target}', 'press kits e fotos oficiais de motocicletas'),
        ]
    elif normalized == 'CAMINHAO':
        extra_official = [
            ('scania_press_portal', 'Scania press portal', 'site:scania.com ("press kit" OR imprensa) {target}', 'catalogos oficiais de cabine e frente'),
            ('volvo_trucks_press', 'Volvo Trucks press portal', 'site:volvo.com ("press kit" OR trucks OR imprensa) {target}', 'catalogos oficiais de caminhões'),
            ('mercedes_benz_press', 'Mercedes-Benz press portal', 'site:mercedes-benz.com.br ("press kit" OR imprensa) {target}', 'press kits oficiais de caminhões'),
            ('iveco_press_portal', 'Iveco press portal', 'site:iveco.com.br ("press kit" OR imprensa) {target}', 'press kits oficiais de caminhões e vans'),
            ('daf_press_portal', 'DAF press portal', 'site:daf.com ("press kit" OR imprensa) {target}', 'press kits oficiais de caminhões'),
        ]
    else:
        extra_official = []

    for fonte, nome, template, objetivo in extra_official:
        query = template.format(target=target)
        _add_source(
            sources,
            fonte,
            nome,
            'official_press_kit',
            _google_search_url(query),
            objetivo,
            4.8,
        )

    public_catalog_sources = [
        ('netcarshow', 'NetCarShow', 'public_catalog', 'https://www.netcarshow.com/', 'catalogo visual por marca, modelo e ano', 4.8, 'direct'),
        ('cars_com_research', 'Cars.com Research', 'public_catalog', 'https://www.cars.com/research/', 'comparacao por anos, geracoes e versoes', 4.6, 'direct'),
        ('edmunds', 'Edmunds', 'public_catalog', 'https://www.edmunds.com/', 'comparacao de trims e geracoes lado a lado', 4.5, 'direct'),
        ('automobile_catalog', 'Automobile Catalog', 'public_catalog', 'https://www.automobile-catalog.com/', 'catalogo tecnico por geracao e especificacoes', 4.7, 'direct'),
    ]
    for fonte, nome, familia, url, objetivo, prioridade, tipo in public_catalog_sources:
        _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, tipo)

    _add_source(
        sources,
        'inmetro_pbe_veicular',
        'Inmetro / PBE Veicular',
        'brazil_validation',
        _google_search_url(f'site:gov.br "PBE Veicular" {target}'),
        'validar combinações efetivamente ofertadas no Brasil',
        5.0,
    )

    if brand_key in BRAND_HOME_PAGES:
        _add_source(
            sources,
            f'catalogo_oficial_{brand_key.lower().replace(" ", "_")}',
            f'Catalogo oficial {brand_key.title()}',
            'brand_homepage',
            BRAND_HOME_PAGES[brand_key],
            'portal oficial do fabricante para consulta primaria',
            4.9,
            'direct',
        )

    marketplace_sources = [
        ('webmotors', 'Webmotors', 'marketplace', f'https://www.webmotors.com.br/carros/estoque?marca={quote_plus(str(fabricante or ""))}&modelo={quote_plus(str(modelo or ""))}' if model_conclusive and fabricante and modelo else _google_search_url(f'site:webmotors.com.br {target}'), 'fotos reais de anuncios', 4.2, 'direct'),
        ('olx', 'OLX', 'marketplace', f'https://www.olx.com.br/autos-e-pecas?q={quote_plus(target)}', 'amostra ampla de veiculos usados', 3.1, 'direct'),
        ('mercado_livre', 'Mercado Livre', 'marketplace', 'https://lista.mercadolivre.com.br/' + quote_plus(target.lower().replace(' ', '-')), 'pecas e variacoes disponiveis no mercado', 3.0, 'direct'),
        ('amazon', 'Amazon', 'marketplace', f'https://www.amazon.com.br/s?k={quote_plus(target + " lanterna traseira")}', 'pecas e codigos de reposicao', 2.8, 'direct'),
    ]
    for fonte, nome, familia, url, objetivo, prioridade, tipo in marketplace_sources:
        _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, tipo)

    public_search_sources = [
        ('google_web', 'Google Search', 'search', _google_search_url(f'{target} ficha tecnica comparativo visual'), 'busca ampla por noticias e comparativos', 4.2),
        ('revista_quatro_rodas', 'Quatro Rodas', 'search', _google_search_url(f'site:quatrorodas.abril.com.br {target} teste'), 'avaliacoes e fotos comparativas', 4.0),
        ('uol', 'UOL Busca', 'search', 'https://busca.uol.com.br/?q=' + quote_plus(f'{target} grade farol lanterna ficha tecnica'), 'materias automotivas e comparativos', 3.7),
        ('yahoo', 'Yahoo Search', 'search', 'https://search.yahoo.com/search?p=' + quote_plus(f'{target} grade farol lanterna ficha tecnica'), 'segunda opiniao de busca', 3.4),
    ]
    for fonte, nome, familia, url, objetivo, prioridade in public_search_sources:
        _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, 'search')

    catalog_search_sources = [
        ('catalogos_autopecas_multidominio', 'Catalogos autopecas multidominio', 'parts_catalog', _google_search_url(
            f'{target} lanterna farol grade para-choque lataria site:autoexperts.parts OR site:download.centerparts.com.br OR site:mundocarautopecas.com.br OR site:promo.ponteirasrodrigues.com.br OR site:saojorgelatarias.com.br OR site:centauroautoparts.com.br OR site:autopecasprimo.com OR site:jocar.com.br OR site:partsy.com.br'
        ), 'comparar componentes por catalogos de pecas', 4.3),
    ]
    for fonte, nome, familia, url, objetivo, prioridade in catalog_search_sources:
        _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, 'search')

    direct_parts_sources = [
        ('autoexperts_parts', 'AutoExperts Parts', 'parts_catalog', 'https://www.autoexperts.parts/pt/br', 'catalogo de autopecas para comparativo de componentes visuais', 4.2),
        ('centerparts_catalogos', 'Centerparts Catalogos', 'parts_catalog', 'https://download.centerparts.com.br/catalogos', 'catalogos tecnicos para identificacao de aplicacoes de pecas', 4.1),
        ('mundocar_autopecas_lataria', 'Mundocar Autopecas Lataria', 'parts_catalog', 'https://www.mundocarautopecas.com.br/lataria', 'referencia de lataria e variacoes por modelo/ano', 4.1),
        ('ponteiras_rodrigues_catalogo_lataria', 'Ponteiras Rodrigues Catalogo Lataria', 'parts_catalog', 'https://promo.ponteirasrodrigues.com.br/catalogo-autopecas-lataria', 'catalogo focado em lataria para confronto de compatibilidade', 4.1),
        ('sao_jorge_latarias', 'Sao Jorge Latarias', 'parts_catalog', 'https://saojorgelatarias.com.br/', 'pesquisa de itens de lataria por aplicacao', 4.1),
        ('centauro_autoparts', 'Centauro Autoparts', 'parts_catalog', 'https://www.centauroautoparts.com.br/', 'comparativo de pecas e componentes de carroceria', 4.0),
        ('autopecas_primo_lataria', 'Autopecas Primo Lataria', 'parts_catalog', 'https://www.autopecasprimo.com/latarias-e-monobloco/lataria', 'lataria e monobloco para identificacao por conjunto de pecas', 4.0),
        ('jocar_latarias', 'Jocar Latarias', 'parts_catalog', 'https://www.jocar.com.br/latarias/', 'catalogo de latarias para confronto de detalhes de carroceria', 4.0),
        ('partsy_lataria', 'Partsy Lataria', 'parts_catalog', 'https://www.partsy.com.br/lataria', 'amostra de pecas de lataria para triangulacao visual', 4.0),
    ]
    for fonte, nome, familia, url, objetivo, prioridade in direct_parts_sources:
        _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, 'direct')

    if normalized == 'MOTOCICLETA':
        motorcycle_sources = [
            ('motoo', 'Motoo', 'public_catalog', 'https://www.motoo.com.br/', 'comparacao visual e tecnica de motocicletas', 3.9, 'direct'),
            ('motonline', 'Motonline', 'public_catalog', 'https://www.motonline.com.br/', 'comparacao visual e tecnica de motocicletas', 3.8, 'direct'),
        ]
        for fonte, nome, familia, url, objetivo, prioridade, tipo in motorcycle_sources:
            _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, tipo)

    if normalized == 'CAMINHAO':
        truck_sources = [
            ('caminhoes_e_carretas', 'Caminhoes e Carretas', 'public_catalog', 'https://www.caminhoes-e-carretas.com/', 'comparacao visual e tecnica de caminhões', 3.9, 'direct'),
            ('blogdocaminhoneiro', 'Blog do Caminhoneiro', 'public_catalog', 'https://blogdocaminhoneiro.com/', 'comparacao visual e tecnica de caminhões', 3.8, 'direct'),
            ('estradao', 'Estradao', 'public_catalog', 'https://estradao.estadao.com.br/', 'comparacao visual e tecnica de caminhões', 3.7, 'direct'),
        ]
        for fonte, nome, familia, url, objetivo, prioridade, tipo in truck_sources:
            _add_source(sources, fonte, nome, familia, url, objetivo, prioridade, tipo)

    return _dedupe_sources(sources)


def summarize_source_families(sources):
    summary = {}
    if not isinstance(sources, list):
        return summary
    for item in sources:
        if not isinstance(item, dict):
            continue
        family = str(item.get('familia', 'unknown')).strip() or 'unknown'
        summary[family] = int(summary.get(family, 0)) + 1
    return dict(sorted(summary.items(), key=lambda item: item[0]))


def build_reference_bundle(fabricante, modelo, category='AUTOMOVEL', view_type='indefinida', model_conclusive=True):
    sources = build_visual_reference_sources(
        fabricante,
        modelo,
        category=category,
        view_type=view_type,
        model_conclusive=model_conclusive,
    )
    return {
        'fontes': sources,
        'familias_fontes': summarize_source_families(sources),
        'checklist_pericial': get_reference_checklist(category),
        'criterios_individualizacao': get_reference_criteria(category),
        'motores_busca_utilizados': get_reference_search_engines(),
        'motores_analise_utilizados': get_reference_analysis_engines(),
        'query_specs': build_visual_reference_query_specs(
            fabricante,
            modelo,
            category=category,
            model_conclusive=model_conclusive,
        ),
    }
