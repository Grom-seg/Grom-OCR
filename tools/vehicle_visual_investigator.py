import argparse
import base64
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import cv2
import numpy as np
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = PROJECT_ROOT / 'python'
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

import ocr_agent  # noqa: E402
from utils import visual_reference_catalog as visual_reference_catalog_module  # noqa: E402


BRAND_ALIASES = {
    'VW': 'VOLKSWAGEN',
    'VOLKSWAGEN CAMINHOES E ONIBUS': 'VOLKSWAGEN',
    'VWCO': 'VOLKSWAGEN',
    'MERCEDES BENZ': 'MERCEDES BENZ',
    'MERCEDES': 'MERCEDES BENZ',
    'GM': 'CHEVROLET',
    'CHEVY': 'CHEVROLET',
    'YAMAHA MOTOR': 'YAMAHA',
    'HONDA MOTO': 'HONDA',
    'SCANIA DO BRASIL': 'SCANIA',
}

BRAND_DOMAINS = {
    'fiat': ['fiat.com.br', 'fiat.com'],
    'chevrolet': ['chevrolet.com.br', 'chevrolet.com'],
    'volkswagen': ['vw.com.br', 'volkswagen.com.br', 'volkswagen.com'],
    'hyundai': ['hyundai.com.br', 'hyundai.com'],
    'renault': ['renault.com.br', 'renault.com'],
    'ford': ['ford.com.br', 'ford.com'],
    'honda': ['honda.com.br', 'honda.com'],
    'yamaha': ['yamaha-motor.com.br', 'yamaha-motor.com'],
    'suzuki': ['suzukimotos.com.br', 'suzuki.com'],
    'kawasaki': ['kawasakibrasil.com', 'kawasaki.com'],
    'bmw': ['bmw-motorrad.com.br', 'bmw.com'],
    'scania': ['scania.com', 'scania.com.br'],
    'volvo': ['volvo.com', 'volvotrucks.com'],
    'mercedes benz': ['mercedes-benz.com.br', 'mercedes-benz.com'],
    'iveco': ['iveco.com.br', 'iveco.com'],
    'daf': ['daf.com', 'dafcaminhoes.com.br'],
}

SPECIALIZED_DOMAINS = {
    'quatrorodas.abril.com.br': 4.4,
    'webmotors.com.br': 4.2,
    'icarros.com.br': 3.8,
    'autopapo.uol.com.br': 3.8,
    'motor1.uol.com.br': 3.8,
    'carrosnaweb.com.br': 3.8,
    'revistaautoesporte.globo.com': 3.7,
    'motoo.com.br': 3.8,
    'motonline.com.br': 3.6,
    'motonline.uol.com.br': 3.5,
    'caminhoes-e-carretas.com': 3.8,
    'blogdocaminhoneiro.com': 3.7,
    'estradao.estadao.com.br': 3.7,
    'autoline.com.br': 3.1,
    'car.blog.br': 3.5,
    'flatout.com.br': 3.5,
    'olx.com.br': 2.4,
    'mercadolivre.com.br': 2.2,
    'amazon.com.br': 2.0,
}

MODEL_SIGNATURE_RULES = {
    ('FIAT', 'UNO'): {
        'lanternas_traseiras': {'statuses': {'par_vertical', 'par_detectado'}, 'weight': 24.0},
        'design_carroceria': {'statuses': {'hatch_compacto', 'intermediario'}, 'weight': 16.0},
        'linhas_portas': {'statuses': {'vincos_visiveis', 'linha_parcial'}, 'weight': 12.0},
        'tampa_traseira': {'statuses': {'linha_detectada', 'sinal_fraco'}, 'weight': 10.0},
        'farois_dianteiros': {'statuses': {'simetricos', 'parcial'}, 'weight': 8.0},
        'grade_dianteira': {'statuses': {'presente', 'fraca'}, 'weight': 8.0},
    },
    ('FIAT', 'MOBI'): {
        'design_carroceria': {'statuses': {'hatch_compacto', 'intermediario'}, 'weight': 16.0},
        'grade_dianteira': {'statuses': {'presente', 'fraca'}, 'weight': 14.0},
        'farois_dianteiros': {'statuses': {'simetricos', 'parcial'}, 'weight': 14.0},
        'emblema_frontal': {'statuses': {'detectado'}, 'weight': 12.0},
        'lanternas_traseiras': {'statuses': {'par_detectado', 'par_vertical'}, 'weight': 9.0},
    },
    ('FIAT', 'ARGO'): {
        'grade_dianteira': {'statuses': {'presente'}, 'weight': 18.0},
        'farois_dianteiros': {'statuses': {'simetricos', 'parcial'}, 'weight': 16.0},
        'emblema_frontal': {'statuses': {'detectado'}, 'weight': 12.0},
        'design_carroceria': {'statuses': {'intermediario', 'perfil_longo'}, 'weight': 10.0},
    },
}

COMPONENT_QUERY_TERMS = {
    'emblema_frontal': 'emblema frontal logotipo grade',
    'grade_dianteira': 'grade dianteira desenho frontal',
    'farois_dianteiros': 'farol dianteiro assinatura optica',
    'lanternas_traseiras': 'lanterna traseira assinatura lente',
    'parachoque': 'parachoque dianteiro traseiro desenho',
    'retrovisores': 'retrovisor externo posicao estilo',
    'rodas_originais': 'rodas originais aro acabamento',
    'entradas_ar_frisos': 'entradas de ar frisos laterais',
    'linhas_portas': 'perfil lateral portas vincos',
    'capo_dianteiro': 'capo dianteiro vincos recorte',
    'tampa_traseira': 'tampa traseira recorte placa',
    'design_carroceria': 'design carroceria hatch sedan',
}

CATEGORY_COMPONENT_QUERY_TERMS = {
    'AUTOMOVEL': {},
    'MOTOCICLETA': {
        'tanque_carenagem': 'tanque carenagem lateral moto',
        'rabeta_lanterna': 'rabeta e lanterna traseira motocicleta',
        'escapamento': 'escapamento ponteira acabamento moto',
        'garfo_dianteiro': 'garfo dianteiro e suspensao moto',
    },
    'CAMINHAO': {
        'cabine': 'cabine frontal caminhao desenho',
        'conjunto_optico': 'farol dianteiro caminhao assinatura',
        'eixos_rodado': 'quantidade de eixos e rodado',
        'implemento_traseiro': 'implemento traseiro bau carroceria',
    },
}

CATEGORY_COMPONENT_WEIGHTS = {
    'AUTOMOVEL': {
        'grade_dianteira': 14.0,
        'farois_dianteiros': 14.0,
        'lanternas_traseiras': 14.0,
        'emblema_frontal': 12.0,
        'linhas_portas': 10.0,
        'design_carroceria': 10.0,
        'parachoque': 8.0,
        'retrovisores': 8.0,
        'rodas_originais': 8.0,
        'capo_dianteiro': 6.0,
        'tampa_traseira': 6.0,
    },
    'MOTOCICLETA': {
        'farois_dianteiros': 16.0,
        'lanternas_traseiras': 14.0,
        'retrovisores': 14.0,
        'rodas_originais': 14.0,
        'emblema_frontal': 12.0,
        'design_carroceria': 12.0,
        'parachoque': 8.0,
        'entradas_ar_frisos': 10.0,
    },
    'CAMINHAO': {
        'grade_dianteira': 18.0,
        'farois_dianteiros': 16.0,
        'retrovisores': 14.0,
        'parachoque': 12.0,
        'design_carroceria': 12.0,
        'entradas_ar_frisos': 10.0,
        'lanternas_traseiras': 8.0,
        'rodas_originais': 10.0,
    },
}

VEHICLE_CATEGORY_MODEL_GROUPS = {
    'AUTOMOVEL': {
        'FIAT': ['UNO', 'MOBI', 'ARGO', 'PALIO'],
        'CHEVROLET': ['ONIX', 'PRISMA', 'JOY'],
        'VOLKSWAGEN': ['GOL', 'POLO', 'FOX'],
        'HYUNDAI': ['HB20', 'HB20S'],
        'RENAULT': ['KWID', 'SANDERO', 'LOGAN'],
        'FORD': ['KA', 'KA SEDAN'],
    },
    'MOTOCICLETA': {
        'HONDA': ['CG 160', 'BIZ 125', 'PCX 160', 'CB 300F', 'XRE 300'],
        'YAMAHA': ['FAZER 250', 'FACTOR 150', 'NMAX 160', 'LANDER 250'],
        'SUZUKI': ['INTRUDER 125', 'GIXXER 150', 'BURGMAN 125'],
        'KAWASAKI': ['NINJA 400', 'Z400', 'VERSYS 300'],
    },
    'CAMINHAO': {
        'MERCEDES BENZ': ['ATEGO', 'ACCELO', 'ACTROS', 'AXOR'],
        'VOLVO': ['FH 540', 'FH 460', 'VM 270', 'VM 330'],
        'SCANIA': ['R 450', 'P 320', 'G 440'],
        'IVECO': ['TECTOR', 'STRALIS', 'DAILY'],
        'VOLKSWAGEN': ['CONSTELLATION', 'DELIVERY', 'METEOR'],
        'DAF': ['XF', 'CF', 'LF'],
    },
}

VEHICLE_MODEL_YEAR_HINTS = {
    ('FIAT', 'UNO'): '2010-2021',
    ('FIAT', 'MOBI'): '2017-Atual',
    ('FIAT', 'ARGO'): '2017-Atual',
    ('FIAT', 'PALIO'): '2012-2017',
    ('CHEVROLET', 'ONIX'): '2013-Atual',
    ('CHEVROLET', 'PRISMA'): '2013-2019',
    ('VOLKSWAGEN', 'GOL'): '2008-2023',
    ('VOLKSWAGEN', 'POLO'): '2018-Atual',
    ('HYUNDAI', 'HB20'): '2012-Atual',
    ('RENAULT', 'KWID'): '2017-Atual',
    ('FORD', 'KA'): '2014-2021',
    ('HONDA', 'CG 160'): '2016-Atual',
    ('HONDA', 'BIZ 125'): '2011-Atual',
    ('HONDA', 'XRE 300'): '2009-Atual',
    ('YAMAHA', 'FAZER 250'): '2005-Atual',
    ('YAMAHA', 'NMAX 160'): '2017-Atual',
    ('MERCEDES BENZ', 'ATEGO'): '2004-Atual',
    ('MERCEDES BENZ', 'ACTROS'): '2012-Atual',
    ('VOLVO', 'FH 540'): '2012-Atual',
    ('SCANIA', 'R 450'): '2018-Atual',
    ('IVECO', 'TECTOR'): '2010-Atual',
    ('VOLKSWAGEN', 'CONSTELLATION'): '2006-Atual',
}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.strip().upper()
    text = re.sub(r'[^A-Z0-9 ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def normalize_category(value: str) -> str:
    category = normalize_text(value or '')
    if category in ('AUTO', 'CARRO', 'AUTOMOVEL', 'AUTOMOVEIS', 'HATCH', 'SEDAN', 'SUV', 'PICAPE'):
        return 'AUTOMOVEL'
    if category in ('MOTO', 'MOTOCICLETA', 'MOTOS', 'SCOOTER', 'BIKE'):
        return 'MOTOCICLETA'
    if category in ('CAMINHAO', 'TRUCK', 'UTILITARIO PESADO', 'PESADO'):
        return 'CAMINHAO'
    return 'AUTOMOVEL'


def canonical_brand_name(value: str) -> str:
    raw = normalize_text(value or '')
    if not raw:
        return ''
    return BRAND_ALIASES.get(raw, raw)


def format_model_name(value: str) -> str:
    return normalize_text(value or '')


def normalize_model_key(fabricante: str, modelo: str) -> Tuple[str, str]:
    return canonical_brand_name(fabricante), format_model_name(modelo)


def get_category_brand_map(category: str) -> Dict[str, List[str]]:
    return VEHICLE_CATEGORY_MODEL_GROUPS.get(normalize_category(category), {})


def get_model_pool_for_brand(category: str, brand: str) -> List[str]:
    brand_key = canonical_brand_name(brand)
    category_map = get_category_brand_map(category)
    if brand_key in category_map:
        return list(category_map.get(brand_key, []))
    for mapped_brand, models in category_map.items():
        if canonical_brand_name(mapped_brand) == brand_key:
            return list(models)
    return []


def get_model_year_hint(brand: str, model: str) -> str:
    key = normalize_model_key(brand, model)
    return VEHICLE_MODEL_YEAR_HINTS.get(key, '')


def detect_candidate_category(brand: str, model: str, fallback='AUTOMOVEL') -> str:
    maker_key, model_key = normalize_model_key(brand, model)
    if not maker_key and not model_key:
        return normalize_category(fallback)

    for category, brand_map in VEHICLE_CATEGORY_MODEL_GROUPS.items():
        for mapped_brand, mapped_models in brand_map.items():
            if canonical_brand_name(mapped_brand) != maker_key:
                continue
            normalized_models = {format_model_name(item) for item in mapped_models}
            if model_key and model_key in normalized_models:
                return normalize_category(category)

    for category, brand_map in VEHICLE_CATEGORY_MODEL_GROUPS.items():
        normalized_brands = {canonical_brand_name(item) for item in brand_map.keys()}
        if maker_key in normalized_brands:
            return normalize_category(category)
    return normalize_category(fallback)


def category_component_terms(category: str) -> Dict[str, str]:
    return CATEGORY_COMPONENT_QUERY_TERMS.get(normalize_category(category), {})


def parse_domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower().strip()
    except Exception:
        return ''
    if netloc.startswith('www.'):
        netloc = netloc[4:]
    return netloc


def primary_brand_domain(brand: str) -> str:
    target = canonical_brand_name(brand)
    if not target:
        return ''
    for key, domains in BRAND_DOMAINS.items():
        if normalize_text(key) == target and domains:
            return str(domains[0])
    for key, domains in BRAND_DOMAINS.items():
        key_norm = normalize_text(key)
        if target.startswith(key_norm) or key_norm.startswith(target):
            if domains:
                return str(domains[0])
    return ''


def trusted_domain_weight(domain: str) -> float:
    if not domain:
        return 0.0
    for _, domain_list in BRAND_DOMAINS.items():
        for item in domain_list:
            if domain == item or domain.endswith('.' + item):
                return 5.0
    for item, weight in SPECIALIZED_DOMAINS.items():
        if domain == item or domain.endswith('.' + item):
            return float(weight)
    if any(word in domain for word in ('forum', 'clube', 'club')):
        return 2.8
    return 0.0


def is_specialized_page(page: Dict[str, str]) -> bool:
    domain = parse_domain(page.get('url', ''))
    if trusted_domain_weight(domain) > 0:
        return True
    text = normalize_text(' '.join([page.get('title', ''), page.get('snippet', '')]))
    return any(
        keyword in text
        for keyword in (
            'FICHA TECNICA',
            'TESTE',
            'AVALIACAO',
            'FAROIS',
            'LANTERNA',
            'GRADE',
            'CATALOGO',
            'MANUAL DO PROPRIETARIO',
        )
    )


def preprocess_vehicle_image(img) -> Tuple:
    if img is None or getattr(img, 'size', 0) == 0:
        return img, {'preprocess_applied': False}

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.4, tileGridSize=(8, 8))
    l_eq = clahe.apply(l_channel)
    enhanced = cv2.cvtColor(cv2.merge([l_eq, a_channel, b_channel]), cv2.COLOR_LAB2BGR)
    contrasted = cv2.convertScaleAbs(enhanced, alpha=1.10, beta=7)
    blurred = cv2.GaussianBlur(contrasted, (0, 0), 1.2)
    sharpened = cv2.addWeighted(contrasted, 1.34, blurred, -0.34, 0)
    details = {
        'preprocess_applied': True,
        'brightness_mean_before': round(float(np.mean(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))), 2),
        'brightness_mean_after': round(float(np.mean(cv2.cvtColor(sharpened, cv2.COLOR_BGR2GRAY))), 2),
        'contrast_std_before': round(float(np.std(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))), 2),
        'contrast_std_after': round(float(np.std(cv2.cvtColor(sharpened, cv2.COLOR_BGR2GRAY))), 2),
    }
    return sharpened, details


def detect_vehicle_roi(img) -> Tuple:
    if img is None or getattr(img, 'size', 0) == 0:
        return img, {'vehicle_crop_applied': False, 'reason': 'empty_image'}

    height, width = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 55, 155)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return img, {'vehicle_crop_applied': False, 'reason': 'no_contours'}

    image_area = float(max(1, height * width))
    best = None
    best_score = -1e9
    for contour in contours:
        x, y, box_w, box_h = cv2.boundingRect(contour)
        area = float(box_w * box_h)
        area_ratio = area / image_area
        if area_ratio < 0.08 or area_ratio > 0.96:
            continue
        aspect = box_w / max(1.0, float(box_h))
        if aspect < 0.75 or aspect > 4.2:
            continue
        center_x = x + (box_w / 2.0)
        center_y = y + (box_h / 2.0)
        center_penalty = (
            abs(center_x - (width / 2.0)) / max(1.0, (width / 2.0))
            + abs(center_y - (height / 2.0)) / max(1.0, (height / 2.0))
        )
        score = (area_ratio * 120.0) - (center_penalty * 16.0)
        if score > best_score:
            best_score = score
            best = (x, y, box_w, box_h, area_ratio, aspect)

    if best is None:
        return img, {'vehicle_crop_applied': False, 'reason': 'no_valid_box'}

    x, y, box_w, box_h, area_ratio, aspect = best
    pad_x = max(8, int(box_w * 0.05))
    pad_y = max(8, int(box_h * 0.05))
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(width, x + box_w + pad_x)
    y2 = min(height, y + box_h + pad_y)
    roi = img[y1:y2, x1:x2]
    if roi.size == 0:
        return img, {'vehicle_crop_applied': False, 'reason': 'empty_crop'}

    return roi, {
        'vehicle_crop_applied': True,
        'bbox_norm': {
            'x': round(x1 / max(1.0, float(width)), 4),
            'y': round(y1 / max(1.0, float(height)), 4),
            'w': round((x2 - x1) / max(1.0, float(width)), 4),
            'h': round((y2 - y1) / max(1.0, float(height)), 4),
        },
        'area_ratio': round(float(area_ratio), 4),
        'aspect_ratio': round(float(aspect), 3),
    }


def classify_vehicle_type(visual_profile: Dict) -> str:
    geometry = (visual_profile or {}).get('geometria', {})
    if not isinstance(geometry, dict):
        return 'indefinido'
    aspect = float(geometry.get('vehicle_aspect_ratio', 0.0))
    compact = bool(geometry.get('compact_vehicle'))
    view = str((visual_profile or {}).get('vista_detectada', 'indefinida'))
    if compact and aspect > 0 and aspect <= 2.0:
        return 'hatch'
    if aspect >= 2.3:
        return 'seda/picape'
    if view == 'traseira' and compact:
        return 'hatch'
    if aspect > 0:
        return 'compacto'
    return 'indefinido'


def infer_vehicle_category(visual_profile: Dict, vision_payload: Dict) -> Dict:
    scores = {
        'AUTOMOVEL': 35.0,
        'MOTOCICLETA': 27.0,
        'CAMINHAO': 27.0,
    }
    signals = []

    geometry = (visual_profile or {}).get('geometria', {})
    if not isinstance(geometry, dict):
        geometry = {}
    aspect = float(geometry.get('vehicle_aspect_ratio', 0.0))
    compact = bool(geometry.get('compact_vehicle'))
    view = normalize_text((visual_profile or {}).get('vista_detectada', 'indefinida'))

    if compact:
        scores['AUTOMOVEL'] += 8.0
        signals.append('geometria_compacta')
    if aspect >= 2.75:
        scores['CAMINHAO'] += 10.0
        signals.append('aspecto_longo_compativel_pesado')
    if 0.9 <= aspect <= 1.45 and not compact:
        scores['MOTOCICLETA'] += 9.0
        signals.append('aspecto_estreito_compativel_moto')
    if view in ('FRONTAL', 'TRASEIRA'):
        scores['AUTOMOVEL'] += 2.5

    text_samples = []
    principal = (visual_profile or {}).get('hipotese_principal', {})
    if isinstance(principal, dict):
        text_samples.extend([
            str(principal.get('fabricante', '') or ''),
            str(principal.get('modelo', '') or ''),
            str(principal.get('evidencias', '') or ''),
        ])
    for item in (visual_profile or {}).get('hipoteses', []) or []:
        if not isinstance(item, dict):
            continue
        text_samples.extend([
            str(item.get('fabricante', '') or ''),
            str(item.get('modelo', '') or ''),
            str(item.get('evidencias', '') or ''),
        ])

    if isinstance(vision_payload, dict):
        text_samples.extend([
            str(vision_payload.get('fabricante', '') or ''),
            str(vision_payload.get('modelo', '') or ''),
            str(vision_payload.get('tipo_veiculo', '') or ''),
        ])
        for candidate in (vision_payload.get('candidatos', []) or [])[:8]:
            if isinstance(candidate, dict):
                text_samples.extend([
                    str(candidate.get('fabricante', '') or ''),
                    str(candidate.get('modelo', '') or ''),
                    str(candidate.get('tipo_veiculo', '') or ''),
                    str(candidate.get('evidencias', '') or ''),
                ])

    flat_text = normalize_text(' '.join(text_samples))
    keyword_sets = {
        'AUTOMOVEL': (
            'HATCH',
            'SEDAN',
            'SUV',
            'PICAPE',
            'CARRO',
            'AUTOMOVEL',
            'ONIX',
            'HB20',
            'UNO',
            'MOBI',
            'GOL',
            'KWID',
        ),
        'MOTOCICLETA': (
            'MOTO',
            'MOTOCICLETA',
            'SCOOTER',
            'CG',
            'BIZ',
            'PCX',
            'XRE',
            'FAZER',
            'NMAX',
            'YAMAHA',
            'HONDA',
        ),
        'CAMINHAO': (
            'CAMINHAO',
            'TRUCK',
            'CARRETA',
            'CAVALO MECANICO',
            'ATEGO',
            'ACTROS',
            'SCANIA',
            'VOLVO',
            'TECTOR',
            'CONSTELLATION',
            'METEOR',
            'RODOTREM',
        ),
    }
    for category, keywords in keyword_sets.items():
        hits = 0
        for keyword in keywords:
            if keyword in flat_text:
                scores[category] += 2.6
                hits += 1
        if hits > 0:
            signals.append(f'keywords_{category.lower()}:{hits}')

    sorted_scores = sorted(scores.items(), key=lambda item: float(item[1]), reverse=True)
    top_category, top_score = sorted_scores[0]
    second_score = float(sorted_scores[1][1]) if len(sorted_scores) > 1 else 0.0
    total = max(1.0, float(sum(scores.values())))
    confidence = max(35.0, min(99.0, (top_score / total) * 100.0))
    if top_category != 'AUTOMOVEL' and (top_score - second_score) < 1.6 and top_score < 40.0:
        top_category = 'AUTOMOVEL'
        confidence = max(38.0, confidence - 8.0)
        signals.append('ambiguidade_categoria_forca_fallback_automovel')

    return {
        'categoria': top_category.lower(),
        'categoria_norm': top_category,
        'confianca': round(float(confidence), 2),
        'placar': {key.lower(): round(float(value), 2) for key, value in scores.items()},
        'sinais': signals[:10],
    }


def build_visual_feature_summary(visual_profile: Dict, category_context: Optional[Dict] = None) -> Dict:
    component_profile = (visual_profile or {}).get('assinaturas_componentes', {})
    if not isinstance(component_profile, dict):
        component_profile = {}
    components = component_profile.get('componentes', {})
    if not isinstance(components, dict):
        components = {}
    emblem = (visual_profile or {}).get('emblema', {})
    if not isinstance(emblem, dict):
        emblem = {}
    summary = {
        'logotipo_emblema': {
            'detectado': bool(emblem.get('detected')),
            'forma': str(emblem.get('shape', 'indefinido')),
            'cor': str(emblem.get('color_hint', 'indefinida')),
            'confianca': float(emblem.get('confidence', 0.0)),
        },
        'grade_frontal': components.get('grade_dianteira', {}),
        'farois': components.get('farois_dianteiros', {}),
        'lanternas': components.get('lanternas_traseiras', {}),
        'linhas_carroceria': components.get('linhas_portas', {}),
        'proporcao_carroceria': components.get('design_carroceria', {}),
        'tipo_veiculo': classify_vehicle_type(visual_profile),
        'categoria_veiculo': str((category_context or {}).get('categoria', 'automovel')),
        'confianca_categoria': float((category_context or {}).get('confianca', 0.0)),
    }
    return summary


def resize_for_vision(img):
    max_side = 1400
    height, width = img.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return img
    scale = max_side / float(longest)
    target_w = max(48, int(round(width * scale)))
    target_h = max(48, int(round(height * scale)))
    return cv2.resize(img, (target_w, target_h), interpolation=cv2.INTER_AREA)


def image_to_data_url(img) -> str:
    ok, encoded = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise RuntimeError('Falha ao codificar imagem para API de visao.')
    payload = base64.b64encode(encoded.tobytes()).decode('ascii')
    return 'data:image/jpeg;base64,' + payload


def extract_response_text(payload: Dict) -> str:
    output_text = str(payload.get('output_text', '') or '').strip()
    if output_text:
        return output_text

    chunks = []
    for item in payload.get('output', []) or []:
        for content in item.get('content', []) or []:
            text = str(content.get('text', '') or '').strip()
            if text:
                chunks.append(text)
    return '\n'.join(chunks).strip()


def extract_json_object(text: str) -> Dict:
    if not text:
        return {}
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    match = re.search(r'\{[\s\S]*\}', text)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def query_openai_vision(image, timeout_sec=35) -> Tuple[Dict, str]:
    api_key = (os.environ.get('OPENAI_API_KEY') or '').strip()
    if not api_key:
        return {}, 'OPENAI_API_KEY_nao_configurada'

    model = (os.environ.get('GROM_OCR_VISION_MODEL') or 'gpt-4.1-mini').strip()
    url = (os.environ.get('GROM_OCR_VISION_URL') or 'https://api.openai.com/v1/responses').strip()
    prompt = (
        'Analise visual automotiva forense. Retorne JSON estrito com campos: '
        'fabricante, modelo, ano_estimado, confianca_geral, candidatos (lista com fabricante, modelo, ano_estimado, confianca, evidencias). '
        'Se estiver incerto, marque confianca baixa e nao invente dados.'
    )

    data_url = image_to_data_url(resize_for_vision(image))
    payload = {
        'model': model,
        'temperature': 0.1,
        'max_output_tokens': 900,
        'input': [
            {
                'role': 'user',
                'content': [
                    {'type': 'input_text', 'text': prompt},
                    {'type': 'input_image', 'image_url': data_url},
                ],
            }
        ],
    }

    try:
        response = requests.post(
            url,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
            },
            json=payload,
            timeout=timeout_sec,
        )
    except Exception as exc:
        return {}, f'vision_request_error:{exc}'

    if response.status_code < 200 or response.status_code >= 300:
        return {}, f'vision_http_{response.status_code}'

    try:
        parsed = response.json()
    except Exception:
        return {}, 'vision_invalid_json'

    text = extract_response_text(parsed)
    result = extract_json_object(text)
    if not result:
        return {}, 'vision_empty_payload'
    return result, ''


def search_serpapi(query: str, count: int) -> Tuple[List[Dict], str]:
    api_key = (os.environ.get('SERPAPI_KEY') or '').strip()
    if not api_key:
        return [], 'SERPAPI_KEY_nao_configurada'

    try:
        response = requests.get(
            'https://serpapi.com/search.json',
            params={
                'engine': 'google',
                'q': query,
                'num': count,
                'hl': 'pt-BR',
                'gl': 'br',
                'api_key': api_key,
            },
            timeout=20,
        )
    except Exception as exc:
        return [], f'serpapi_request_error:{exc}'

    if response.status_code < 200 or response.status_code >= 300:
        return [], f'serpapi_http_{response.status_code}'

    try:
        payload = response.json()
    except Exception:
        return [], 'serpapi_invalid_json'

    pages = []
    for item in payload.get('organic_results', []) or []:
        pages.append({
            'title': str(item.get('title', '') or ''),
            'url': str(item.get('link', '') or ''),
            'snippet': str(item.get('snippet', '') or ''),
            'provider': 'serpapi',
        })
    return pages, ''


def search_brave(query: str, count: int) -> Tuple[List[Dict], str]:
    api_key = (os.environ.get('BRAVE_SEARCH_API_KEY') or '').strip()
    if not api_key:
        return [], 'BRAVE_SEARCH_API_KEY_nao_configurada'

    try:
        response = requests.get(
            'https://api.search.brave.com/res/v1/web/search',
            params={'q': query, 'count': count, 'country': 'BR'},
            headers={'X-Subscription-Token': api_key, 'Accept': 'application/json'},
            timeout=20,
        )
    except Exception as exc:
        return [], f'brave_request_error:{exc}'

    if response.status_code < 200 or response.status_code >= 300:
        return [], f'brave_http_{response.status_code}'

    try:
        payload = response.json()
    except Exception:
        return [], 'brave_invalid_json'

    pages = []
    for item in (((payload or {}).get('web') or {}).get('results') or []):
        pages.append({
            'title': str(item.get('title', '') or ''),
            'url': str(item.get('url', '') or ''),
            'snippet': str(item.get('description', '') or ''),
            'provider': 'brave',
        })
    return pages, ''


def search_google_cse(query: str, count: int) -> Tuple[List[Dict], str]:
    api_key = (os.environ.get('GOOGLE_API_KEY') or '').strip()
    cse_id = (os.environ.get('GOOGLE_CSE_ID') or '').strip()
    if not api_key or not cse_id:
        return [], 'GOOGLE_API_KEY_ou_GOOGLE_CSE_ID_nao_configurados'

    try:
        response = requests.get(
            'https://www.googleapis.com/customsearch/v1',
            params={'key': api_key, 'cx': cse_id, 'q': query, 'num': max(1, min(count, 10))},
            timeout=20,
        )
    except Exception as exc:
        return [], f'google_cse_request_error:{exc}'

    if response.status_code < 200 or response.status_code >= 300:
        return [], f'google_cse_http_{response.status_code}'

    try:
        payload = response.json()
    except Exception:
        return [], 'google_cse_invalid_json'

    pages = []
    for item in payload.get('items', []) or []:
        pages.append({
            'title': str(item.get('title', '') or ''),
            'url': str(item.get('link', '') or ''),
            'snippet': str(item.get('snippet', '') or ''),
            'provider': 'google_cse',
        })
    return pages, ''


def choose_search_provider(requested: str) -> str:
    if requested != 'auto':
        return requested
    if (os.environ.get('SERPAPI_KEY') or '').strip():
        return 'serpapi'
    if (os.environ.get('BRAVE_SEARCH_API_KEY') or '').strip():
        return 'brave'
    if (os.environ.get('GOOGLE_API_KEY') or '').strip() and (os.environ.get('GOOGLE_CSE_ID') or '').strip():
        return 'google_cse'
    return 'none'


def run_search_api(query: str, provider: str, count: int) -> Tuple[List[Dict], str]:
    if provider == 'serpapi':
        return search_serpapi(query, count)
    if provider == 'brave':
        return search_brave(query, count)
    if provider == 'google_cse':
        return search_google_cse(query, count)
    return [], 'search_provider_indisponivel'


def parse_year_range(text: str) -> Tuple[int, int]:
    raw = str(text or '')
    matches = [int(m.group(0)) for m in re.finditer(r'(19|20)\d{2}', raw)]
    if not matches:
        return 0, 0
    return min(matches), max(matches)


def new_candidate_entry(maker: str, model: str, year_hint='', default_category='AUTOMOVEL') -> Dict:
    maker_key = canonical_brand_name(maker)
    model_key = format_model_name(model)
    inferred_category = detect_candidate_category(maker_key, model_key, fallback=default_category)
    return {
        'fabricante': maker_key,
        'modelo': model_key,
        'categoria': normalize_category(inferred_category),
        'ano_estimado': str(year_hint or ''),
        'local_conf': 0.0,
        'vision_conf': 0.0,
        'base_conf': 0.0,
        'component_conf': 0.0,
        'web_conf': 0.0,
        'final_conf': 0.0,
        'evidencias': [],
        'fontes_consultadas': [],
        'synthetic_candidate': False,
    }


def build_initial_candidates(visual_profile: Dict, vision_payload: Dict, category_context: Optional[Dict] = None) -> List[Dict]:
    merged: Dict[Tuple[str, str], Dict] = {}
    default_category = normalize_category((category_context or {}).get('categoria_norm', 'AUTOMOVEL'))

    local_hypotheses = visual_profile.get('hipoteses', []) if isinstance(visual_profile, dict) else []
    if not isinstance(local_hypotheses, list):
        local_hypotheses = []
    for item in local_hypotheses[:8]:
        if not isinstance(item, dict):
            continue
        maker = str(item.get('fabricante', '')).strip()
        model = str(item.get('modelo', '')).strip()
        if not maker or not model:
            continue
        key = normalize_model_key(maker, model)
        entry = merged.setdefault(key, new_candidate_entry(maker, model, item.get('faixa_ano_modelo', ''), default_category))
        entry['local_conf'] = max(float(entry.get('local_conf', 0.0)), float(item.get('confianca', 0.0)))
        evidences = item.get('evidencias', [])
        if isinstance(evidences, list):
            entry['evidencias'].extend([str(x) for x in evidences if str(x).strip()])

    vision_candidates = vision_payload.get('candidatos', []) if isinstance(vision_payload, dict) else []
    if not isinstance(vision_candidates, list):
        vision_candidates = []
    for item in vision_candidates[:8]:
        if not isinstance(item, dict):
            continue
        maker = str(item.get('fabricante', '')).strip()
        model = str(item.get('modelo', '')).strip()
        if not maker or not model:
            continue
        key = normalize_model_key(maker, model)
        entry = merged.setdefault(key, new_candidate_entry(maker, model, item.get('ano_estimado', ''), default_category))
        entry['vision_conf'] = max(float(entry.get('vision_conf', 0.0)), float(item.get('confianca', 0.0)))
        if not entry.get('ano_estimado'):
            entry['ano_estimado'] = str(item.get('ano_estimado', '') or '')
        evidences = item.get('evidencias', [])
        if isinstance(evidences, list):
            entry['evidencias'].extend([str(x) for x in evidences if str(x).strip()])

    principal = (visual_profile or {}).get('hipotese_principal', {})
    if isinstance(principal, dict):
        maker = str(principal.get('fabricante', '')).strip()
        model = str(principal.get('modelo', '')).strip()
        if maker and model:
            key = normalize_model_key(maker, model)
            entry = merged.setdefault(
                key,
                new_candidate_entry(maker, model, principal.get('faixa_ano_modelo', ''), default_category),
            )
            entry['local_conf'] = max(float(entry.get('local_conf', 0.0)), float(principal.get('confianca', 0.0)))

    candidates = list(merged.values())
    if not candidates:
        category_map = get_category_brand_map(default_category)
        for brand, models in category_map.items():
            for model in models[:2]:
                key = normalize_model_key(brand, model)
                if key in merged:
                    continue
                seed = new_candidate_entry(brand, model, get_model_year_hint(brand, model), default_category)
                seed['base_conf'] = 12.0
                seed['local_conf'] = 12.0
                seed['synthetic_candidate'] = True
                seed['evidencias'] = ['seed_categoria_sem_hipotese_local']
                candidates.append(seed)
            if len(candidates) >= 3:
                break

    for item in candidates:
        local_conf = float(item.get('local_conf', 0.0))
        vision_conf = float(item.get('vision_conf', 0.0))
        if local_conf > 0.0 and vision_conf > 0.0:
            base = (local_conf * 0.62) + (vision_conf * 0.38)
        else:
            base = max(local_conf, vision_conf)
        item['base_conf'] = round(float(base), 2)
        item['evidencias'] = list(dict.fromkeys(item.get('evidencias', [])))[:8]
    return sorted(candidates, key=lambda x: float(x.get('base_conf', 0.0)), reverse=True)


def inject_similar_candidates(
    candidates: List[Dict],
    visual_profile: Dict,
    category_context: Optional[Dict] = None,
    min_candidates=3,
    max_candidates=5,
) -> List[Dict]:
    ranked = [dict(item) for item in (candidates or []) if isinstance(item, dict)]
    keys = {(normalize_model_key(item.get('fabricante', ''), item.get('modelo', ''))) for item in ranked}
    local_hypotheses = (visual_profile or {}).get('hipoteses', [])
    if not isinstance(local_hypotheses, list):
        local_hypotheses = []
    default_category = normalize_category((category_context or {}).get('categoria_norm', 'AUTOMOVEL'))

    if ranked:
        top = ranked[0]
        top_brand = canonical_brand_name(top.get('fabricante', ''))
        top_model = format_model_name(top.get('modelo', ''))
        top_category = normalize_category(top.get('categoria', default_category))
        pool = get_model_pool_for_brand(top_category, top_brand)
        for alt_model in pool:
            key = normalize_model_key(top_brand, alt_model)
            if key in keys:
                continue
            year_hint = get_model_year_hint(top_brand, alt_model)
            alt_conf = max(8.0, float(top.get('base_conf', 0.0)) * 0.72)
            evidences = [f'candidato_semelhante_{top_model.lower()}']
            synthetic = new_candidate_entry(top_brand, alt_model, year_hint, top_category)
            synthetic['local_conf'] = alt_conf
            synthetic['base_conf'] = round(float(alt_conf), 2)
            synthetic['synthetic_candidate'] = True
            synthetic['evidencias'] = evidences
            ranked.append(synthetic)
            keys.add(key)
            if len(ranked) >= min_candidates:
                break

    for item in local_hypotheses:
        if len(ranked) >= min_candidates:
            break
        if not isinstance(item, dict):
            continue
        maker = str(item.get('fabricante', '')).strip()
        model = str(item.get('modelo', '')).strip()
        if not maker or not model:
            continue
        key = normalize_model_key(maker, model)
        if key in keys:
            continue
        expanded = new_candidate_entry(maker, model, item.get('faixa_ano_modelo', ''), default_category)
        expanded['local_conf'] = float(item.get('confianca', 0.0)) * 0.75
        expanded['base_conf'] = round(float(item.get('confianca', 0.0)) * 0.75, 2)
        expanded['evidencias'] = ['hipotese_visual_ampliada']
        ranked.append(expanded)
        keys.add(key)

    if len(ranked) < min_candidates:
        category_map = get_category_brand_map(default_category)
        for brand, models in category_map.items():
            for model in models:
                key = normalize_model_key(brand, model)
                if key in keys:
                    continue
                synthetic = new_candidate_entry(brand, model, get_model_year_hint(brand, model), default_category)
                synthetic['local_conf'] = 10.0
                synthetic['base_conf'] = 10.0
                synthetic['synthetic_candidate'] = True
                synthetic['evidencias'] = ['seed_ampliacao_categoria']
                ranked.append(synthetic)
                keys.add(key)
                if len(ranked) >= min_candidates:
                    break
            if len(ranked) >= min_candidates:
                break

    ranked.sort(key=lambda x: float(x.get('base_conf', 0.0)), reverse=True)
    return ranked[:max(3, min(max_candidates, 5))]


def score_component_alignment(candidate: Dict, visual_profile: Dict) -> float:
    components = (((visual_profile or {}).get('assinaturas_componentes', {}) or {}).get('componentes', {}))
    if not isinstance(components, dict):
        return 0.0

    key = normalize_model_key(candidate.get('fabricante', ''), candidate.get('modelo', ''))
    rules = MODEL_SIGNATURE_RULES.get(key)
    category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
    if not rules:
        weights = CATEGORY_COMPONENT_WEIGHTS.get(category, {})
        if weights:
            total_weight = 0.0
            weighted_score = 0.0
            for component_name, weight in weights.items():
                item = components.get(component_name, {})
                total_weight += float(weight)
                if not isinstance(item, dict):
                    continue
                status = str(item.get('status', 'indefinido'))
                conf = float(item.get('confianca', 0.0))
                if status.startswith('limitado_vista'):
                    weighted_score += float(weight) * 0.45
                elif status not in ('indefinido', 'nao_detectado', 'nao_detectada', 'ausente'):
                    weighted_score += float(weight) * min(1.0, max(0.28, conf / 100.0))
                elif conf >= 36.0:
                    weighted_score += float(weight) * 0.22
            if total_weight > 0.0:
                return round((weighted_score / total_weight) * 100.0, 2)

        detected = 0
        assessed = 0
        for item in components.values():
            if not isinstance(item, dict):
                continue
            assessed += 1
            conf = float(item.get('confianca', 0.0))
            status = str(item.get('status', 'indefinido'))
            if conf >= 45.0 and status not in ('indefinido', 'nao_detectado', 'nao_detectada'):
                detected += 1
        return round((detected / max(1, assessed)) * 62.0 + 18.0, 2)

    total_weight = 0.0
    score = 0.0
    for component_name, rule in rules.items():
        total_weight += float(rule.get('weight', 0.0))
        item = components.get(component_name, {})
        if not isinstance(item, dict):
            continue
        status = str(item.get('status', 'indefinido'))
        conf = float(item.get('confianca', 0.0))
        if status in rule.get('statuses', set()):
            score += float(rule.get('weight', 0.0)) * min(1.0, max(0.3, conf / 100.0))
        elif status.startswith('limitado_vista'):
            score += float(rule.get('weight', 0.0)) * 0.45
        elif status in ('sinal_fraco', 'linha_parcial', 'fraca', 'parcial'):
            score += float(rule.get('weight', 0.0)) * 0.35
    if total_weight <= 0.0:
        return 0.0
    return round((score / total_weight) * 100.0, 2)


def evaluate_candidate_components(candidate: Dict, visual_profile: Dict) -> Dict:
    components = (((visual_profile or {}).get('assinaturas_componentes', {}) or {}).get('componentes', {}))
    if not isinstance(components, dict):
        components = {}

    key = normalize_model_key(candidate.get('fabricante', ''), candidate.get('modelo', ''))
    rules = MODEL_SIGNATURE_RULES.get(key, {})
    category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
    category_weights = CATEGORY_COMPONENT_WEIGHTS.get(category, {})
    score = score_component_alignment(candidate, visual_profile)
    matches = []
    mismatches = []
    limited = []

    if not rules and not category_weights:
        for component_name, item in components.items():
            if not isinstance(item, dict):
                continue
            status = str(item.get('status', 'indefinido'))
            conf = float(item.get('confianca', 0.0))
            if status.startswith('limitado_vista'):
                limited.append(f'{component_name}:{status}')
            elif conf >= 48.0 and status not in ('indefinido', 'nao_detectado', 'nao_detectada'):
                matches.append(f'{component_name}:{status}')
            else:
                mismatches.append(f'{component_name}:{status}')
    elif not rules and category_weights:
        for component_name in category_weights.keys():
            item = components.get(component_name, {})
            status = str(item.get('status', 'indefinido')) if isinstance(item, dict) else 'indefinido'
            conf = float(item.get('confianca', 0.0)) if isinstance(item, dict) else 0.0
            if status.startswith('limitado_vista'):
                limited.append(f'{component_name}:{status}')
                continue
            if status not in ('indefinido', 'nao_detectado', 'nao_detectada', 'ausente') and conf >= 40.0:
                matches.append(f'{component_name}:{status}')
            else:
                mismatches.append(f'{component_name}:{status}')
    else:
        for component_name, rule in rules.items():
            item = components.get(component_name, {})
            status = str(item.get('status', 'indefinido')) if isinstance(item, dict) else 'indefinido'
            conf = float(item.get('confianca', 0.0)) if isinstance(item, dict) else 0.0
            if status.startswith('limitado_vista'):
                limited.append(f'{component_name}:{status}')
                continue
            if status in rule.get('statuses', set()) and conf >= 42.0:
                matches.append(f'{component_name}:{status}')
            else:
                mismatches.append(f'{component_name}:{status}')

    return {
        'score': round(float(score), 2),
        'matches': matches[:8],
        'mismatches': mismatches[:8],
        'limited': limited[:6],
    }


def get_similar_models_for_candidate(candidate: Dict, candidate_pool: List[Dict]) -> set:
    maker = canonical_brand_name(candidate.get('fabricante', ''))
    model = format_model_name(candidate.get('modelo', ''))
    category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
    similar_models = {format_model_name(item) for item in get_model_pool_for_brand(category, maker)}
    for item in candidate_pool:
        if not isinstance(item, dict):
            continue
        if canonical_brand_name(item.get('fabricante', '')) == maker:
            similar_models.add(format_model_name(item.get('modelo', '')))
    if model in similar_models:
        similar_models.remove(model)
    return similar_models


def evaluate_web_confirmation(candidate: Dict, pages: List[Dict], candidate_pool: List[Dict]) -> Dict:
    maker = canonical_brand_name(candidate.get('fabricante', ''))
    model = format_model_name(candidate.get('modelo', ''))
    category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
    similar_models = get_similar_models_for_candidate(candidate, candidate_pool)

    category_keywords = {
        'AUTOMOVEL': {'CARRO', 'AUTOMOVEL', 'HATCH', 'SEDAN', 'SUV', 'PICAPE'},
        'MOTOCICLETA': {'MOTO', 'MOTOCICLETA', 'SCOOTER', 'NAKED', 'TRAIL'},
        'CAMINHAO': {'CAMINHAO', 'TRUCK', 'CARRETA', 'CAVALO MECANICO', 'RODOTREM'},
    }
    category_terms = category_keywords.get(category, set())

    confirmations = {}
    conflicts = {}
    category_support = 0
    for page in pages:
        text = normalize_text(' '.join([page.get('title', ''), page.get('snippet', ''), page.get('url', '')]))
        domain = parse_domain(page.get('url', ''))
        page_score = float(page.get('score', 0.0))
        if not domain:
            continue

        has_model = bool(model and model in text)
        has_maker = bool(maker and maker in text)
        has_category_keyword = any(keyword in text for keyword in category_terms)
        if has_category_keyword:
            category_support += 1
            page_score += 0.8

        if has_maker and has_model and page_score >= 7.2:
            confirmations[domain] = max(float(confirmations.get(domain, 0.0)), page_score)

        if has_maker:
            for other in similar_models:
                if other and other in text and not has_model and page_score >= 7.0:
                    conflicts[domain] = max(float(conflicts.get(domain, 0.0)), page_score)
                    break

    confirmation_count = len(confirmations)
    conflict_count = len(conflicts)
    confirmation_strength = np.mean(list(confirmations.values())) if confirmations else 0.0
    conflict_strength = np.mean(list(conflicts.values())) if conflicts else 0.0

    web_conf = (confirmation_count * 16.0) + (float(confirmation_strength) * 5.2) + (min(4, category_support) * 2.2)
    web_conf -= (conflict_count * 9.5) + (float(conflict_strength) * 2.8)
    web_conf = max(0.0, min(99.0, web_conf))

    reasons = []
    if confirmation_count == 0:
        reasons.append('sem_confirmacao_independente_em_fontes_abertas')
    if conflict_count > 0:
        reasons.append('fontes_apontam_modelos_semelhantes_em_conflito')
    if category_support == 0:
        reasons.append('fontes_sem_contexto_claro_de_categoria_veicular')

    return {
        'score': round(float(web_conf), 2),
        'confirmation_count': int(confirmation_count),
        'conflict_count': int(conflict_count),
        'category_support_count': int(category_support),
        'confirmation_domains': sorted(confirmations.keys()),
        'conflict_domains': sorted(conflicts.keys()),
        'reasons': reasons,
    }


def build_discarded_models(ranked_candidates: List[Dict]) -> List[Dict]:
    if not ranked_candidates:
        return []
    best = ranked_candidates[0]
    best_conf = float(best.get('final_conf', 0.0))

    discarded = []
    for item in ranked_candidates[1:]:
        conf = float(item.get('final_conf', 0.0))
        reasons = []
        if conf <= (best_conf - 6.0):
            reasons.append('confianca_global_inferior_ao_melhor_candidato')
        component_eval = item.get('component_eval', {})
        if isinstance(component_eval, dict) and component_eval.get('mismatches'):
            reasons.append('divergencia_de_componentes_visuais')
        web_eval = item.get('web_eval', {})
        if isinstance(web_eval, dict):
            if int(web_eval.get('confirmation_count', 0)) < int((best.get('web_eval', {}) or {}).get('confirmation_count', 0)):
                reasons.append('menos_confirmacoes_independentes')
            if int(web_eval.get('conflict_count', 0)) > 0:
                reasons.append('conflito_com_modelos_semelhantes')
        if bool(item.get('synthetic_candidate')):
            reasons.append('candidato_expandido_por_semelhanca_sem_confirmacao_suficiente')
        if not reasons and conf < 55.0:
            reasons.append('baixo_desempenho_no_ranqueamento_cruzado')
        discarded.append({
            'fabricante': str(item.get('fabricante', '')),
            'modelo': str(item.get('modelo', '')),
            'ano_estimado': str(item.get('ano_estimado', '-') or '-'),
            'confianca': round(float(conf), 2),
            'motivos': list(dict.fromkeys(reasons)),
        })
    return discarded[:5]


def build_queries(candidate: Dict) -> List[Tuple[str, str]]:
    maker = canonical_brand_name(candidate.get('fabricante', ''))
    model = format_model_name(candidate.get('modelo', ''))
    category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
    base = f'{maker} {model}'.strip()
    brand_domain = primary_brand_domain(maker)
    category_site_queries = {
        'AUTOMOVEL': [
            f'site:quatrorodas.abril.com.br {base} teste',
            f'site:motor1.uol.com.br {base} teste',
            f'site:webmotors.com.br {base} fotos',
            f'site:carrosnaweb.com.br {base} ficha tecnica',
        ],
        'MOTOCICLETA': [
            f'site:motoo.com.br {base} teste',
            f'site:motonline.com.br {base} ficha tecnica',
            f'site:webmotors.com.br/motos {base}',
            f'site:olx.com.br {base} moto',
        ],
        'CAMINHAO': [
            f'site:caminhoes-e-carretas.com {base} ficha tecnica',
            f'site:blogdocaminhoneiro.com {base}',
            f'site:estradao.estadao.com.br {base}',
            f'site:olx.com.br {base} caminhao',
        ],
    }
    queries = [
        (f'{base} ficha tecnica comparativo visual', 'geral'),
        (f'{base} farol grade lanterna emblema', 'geral'),
        (f'{base} anuncios compra venda fotos', 'geral'),
        (f'{base} forum clube proprietarios', 'geral'),
        (f'{base} manual do proprietario pdf', 'geral'),
        (f'{base} concessionaria catalogo oficial', 'geral'),
        (f'{base} yahoosearch imagens referencia', 'geral'),
    ]
    visual_reference_specs = visual_reference_catalog_module.build_visual_reference_query_specs(
        maker,
        model,
        category=category,
        model_conclusive=bool(maker and model),
    )
    queries.extend(visual_reference_specs)
    if brand_domain:
        queries.append((f'site:{brand_domain} {base} catalogo oficial', 'geral'))
        queries.append((f'site:{brand_domain} {base} manual', 'geral'))

    for query in category_site_queries.get(category, []):
        queries.append((query, 'geral'))

    merged_component_terms = dict(COMPONENT_QUERY_TERMS)
    merged_component_terms.update(category_component_terms(category))
    for component_name, terms in merged_component_terms.items():
        queries.append((f'{base} {terms}', component_name))

    deduped = []
    seen = set()
    for query_text, component_hint in queries:
        key = (normalize_text(query_text), normalize_text(component_hint))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((query_text, component_hint))
    return deduped[:16]


def score_page_for_candidate(page: Dict, candidate: Dict, component_hint: str) -> float:
    text = normalize_text(' '.join([page.get('title', ''), page.get('snippet', ''), page.get('url', '')]))
    maker = normalize_text(candidate.get('fabricante', ''))
    model = normalize_text(candidate.get('modelo', ''))
    domain = parse_domain(page.get('url', ''))

    score = trusted_domain_weight(domain)
    if maker and maker in text:
        score += 4.0
    if model and model in text:
        score += 6.0
    else:
        model_tokens = [x for x in model.split(' ') if len(x) > 1]
        for token in model_tokens:
            if token in text:
                score += 1.4

    if component_hint and component_hint != 'geral':
        category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
        merged_terms = dict(COMPONENT_QUERY_TERMS)
        merged_terms.update(category_component_terms(category))
        terms = normalize_text(merged_terms.get(component_hint, '')).split(' ')
        for token in terms:
            if token and token in text:
                score += 0.8

    year_min, year_max = parse_year_range(str(candidate.get('ano_estimado', '')))
    if year_min > 0 and year_max > 0:
        for match in re.finditer(r'(19|20)\d{2}', text):
            year = int(match.group(0))
            if year_min <= year <= year_max:
                score += 1.6
                break
    return round(float(score), 3)


def collect_web_evidence(candidate: Dict, provider: str, max_results: int) -> Tuple[List[Dict], List[str]]:
    all_pages = []
    warnings = []
    seen_urls = set()
    for query, component_hint in build_queries(candidate):
        pages, error = run_search_api(query, provider, max_results)
        if error:
            warnings.append(error)
            continue
        for page in pages:
            url = str(page.get('url', '')).strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            page['component_hint'] = component_hint
            if is_specialized_page(page):
                page['score'] = score_page_for_candidate(page, candidate, component_hint)
                all_pages.append(page)

    all_pages.sort(key=lambda item: float(item.get('score', 0.0)), reverse=True)
    return all_pages[:14], list(dict.fromkeys(warnings))


def summarize_sources(pages: List[Dict], limit=8) -> List[str]:
    lines = []
    for item in pages[:limit]:
        title = str(item.get('title', '')).strip() or '-'
        url = str(item.get('url', '')).strip()
        domain = parse_domain(url)
        score = float(item.get('score', 0.0))
        lines.append(f'{domain} | score={score:.1f} | {title} | {url}')
    return lines


def build_fallback_sources_for_candidate(candidate: Dict, limit=12) -> List[str]:
    maker = canonical_brand_name(candidate.get('fabricante', ''))
    model = format_model_name(candidate.get('modelo', ''))
    category = normalize_category(candidate.get('categoria', 'AUTOMOVEL'))
    base = f'{maker} {model}'.strip()
    brand_domain = primary_brand_domain(maker)

    category_queries = {
        'AUTOMOVEL': [
            ('quatro_rodas', f'https://www.google.com/search?q={quote_plus("site:quatrorodas.abril.com.br " + base + " teste")}'),
            ('motor1', f'https://www.google.com/search?q={quote_plus("site:motor1.uol.com.br " + base)}'),
            ('webmotors', f'https://www.webmotors.com.br/carros/estoque?marca={quote_plus(maker)}&modelo={quote_plus(model)}'),
            ('olx', f'https://www.google.com/search?q={quote_plus("site:olx.com.br " + base)}'),
        ],
        'MOTOCICLETA': [
            ('motoo', f'https://www.google.com/search?q={quote_plus("site:motoo.com.br " + base)}'),
            ('motonline', f'https://www.google.com/search?q={quote_plus("site:motonline.com.br " + base)}'),
            ('webmotors_motos', f'https://www.google.com/search?q={quote_plus("site:webmotors.com.br/motos " + base)}'),
            ('mercadolivre_motos', f'https://www.google.com/search?q={quote_plus("site:mercadolivre.com.br " + base + " moto")}'),
        ],
        'CAMINHAO': [
            ('caminhoes_carretas', f'https://www.google.com/search?q={quote_plus("site:caminhoes-e-carretas.com " + base)}'),
            ('blog_caminhoneiro', f'https://www.google.com/search?q={quote_plus("site:blogdocaminhoneiro.com " + base)}'),
            ('estradao', f'https://www.google.com/search?q={quote_plus("site:estradao.estadao.com.br " + base)}'),
            ('olx_caminhao', f'https://www.google.com/search?q={quote_plus("site:olx.com.br " + base + " caminhao")}'),
        ],
    }

    queries = [
        ('manual_proprietario', f'https://www.google.com/search?q={quote_plus(base + " manual do proprietario pdf")}'),
        ('concessionaria', f'https://www.google.com/search?q={quote_plus(base + " concessionaria catalogo oficial")}'),
        ('forum', f'https://www.google.com/search?q={quote_plus(base + " forum clube")}'),
        ('google_imagens', f'https://www.google.com/search?tbm=isch&q={quote_plus(base + " detalhes visuais farol lanterna grade emblema")}'),
        ('yahoo_busca', f'https://search.yahoo.com/search?p={quote_plus(base + " ficha tecnica")}'),
        ('yahoo_imagens', f'https://images.search.yahoo.com/search/images?p={quote_plus(base + " detalhes visuais")}'),
    ]
    if brand_domain:
        queries.append(('site_fabricante', f'https://www.google.com/search?q={quote_plus("site:" + brand_domain + " " + base)}'))
    queries.extend(category_queries.get(category, []))
    visual_reference_sources = visual_reference_catalog_module.build_visual_reference_sources(
        maker,
        model,
        category=category,
        model_conclusive=bool(maker and model),
    )
    for source in visual_reference_sources[:10]:
        if not isinstance(source, dict):
            continue
        label = str(source.get('fonte', source.get('nome', 'visual_reference'))).strip() or 'visual_reference'
        url = str(source.get('url', '')).strip()
        if label and url:
            queries.append((label, url))
    lines = [f'{label} | {url}' for label, url in queries if url]
    return lines[:max(4, min(limit, 20))]


def candidate_category_alignment(candidate: Dict, category_context: Dict) -> float:
    inferred = normalize_category((category_context or {}).get('categoria_norm', 'AUTOMOVEL'))
    inferred_conf = float((category_context or {}).get('confianca', 0.0))
    candidate_category = normalize_category(candidate.get('categoria', inferred))
    if candidate_category == inferred:
        return round(min(4.8, max(0.6, inferred_conf / 22.0)), 2)
    if inferred_conf >= 62.0:
        return -8.0
    if inferred_conf >= 48.0:
        return -4.5
    return -2.0


def build_result_payload(image_path: str, provider: str, use_vision_service: bool, max_web_results: int) -> Dict:
    img = cv2.imread(image_path)
    if img is None:
        raise RuntimeError('Nao foi possivel abrir a imagem informada.')

    preprocessed_img, preprocess_meta = preprocess_vehicle_image(img)
    roi_img, roi_meta = detect_vehicle_roi(preprocessed_img)

    local_profile_roi = ocr_agent.analyze_vehicle_visual_profile(roi_img)
    local_profile_full = ocr_agent.analyze_vehicle_visual_profile(preprocessed_img)
    roi_conf = float(((local_profile_roi or {}).get('hipotese_principal', {}) or {}).get('confianca', 0.0))
    full_conf = float(((local_profile_full or {}).get('hipotese_principal', {}) or {}).get('confianca', 0.0))
    local_profile = local_profile_roi if roi_conf >= (full_conf - 1.2) else local_profile_full
    selected_scope = 'roi' if local_profile is local_profile_roi else 'full'

    vision_payload = {}
    vision_warning = ''
    if use_vision_service:
        vision_source = roi_img if selected_scope == 'roi' and roi_img is not None else preprocessed_img
        vision_payload, vision_warning = query_openai_vision(vision_source)

    category_context = infer_vehicle_category(local_profile, vision_payload)
    visual_features = build_visual_feature_summary(local_profile, category_context)

    candidates = build_initial_candidates(local_profile, vision_payload, category_context)
    candidates = inject_similar_candidates(candidates, local_profile, category_context, min_candidates=3, max_candidates=5)
    if not candidates:
        return {
            'status': 'inconclusivo',
            'mensagem': 'Nao foi possivel formar candidatos tecnicos confiaveis.',
            'fabricante': '',
            'modelo': '',
            'ano_estimado': '',
            'categoria_veiculo': str(category_context.get('categoria', 'automovel')),
            'candidatos': [],
            'modelos_descartados': [],
            'fontes_consultadas': [],
            'avisos': ['sem_candidatos_iniciais'],
        }

    warnings = []
    if vision_warning:
        warnings.append(vision_warning)

    for candidate in candidates[:5]:
        candidate['categoria'] = normalize_category(
            candidate.get(
                'categoria',
                detect_candidate_category(candidate.get('fabricante', ''), candidate.get('modelo', ''), category_context.get('categoria_norm', 'AUTOMOVEL')),
            )
        )
        component_eval = evaluate_candidate_components(candidate, local_profile)
        candidate['component_eval'] = component_eval
        candidate['component_conf'] = float(component_eval.get('score', 0.0))
        pages, search_warnings = collect_web_evidence(candidate, provider, max_web_results)
        candidate['fontes_consultadas'] = summarize_sources(pages, limit=10)
        web_eval = evaluate_web_confirmation(candidate, pages, candidates)
        candidate['web_eval'] = web_eval
        candidate['web_conf'] = round(float(web_eval.get('score', 0.0)), 2)
        if not pages:
            candidate['evidencias'].append('sem_fontes_especializadas_via_api')
        warnings.extend(search_warnings)

        base_conf = float(candidate.get('base_conf', 0.0))
        component_conf = float(candidate.get('component_conf', 0.0))
        if provider == 'none':
            final = (base_conf * 0.56) + (component_conf * 0.44)
        else:
            final = (
                (base_conf * 0.34)
                + (component_conf * 0.33)
                + (float(candidate.get('web_conf', 0.0)) * 0.33)
                + (float(web_eval.get('confirmation_count', 0)) * 2.0)
                - (float(web_eval.get('conflict_count', 0)) * 2.2)
            )
        final += candidate_category_alignment(candidate, category_context)
        if isinstance(component_eval, dict) and len(component_eval.get('mismatches', [])) >= 3:
            final -= 5.0
        if bool(candidate.get('synthetic_candidate')):
            final -= 10.0
        candidate['final_conf'] = round(float(min(99.0, max(0.0, final))), 2)
        candidate['evidencias'] = list(dict.fromkeys(candidate.get('evidencias', [])))[:10]
        if normalize_category(candidate.get('categoria', 'AUTOMOVEL')) != normalize_category(category_context.get('categoria_norm', 'AUTOMOVEL')):
            candidate['evidencias'].append('categoria_candidato_diverge_da_categoria_inferida')
        if isinstance(web_eval, dict):
            candidate['evidencias'].extend(list(web_eval.get('reasons', [])))
            candidate['evidencias'] = list(dict.fromkeys(candidate.get('evidencias', [])))[:12]

    ranked = sorted(candidates, key=lambda x: float(x.get('final_conf', 0.0)), reverse=True)
    best = ranked[0]
    second = ranked[1] if len(ranked) > 1 else None
    gap = float(best.get('final_conf', 0.0)) - float(second.get('final_conf', 0.0)) if second else 99.0
    uncertain = float(best.get('final_conf', 0.0)) < 80.0 or gap < 6.0
    if float(category_context.get('confianca', 0.0)) < 52.0:
        uncertain = True
        warnings.append('categoria_veicular_com_baixa_confianca')

    if uncertain:
        warnings.append('identificacao_visual_inconclusiva')
        warnings.append('Identificacao com baixa confianca. Recomenda-se verificacao manual.')

    sources = best.get('fontes_consultadas', [])
    if not sources:
        sources.extend(build_fallback_sources_for_candidate(best, limit=12))
    sources = list(dict.fromkeys(sources))[:12]
    discarded = build_discarded_models(ranked)
    best_web_eval = best.get('web_eval', {}) if isinstance(best.get('web_eval', {}), dict) else {}
    best_component_eval = best.get('component_eval', {}) if isinstance(best.get('component_eval', {}), dict) else {}
    cross_validation_summary = {
        'independent_confirmations': int(best_web_eval.get('confirmation_count', 0)),
        'conflicting_sources': int(best_web_eval.get('conflict_count', 0)),
        'component_mismatches': int(len(best_component_eval.get('mismatches', []))),
    }

    return {
        'status': 'incerto' if uncertain else 'ok',
        'fabricante': str(best.get('fabricante', '')),
        'modelo': str(best.get('modelo', '')),
        'ano_estimado': str(best.get('ano_estimado', '') or '-'),
        'categoria_veiculo': str(normalize_category(best.get('categoria', category_context.get('categoria_norm', 'AUTOMOVEL'))).lower()),
        'confianca_final': float(best.get('final_conf', 0.0)),
        'confianca_base': float(best.get('base_conf', 0.0)),
        'confianca_componentes': float(best.get('component_conf', 0.0)),
        'confianca_fontes_abertas': float(best.get('web_conf', 0.0)),
        'gap_top2': round(float(gap), 2),
        'candidatos': ranked[:5],
        'modelos_descartados': discarded,
        'fontes_consultadas': sources,
        'etapas': {
            'entrada_preprocessamento': {
                'source_image': image_path,
                'preprocess': preprocess_meta,
                'vehicle_roi': roi_meta,
                'profile_scope': selected_scope,
            },
            'analise_visual_inicial': visual_features,
            'validacao_cruzada': cross_validation_summary,
            'categoria_veiculo': category_context,
        },
        'visual_profile': local_profile,
        'vision_service': vision_payload,
        'categoria_contexto': category_context,
        'avisos': list(dict.fromkeys(warnings)),
    }


def render_text_report(payload: Dict) -> str:
    lines = []
    lines.append('Possiveis modelos (nivel de confianca):')
    candidates = payload.get('candidatos', [])
    if not isinstance(candidates, list) or not candidates:
        lines.append('- Nenhum candidato suficiente.')
    else:
        for idx, item in enumerate(candidates, start=1):
            maker = str(item.get('fabricante', '-'))
            model = str(item.get('modelo', '-'))
            year = str(item.get('ano_estimado', '-') or '-')
            conf = float(item.get('final_conf', 0.0))
            category = str(normalize_category(item.get('categoria', 'AUTOMOVEL')).lower())
            lines.append(f'{idx}. {maker}/{model} | confianca={conf:.1f}% | ano={year} | categoria={category}')

    lines.append('')
    lines.append('Categoria do veiculo:')
    lines.append(str(payload.get('categoria_veiculo', 'automovel')))
    lines.append('')
    lines.append('Fabricante:')
    maker = str(payload.get('fabricante', '') or '-')
    if payload.get('status') != 'ok':
        maker += ' (incerto)'
    lines.append(maker)
    lines.append('')
    lines.append('Modelo:')
    model = str(payload.get('modelo', '') or '-')
    if payload.get('status') != 'ok':
        model += ' (incerto)'
    lines.append(model)
    lines.append('')
    lines.append('Ano estimado:')
    lines.append(str(payload.get('ano_estimado', '-') or '-'))
    lines.append('')
    lines.append('Nivel de confianca (%):')
    lines.append(f"{float(payload.get('confianca_final', 0.0)):.1f}%")
    lines.append('')
    lines.append('Validacao cruzada:')
    stages = payload.get('etapas', {})
    cross = stages.get('validacao_cruzada', {}) if isinstance(stages, dict) else {}
    lines.append(
        f"- confirmacoes_independentes={int((cross or {}).get('independent_confirmations', 0))} | "
        f"fontes_conflitantes={int((cross or {}).get('conflicting_sources', 0))} | "
        f"mismatches_componentes={int((cross or {}).get('component_mismatches', 0))}"
    )

    discarded = payload.get('modelos_descartados', [])
    lines.append('')
    lines.append('Modelos descartados e motivo:')
    if isinstance(discarded, list) and discarded:
        for item in discarded:
            if not isinstance(item, dict):
                continue
            maker_d = str(item.get('fabricante', '-'))
            model_d = str(item.get('modelo', '-'))
            conf_d = float(item.get('confianca', 0.0))
            reasons = item.get('motivos', [])
            reason_txt = ', '.join([str(x) for x in reasons]) if isinstance(reasons, list) and reasons else 'sem_motivo_tecnico'
            lines.append(f"- {maker_d}/{model_d} ({conf_d:.1f}%): {reason_txt}")
    else:
        lines.append('- Nenhum modelo descartado formalmente.')

    lines.append('')
    lines.append('Fontes consultadas:')
    sources = payload.get('fontes_consultadas', [])
    if isinstance(sources, list) and sources:
        for item in sources:
            lines.append(f'- {item}')
    else:
        lines.append('- Nenhuma fonte especializada retornada via API de busca.')

    if float(payload.get('confianca_final', 0.0)) < 80.0:
        lines.append('')
        lines.append('Aviso de incerteza:')
        lines.append('Identificacao com baixa confianca. Recomenda-se verificacao manual.')

    warnings = payload.get('avisos', [])
    if isinstance(warnings, list) and warnings:
        lines.append('')
        lines.append('Observacoes de incerteza/execucao:')
        for item in warnings[:8]:
            lines.append(f'- {item}')
    return '\n'.join(lines).strip()


def main():
    parser = argparse.ArgumentParser(
        description='Investigador visual de fabricante/modelo com comparacao entre modelos parecidos e validacao por fontes abertas.'
    )
    parser.add_argument('image', help='Caminho da imagem de entrada')
    parser.add_argument('--search-provider', choices=['auto', 'serpapi', 'brave', 'google_cse', 'none'], default='auto')
    parser.add_argument('--max-web-results', type=int, default=8)
    parser.add_argument('--skip-vision-service', action='store_true', help='Nao usa API externa de reconhecimento visual')
    parser.add_argument('--output-json', default='', help='Arquivo para salvar saida JSON completa')
    args = parser.parse_args()

    image_path = str(Path(args.image).expanduser().resolve())
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f'Arquivo nao encontrado: {image_path}')

    provider = choose_search_provider(args.search_provider)
    payload = build_result_payload(
        image_path=image_path,
        provider=provider,
        use_vision_service=not args.skip_vision_service,
        max_web_results=max(3, min(args.max_web_results, 12)),
    )
    payload['search_provider'] = provider
    payload['image_path'] = image_path

    print(render_text_report(payload))
    if args.output_json:
        output_path = str(Path(args.output_json).expanduser().resolve())
        with open(output_path, 'w', encoding='utf-8') as fp:
            json.dump(payload, fp, ensure_ascii=False, indent=2)
        print(f'\nJSON salvo em: {output_path}')


if __name__ == '__main__':
    main()
