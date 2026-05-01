"""Human-readable labels for pericial reports and dashboards."""

from __future__ import annotations

import re
import unicodedata


_LABEL_MAP = {
    'A': 'Boa',
    'B': 'Razoável',
    'C': 'Ruim',
    'D': 'Imprópria',
    'ALTA': 'Alta',
    'ATENCAO': 'Atenção',
    'ATENÇÃO': 'Atenção',
    'BAIXA': 'Baixa',
    'BALANCED': 'Balanceado',
    'BACKLIT': 'Contraluz',
    'BLURRED': 'Borrado',
    'BRIGHT': 'Muito claro',
    'BOA': 'Boa',
    'AVAILABLE': 'Disponivel',
    'CONFIGURED': 'Configurado',
    'ENHANCED': 'Aprimorado',
    'ORIGINAL': 'Original',
    'FILE': 'Arquivo',
    'IMAGE': 'Imagem',
    'PDF': 'PDF',
    'PNG': 'PNG',
    'JPG': 'JPG',
    'JPEG': 'JPEG',
    'WEBP': 'WEBP',
    'TIFF': 'TIFF',
    'BMP': 'BMP',
    'OPENCV': 'OpenCV',
    'PILLOW': 'Pillow',
    'HEURISTIC': 'Heuristica',
    'CENTER_GUESS': 'Estimativa central',
    'LOWER_WIDE_FOCUS': 'Foco amplo inferior',
    'RAW_CENTER_GUESS': 'Corte central bruto',
    'RAW_WIDE_FOCUS': 'Foco amplo bruto',
    'SCENE_PROFILE_SELECTED_VARIANT': 'Variante priorizada pelo perfil da cena',
    'SCENE_PROFILE_KEPT_ORIGINAL': 'Imagem original preservada',
    'SCENE_PROFILE_KEPT_ORIGINAL_BY_MARGIN': 'Imagem original preservada por margem',
    'PILLOW_AUTOCONTRAST': 'Pillow - autocontraste',
    'PILLOW_BRIGHTNESS_DOWN': 'Pillow - brilho reduzido',
    'PILLOW_BRIGHTNESS_UP': 'Pillow - brilho aumentado',
    'PILLOW_CONTRAST_UP': 'Pillow - contraste aumentado',
    'PILLOW_DETAIL': 'Pillow - detalhe',
    'PILLOW_EDGE_ENHANCE': 'Pillow - realce de bordas',
    'PILLOW_EQUALIZE': 'Pillow - equalizacao',
    'PILLOW_MEDIAN': 'Pillow - mediana',
    'PILLOW_SHARPEN': 'Pillow - nitidez',
    'PILLOW_SHARPNESS_UP': 'Pillow - nitidez reforcada',
    'PILLOW_UNSHARP': 'Pillow - nitidez reforcada',
    'GRAY_WORLD_BALANCE': 'OpenCV - balanco de cinza',
    'GRAY_WORLD_BILATERAL': 'OpenCV - bilateral',
    'GRAY_WORLD_BLACKHAT': 'OpenCV - blackhat',
    'GRAY_WORLD_CLAHE_1_8': 'OpenCV - CLAHE',
    'GRAY_WORLD_DENOISE': 'OpenCV - reducao de ruido',
    'GRAY_WORLD_EQUALIZE': 'OpenCV - equalizacao',
    'GRAY_WORLD_GAMMA': 'OpenCV - gamma',
    'GRAY_WORLD_MEDIAN': 'OpenCV - mediana',
    'GRAY_WORLD_SHARPEN': 'OpenCV - nitidez',
    'GRAY_WORLD_TOPHAT': 'OpenCV - tophat',
    'DARK': 'Escuro',
    'EMPTY_SCENE': 'Cena vazia',
    'CONFIRMADO_MANUAL': 'Ratificada manualmente',
    'CORRIGIDO_MANUAL': 'Ratificada com ajuste',
    'REGISTRADO': 'Registrado em conferencia',
    'CONFERENCIA_HUMANA': 'Conferencia tecnico-pericial',
    'CONFERENCIA_TECNICO_PERICIAL': 'Conferencia tecnico-pericial',
    'CONFERENCIA_TECNICO_PERICIAL_REGISTRADA': 'Conferencia tecnico-pericial registrada',
    'PRE_ANALISE_TECNICO_PERICIAL': 'Pre-analise tecnico-pericial',
    'ANALISE_TECNICO_PERICIAL': 'Analise tecnico-pericial',
    'RESULTADO_FINAL': 'Resultado final',
    'LAUDO_FINAL': 'Laudo final',
    'RATIFICADA_MANUALMENTE': 'Ratificada manualmente',
    'RATIFICADA_COM_AJUSTE': 'Ratificada com ajuste',
    'MOTORES_OCR_EMPREGADOS': 'Motores OCR empregados',
    'FONTE_COMPLEMENTAR_AUDITAVEL': 'Fonte complementar auditavel',
    'FONTES_COMPLEMENTARES_AUDITAVEIS': 'Fontes complementares auditaveis',
    'VALIDACAO_TECNICO_PERICIAL_AUTOMATIZADA': 'Validacao tecnico-pericial automatizada',
    'CADEIA_DE_CUSTODIA_TECNICO_DIGITAL': 'Cadeia de custodia tecnico-digital',
    'CLASSIFICACAO_TECNICO_PROBATORIA': 'Classificacao tecnico-probatoria',
    'GLARE': 'Reflexo intenso',
    'LOW_CONTRAST': 'Baixo contraste',
    'MOTION_BLUR': 'Borrado por movimento',
    'NOISY': 'Ruidoso',
    'OVEREXPOSED': 'Estourado',
    'PARTIAL': 'Parcial',
    'READY': 'Pronto',
    'UNDEREXPOSED': 'Subexposto',
    'BLOCKED': 'Bloqueado',
    'COMPATIVEL': 'Compatível',
    'COMPATIVEL_PARCIAL': 'Compatível parcial (forense)',
    'CONCLUSIVO': 'Conclusivo',
    'DARK': 'Escuro',
    'EMPTY_SCENE': 'Cena vazia',
    'GLARE': 'Reflexo intenso',
    'LOW_CONTRAST': 'Baixo contraste',
    'MOTION_BLUR': 'Borrado por movimento',
    'NOISY': 'Ruidoso',
    'OVEREXPOSED': 'Estourado',
    'PARTIAL': 'Parcial',
    'READY': 'Pronto',
    'UNDEREXPOSED': 'Subexposto',
    'CRITICA': 'Crítica',
    'CRÍTICA': 'Crítica',
    'EXCELENTE': 'Excelente',
    'FORTEMENTE_COMPATIVEL': 'Fortemente compatível',
    'FALLBACK_FULL_SCENE': 'Imagem completa',
    'DISABLED': 'Desabilitado',
    'AVAILABLE': 'Disponivel',
    'CONFIGURED': 'Configurado',
    'EXECUTED': 'Executado',
    'FAILED': 'Falhou',
    'IMPROPRIA': 'Imprópria',
    'IMPRÓPRIA': 'Imprópria',
    'INCOMPATIVEL': 'Incompatível',
    'INCONCLUSIVO': 'Inconclusivo',
    'INDEFINIDO': 'Indefinido',
    'INDEFINIDA': 'Indefinida',
    'MEDIA': 'Média',
    'MÉDIA': 'Média',
    'MUITO_PROVAVELMENTE_CORRESPONDENTE': 'Muito provavelmente correspondente',
    'OK': 'Ok',
    'POUCO_COMPATIVEL': 'Pouco compatível',
    'RAZOAVEL': 'Razoável',
    'RAZOÁVEL': 'Razoável',
    'REGULAR': 'Regular',
    'RESULTADO_CACHE': 'Resultado em cache',
    'PLATE_ROI_FIRST': 'ROI da placa primeiro',
    'ALLOWLIST_EXTENSION_SIGNATURE_SIZE': 'Validacao por extensao, assinatura e tamanho',
    'SINGLE_LINE': 'Linha unica',
    'WIDE': 'Largo',
    'SKIPPED': 'Ignorado',
    'PENDING': 'Pendente',
    'PENDING_ASYNC': 'Pendente',
    'PENDENTE_WEBHOOK': 'Pendente de webhook',
    'CORROBORADA_MULTIFONTE': 'Corroborada por múltiplas fontes',
    'DIVERGENCIA_VISUAL': 'Divergência visual',
    'REVISAO_HUMANA_OBRIGATORIA': 'Revisão humana obrigatória',
    'HIPOTESE_VISUAL_LOCAL': 'Hipótese visual local',
    'APOIO_TECNICO_VISUAL': 'Apoio técnico visual',
    'PENDENTE_WEBHOOK_USEZAPAY': 'Pendente de webhook',
    'PENDENTE_NO_PHP': 'Pendente no PHP',
    'UNAVAILABLE': 'Indisponível',
    'NAO_DISPONIVEL': 'Não disponível',
    'REVISAO_OBRIGATORIA': 'Revisão obrigatória',
    'REVISÃO_OBRIGATÓRIA': 'Revisão obrigatória',
    'ROI_DETECTADO': 'ROI detectado',
    'SEM_CANDIDATO': 'Sem candidato',
    'SEM_ROI_CONFIAVEL': 'Sem ROI confiável',
    'VALIDADO': 'Validado',
}

_SCENE_LABEL_MAP = {
    'BALANCED': 'Balanceado',
    'BLURRED': 'Borrado',
    'BRIGHT': 'Muito claro',
    'DARK': 'Escuro',
    'DISABLED': 'Desabilitado',
    'EMPTY_SCENE': 'Cena vazia',
    'GLARE': 'Reflexo intenso',
    'LOW_CONTRAST': 'Baixo contraste',
    'MOTION_BLUR': 'Borrado por movimento',
    'NOISY': 'Ruidoso',
    'OVEREXPOSED': 'Estourado',
    'UNDEREXPOSED': 'Subexposto',
    'BACKLIT': 'Contraluz',
}

_ENGINE_HEALTH_LABEL_MAP = {
    'AVAILABLE': 'Disponivel',
    'CONFIGURED': 'Configurado',
    'DISABLED': 'Desabilitado',
    'EXECUTED': 'Executado',
    'FAILED': 'Falhou',
    'OK': 'Ok',
    'PARTIAL': 'Parcial',
    'READY': 'Pronto',
    'SKIPPED': 'Ignorado',
    'UNAVAILABLE': 'Indisponivel',
}

_ROI_QUALITY_LABEL_MAP = {
    'A': 'Boa',
    'B': 'Razoável',
    'C': 'Ruim',
    'D': 'Imprópria',
    'BOA': 'Boa',
    'EXCELENTE': 'Excelente',
    'REGULAR': 'Regular',
    'CRITICA': 'Crítica',
    'IMPROPRIA': 'Imprópria',
    'INDEFINIDA': 'Indefinida',
    'INDEFINIDO': 'Indefinido',
    'SEM_ROI_CONFIAVEL': 'Sem ROI confiável',
    'ROI_DETECTADO': 'ROI detectado',
    'FALLBACK_FULL_SCENE': 'Imagem completa',
    'SEM_CANDIDATO': 'Sem candidato',
}

_OFFICIAL_VALIDATION_LABEL_MAP = {
    'VALIDADO': 'Validado',
    'OK': 'Ok',
    'RESULTADO_CACHE': 'Resultado em cache',
    'PENDENTE_WEBHOOK': 'Pendente de webhook',
    'PENDENTE_WEBHOOK_USEZAPAY': 'Pendente de webhook',
    'PENDING': 'Pendente',
    'PENDING_ASYNC': 'Pendente',
    'NAO_DISPONIVEL': 'Não disponível',
    'NAO_CONFIGURADO': 'Não configurado',
    'SEM_RETORNO': 'Sem retorno',
    'SEM_HISTORICO': 'Sem histórico',
    'ESTIMADO_FONTES_ABERTAS': 'Estimado por fontes abertas',
    'REVISAO_OBRIGATORIA': 'Revisão obrigatória',
    'ERRO': 'Erro',
    'INDEFINIDO': 'Indefinido',
    'INDEFINIDA': 'Indefinida',
}

_OFFICIAL_VALIDATION_SOURCE_KIND_MAP = {
    'OFFICIAL_SENATRAN': 'Fonte oficial Senatran',
    'OFFICIAL_SERPRO': 'Fonte oficial Serpro',
    'OFFICIAL_SINESP': 'Fonte oficial Sinesp',
    'USEZAPAY': 'UseZapay',
    'OPEN_VISUAL_FALLBACK': 'Análise visual local',
    'ESTIMADO_FONTES_ABERTAS': 'Fontes abertas',
    'FIPE': 'FIPE',
    'OPEN_DATA_FIPE': 'FIPE aberta',
    'INDEFINIDO': 'Indefinido',
}

_OFFICIAL_VALIDATION_SOURCE_LABEL_MAP = {
    'ANALISE_VISUAL_LOCAL_HEURISTICA': 'Análise visual local heurística',
    'ANALISE_VISUAL_LOCAL': 'Análise visual local',
    'SENATRAN': 'Senatran',
    'SERPRO': 'Serpro',
    'SINESP': 'Sinesp Cidadão',
    'SINESP_CIDADAO': 'Sinesp Cidadão',
    'USEZAPAY': 'UseZapay',
    'FIPE': 'FIPE',
    'FIPE_PARALELUM': 'FIPE aberta',
    'OPEN_DATA': 'Dados abertos',
    'OPEN_VISUAL_FALLBACK': 'Análise visual local',
}


_ACCENT_WORD_MAP = {
    'acuracia': 'acurácia',
    'analise': 'análise',
    'analises': 'análises',
    'aprovacao': 'aprovação',
    'avaliacao': 'avaliação',
    'calibracao': 'calibração',
    'classificacao': 'classificação',
    'compativel': 'compatível',
    'compativeis': 'compatíveis',
    'conferencia': 'conferência',
    'conferencias': 'conferências',
    'consolidacao': 'consolidação',
    'correlacao': 'correlação',
    'custodia': 'custódia',
    'decisao': 'decisão',
    'descricao': 'descrição',
    'deteccao': 'detecção',
    'divergencia': 'divergência',
    'divergencias': 'divergências',
    'documentacao': 'documentação',
    'documental': 'documental',
    'evidencia': 'evidência',
    'evidencias': 'evidências',
    'estrategia': 'estratégia',
    'faixa': 'faixa',
    'fonte': 'fonte',
    'fontes': 'fontes',
    'hipotese': 'hipótese',
    'hipoteses': 'hipóteses',
    'historico': 'histórico',
    'identificacao': 'identificação',
    'impressao': 'impressão',
    'inferencia': 'inferência',
    'integridade': 'integridade',
    'interpretacao': 'interpretação',
    'matriz': 'matriz',
    'metadados': 'metadados',
    'motores': 'motores',
    'observacao': 'observação',
    'observacoes': 'observações',
    'operacao': 'operação',
    'operacional': 'operacional',
    'padrao': 'padrão',
    'padroes': 'padrões',
    'pericial': 'pericial',
    'pericia': 'perícia',
    'placa': 'placa',
    'politica': 'política',
    'pos': 'pós',
    'pre': 'pré',
    'probatoria': 'probatória',
    'probatorio': 'probatório',
    'processamento': 'processamento',
    'protocolo': 'protocolo',
    'qualificacao': 'qualificação',
    'qualidade': 'qualidade',
    'confianca': 'confiança',
    'conclusao': 'conclusão',
    'correcao': 'correção',
    'revisao': 'revisão',
    'seguranca': 'segurança',
    'sintese': 'síntese',
    'situacao': 'situação',
    'tecnica': 'técnica',
    'tecnicas': 'técnicas',
    'tecnico': 'técnico',
    'tecnicos': 'técnicos',
    'tratamento': 'tratamento',
    'validacao': 'validação',
    'veiculo': 'veículo',
    'veiculos': 'veículos',
}


def _apply_common_accentuation(text: str) -> str:
    if not text:
        return text

    parts = re.split(r'(\W+)', text, flags=re.UNICODE)
    for index, part in enumerate(parts):
        if not part or not part.isalpha():
            continue
        normalized = unicodedata.normalize('NFKD', part)
        base = ''.join(char for char in normalized if not unicodedata.combining(char)).casefold()
        replacement = _ACCENT_WORD_MAP.get(base)
        if not replacement:
            continue
        if part.isupper():
            parts[index] = replacement.upper()
        elif part[:1].isupper():
            parts[index] = replacement[:1].upper() + replacement[1:]
        else:
            parts[index] = replacement

    return ''.join(parts)


def _normalize_label_key(value) -> str:
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = text.upper().strip()
    text = re.sub(r'[^A-Z0-9]+', '_', text)
    return re.sub(r'_+', '_', text).strip('_')


def _humanize_label(value, custom_map=None) -> str:
    raw = '' if value is None else str(value).strip()
    if not raw:
        return 'Indefinido'

    key = _normalize_label_key(raw)
    if custom_map and key in custom_map:
        return _apply_common_accentuation(custom_map[key])
    if key in _LABEL_MAP:
        return _apply_common_accentuation(_LABEL_MAP[key])

    fallback = raw.replace('_', ' ').replace('-', ' ')
    fallback = re.sub(r'\s+', ' ', fallback).strip()
    if not fallback:
        return 'Indefinido'

    fallback = fallback[:1].upper() + fallback[1:]
    return _apply_common_accentuation(fallback)


def format_report_label(value) -> str:
    raw = '' if value is None else str(value).strip()
    if not raw:
        return 'Indefinido'

    slug_like = bool(re.fullmatch(r'[A-Z0-9_./+\-]+', raw)) or '_' in raw or raw.isupper()
    if slug_like:
        return _apply_common_accentuation(humanize_pericial_label(raw))
    return _apply_common_accentuation(raw)


def format_report_value(value) -> str:
    if isinstance(value, bool):
        return 'Sim' if value else 'Não'

    raw = '' if value is None else str(value).strip()
    if not raw:
        return 'Indefinido'

    lowered = raw.casefold()
    if lowered in {'nao', 'não'}:
        return 'Não'
    if lowered in {'sim'}:
        return 'Sim'
    if '://' in raw or '\\' in raw or '/' in raw and len(raw) > 3:
        return raw

    slug_like = bool(re.fullmatch(r'[A-Z0-9_./+\-]+', raw)) or '_' in raw or raw.isupper()
    if slug_like:
        return _apply_common_accentuation(humanize_pericial_label(raw))

    return _apply_common_accentuation(raw)


def humanize_pericial_label(value) -> str:
    return _humanize_label(value)


def humanize_scene_label(value) -> str:
    return _humanize_label(value, _SCENE_LABEL_MAP)


def humanize_engine_health_label(value) -> str:
    return _humanize_label(value, _ENGINE_HEALTH_LABEL_MAP)


def humanize_roi_quality_label(value) -> str:
    return _humanize_label(value, _ROI_QUALITY_LABEL_MAP)


def humanize_official_validation_label(value) -> str:
    return _humanize_label(value, _OFFICIAL_VALIDATION_LABEL_MAP)


def humanize_official_validation_source_kind_label(value) -> str:
    return _humanize_label(value, _OFFICIAL_VALIDATION_SOURCE_KIND_MAP)


def humanize_official_validation_source_label(value) -> str:
    return _humanize_label(value, _OFFICIAL_VALIDATION_SOURCE_LABEL_MAP)
