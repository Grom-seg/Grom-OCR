from __future__ import annotations

import os
import hashlib
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote_plus


def _safe_float(value, default=0.0):
    try:
        if value is None or value == '':
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value, default=0):
    try:
        if value is None or value == '':
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def _safe_text(value, fallback=''):
    text = '' if value is None else str(value).strip()
    return text if text else fallback


def _normalize_fragment_text(text):
    return ''.join(ch for ch in str(text or '').upper() if ch.isalnum())


def _fragment_slot_hint(text):
    cleaned = _normalize_fragment_text(text)
    return ''.join('L' if ch.isalpha() else 'D' if ch.isdigit() else '?' for ch in cleaned)


def _fragment_kind(text):
    length = len(_normalize_fragment_text(text))
    if length <= 0:
        return 'indefinido'
    if length == 1:
        return 'caractere_isolado'
    if length == 2:
        return 'par_de_caracteres'
    if length <= 4:
        return 'fragmento_curto'
    return 'fragmento_parcial'


def _is_scene_level_region(region):
    normalized = _safe_text(region, '').lower()
    if not normalized:
        return False
    scene_tokens = (
        'raw_input',
        'full_image',
        'scene',
        'ocr_result',
        'whole_image',
    )
    return any(token in normalized for token in scene_tokens)


def _format_timecode(seconds):
    total = max(0, int(round(_safe_float(seconds, 0.0))))
    minutes = total // 60
    remaining = total % 60
    return f'{minutes:02d}:{remaining:02d}'


def _fragment_priority(cleaned, best_confidence, support_count, source_count):
    length = len(cleaned)
    if length <= 0:
        return 0.0
    length_bonus = 3.2 if length <= 2 else (2.0 if length <= 4 else 1.1)
    support_bonus = min(5.0, float(support_count) * 1.6)
    source_bonus = min(3.0, float(source_count) * 0.55)
    confidence_bonus = min(9.0, float(best_confidence) / 12.0)
    shape_bonus = 0.0
    letters = sum(char.isalpha() for char in cleaned)
    digits = sum(char.isdigit() for char in cleaned)
    if letters and digits:
        shape_bonus += 1.3
    elif length <= 2:
        shape_bonus += 0.8
    else:
        shape_bonus += 0.2
    return round(length_bonus + support_bonus + source_bonus + confidence_bonus + shape_bonus, 4)


def _should_keep_fragment(cleaned, best_confidence, support_count, source_count):
    length = len(cleaned)
    if length < 1 or length > 6:
        return False

    letters = sum(char.isalpha() for char in cleaned)
    digits = sum(char.isdigit() for char in cleaned)

    if length == 1:
        return best_confidence >= 18.0 or support_count >= 1 or source_count >= 1
    if length == 2:
        return best_confidence >= 16.0 or support_count >= 1 or source_count >= 1
    if length == 3:
        return (letters > 0 and digits > 0) or best_confidence >= 32.0 or support_count >= 2
    if length == 4:
        return (letters > 0 and digits > 0) or best_confidence >= 36.0 or support_count >= 2
    return (letters > 0 and digits > 0) or best_confidence >= 46.0 or support_count >= 2


def _build_source_items(ocr_results, top_candidates=None, context=None):
    ocr_results = ocr_results if isinstance(ocr_results, dict) else {}
    top_candidates = top_candidates if isinstance(top_candidates, list) else []
    context = context if isinstance(context, dict) else {}

    base_context = {
        'analysis_mode': _safe_text(context.get('analysis_mode'), ''),
        'analysis_id': _safe_text(context.get('analysis_id'), ''),
        'frame_index': _safe_int(context.get('frame_index'), -1),
        'frame_order': _safe_int(context.get('frame_order'), -1),
        'timestamp_seconds': _safe_float(context.get('timestamp_seconds'), -1.0),
        'frame_path': _safe_text(context.get('frame_path'), ''),
        'crop_raw_path': _safe_text(context.get('crop_raw_path'), ''),
        'crop_treated_path': _safe_text(context.get('crop_treated_path'), ''),
        'minute_index': _safe_int(context.get('minute_index'), -1),
        'minute_range': _safe_text(context.get('minute_range'), ''),
    }

    source_items = []

    for engine_name, result in ocr_results.items():
        if not isinstance(result, dict):
            continue
        engine = _safe_text(engine_name, 'ocr')
        region = _safe_text(result.get('region'), '')
        avg_conf = _safe_float(result.get('avg_conf', 0.0), 0.0)
        score = _safe_float(result.get('score', 0.0), 0.0)
        raw_entries = result.get('raw_entries') or result.get('entries') or []
        if isinstance(raw_entries, dict):
            raw_entries = [raw_entries]
        if not isinstance(raw_entries, list):
            raw_entries = []

        for entry in raw_entries:
            if isinstance(entry, dict):
                candidate_text = (
                    entry.get('word')
                    or entry.get('text')
                    or entry.get('value')
                    or entry.get('fragment')
                    or ''
                )
                confidence = _safe_float(
                    entry.get('conf')
                    or entry.get('confidence')
                    or entry.get('avg_conf')
                    or entry.get('score')
                    or avg_conf,
                    avg_conf,
                )
                entry_region = _safe_text(entry.get('region'), region)
                entry_origin = _safe_text(entry.get('origin'), 'raw_entry')
            else:
                candidate_text = entry
                confidence = avg_conf
                entry_region = region
                entry_origin = 'raw_entry'

            cleaned = _normalize_fragment_text(candidate_text)
            if not cleaned:
                continue
            if _is_scene_level_region(entry_region) and len(cleaned) >= 4 and cleaned.isalpha():
                continue
            if not _should_keep_fragment(cleaned, confidence, 1, 1):
                continue

            item = dict(base_context)
            item.update({
                'text': cleaned,
                'engine': engine,
                'region': entry_region or region or 'ocr_result',
                'origin': entry_origin,
                'conf': confidence,
                'score': score,
                'source_type': 'raw_entry',
            })
            source_items.append(item)

        if not raw_entries:
            fallback_text = _normalize_fragment_text(result.get('text', ''))
            if fallback_text and len(fallback_text) <= 6:
                if _is_scene_level_region(region) and len(fallback_text) >= 4 and fallback_text.isalpha():
                    continue
                confidence = avg_conf
                if _should_keep_fragment(fallback_text, confidence, 1, 1):
                    item = dict(base_context)
                    item.update({
                        'text': fallback_text,
                        'engine': engine,
                        'region': region or 'ocr_result',
                        'origin': 'engine_text',
                        'conf': confidence,
                        'score': score,
                        'source_type': 'engine_text',
                    })
                    source_items.append(item)

    for candidate in top_candidates:
        if not isinstance(candidate, dict):
            continue
        candidate_text = _normalize_fragment_text(candidate.get('text', ''))
        if not candidate_text or len(candidate_text) > 6:
            continue
        candidate_region = _safe_text(candidate.get('region'), '')
        if _is_scene_level_region(candidate_region) and len(candidate_text) >= 4 and candidate_text.isalpha():
            continue
        confidence = _safe_float(
            candidate.get('avg_conf')
            or candidate.get('confidence')
            or candidate.get('best_confidence')
            or 0.0,
            0.0,
        )
        support_count = _safe_int(candidate.get('support_count', candidate.get('hits', 1)), 1)
        if not _should_keep_fragment(candidate_text, confidence, support_count, support_count):
            continue
        item = dict(base_context)
        item.update({
            'text': candidate_text,
            'engine': _safe_text(candidate.get('engine'), 'ensemble'),
            'region': _safe_text(candidate.get('region'), ''),
            'origin': 'top_candidate',
            'conf': confidence,
            'score': _safe_float(candidate.get('score', 0.0), 0.0),
            'source_type': 'top_candidate',
        })
        item['minute_index'] = _safe_int(candidate.get('minute_index', item.get('minute_index', -1)), item.get('minute_index', -1))
        item['minute_range'] = _safe_text(candidate.get('minute_range', item.get('minute_range', '')), item.get('minute_range', ''))
        item['frame_index'] = _safe_int(candidate.get('frame_index', item.get('frame_index', -1)), item.get('frame_index', -1))
        item['frame_order'] = _safe_int(candidate.get('frame_order', item.get('frame_order', -1)), item.get('frame_order', -1))
        source_items.append(item)

    if not source_items:
        char_sources = []
        char_strength = defaultdict(float)
        char_support = defaultdict(set)
        for engine_name, result in ocr_results.items():
            if not isinstance(result, dict):
                continue
            engine = _safe_text(engine_name, 'ocr')
            region = _safe_text(result.get('region'), '')
            chars = result.get('chars', [])
            if not isinstance(chars, list):
                continue
            if _is_scene_level_region(region):
                continue
            for char, conf in chars:
                cleaned = _normalize_fragment_text(char)
                if len(cleaned) != 1:
                    continue
                confidence = _safe_float(conf, 0.0)
                if confidence <= 0:
                    continue
                char_strength[cleaned] = max(float(char_strength.get(cleaned, 0.0)), confidence)
                char_support[cleaned].add(engine)
                char_sources.append({
                    **base_context,
                    'text': cleaned,
                    'engine': engine,
                    'region': region or 'chars',
                    'origin': 'char_option',
                    'conf': confidence,
                    'score': confidence,
                    'source_type': 'char_option',
                })

        if char_sources:
            source_items.extend(char_sources)

    return source_items


def build_partial_plate_candidates(ocr_results, top_candidates=None, context=None, max_candidates=8):
    source_items = _build_source_items(ocr_results, top_candidates=top_candidates, context=context)
    if not source_items:
        return []

    groups: Dict[str, Dict[str, Any]] = {}
    for item in source_items:
        text = _normalize_fragment_text(item.get('text', ''))
        if not text:
            continue

        group = groups.get(text)
        if group is None:
            group = {
                'text': text,
                'normalized_text': text,
                'fragment_length': len(text),
                'fragment_kind': _fragment_kind(text),
                'slot_hint': _fragment_slot_hint(text),
                'source_count': 0,
                'support_engines': set(),
                'regions': set(),
                'origins': set(),
                'source_types': set(),
                'conf_sum': 0.0,
                'best_confidence': 0.0,
                'best_score': 0.0,
                'frame_indexes': set(),
                'frame_orders': set(),
                'frame_paths': [],
                'crop_raw_paths': [],
                'crop_treated_paths': [],
                'minute_index': _safe_int(item.get('minute_index'), -1),
                'minute_range': _safe_text(item.get('minute_range'), ''),
                'timestamp_seconds': _safe_float(item.get('timestamp_seconds'), -1.0),
                'frame_index': _safe_int(item.get('frame_index'), -1),
                'frame_order': _safe_int(item.get('frame_order'), -1),
                'analysis_modes': set(),
                'analysis_ids': set(),
            }
            groups[text] = group

        group['source_count'] += 1
        group['support_engines'].add(_safe_text(item.get('engine'), 'ocr'))
        region = _safe_text(item.get('region'), '')
        if region:
            group['regions'].add(region)
        origin = _safe_text(item.get('origin'), '')
        if origin:
            group['origins'].add(origin)
        source_type = _safe_text(item.get('source_type'), '')
        if source_type:
            group['source_types'].add(source_type)
        group['analysis_modes'].add(_safe_text(item.get('analysis_mode'), ''))
        group['analysis_ids'].add(_safe_text(item.get('analysis_id'), ''))
        confidence = _safe_float(item.get('conf', 0.0), 0.0)
        score = _safe_float(item.get('score', 0.0), 0.0)
        group['conf_sum'] += confidence
        previous_best_confidence = float(group['best_confidence'])
        group['best_confidence'] = max(float(group['best_confidence']), confidence)
        group['best_score'] = max(float(group['best_score']), score)
        frame_index = _safe_int(item.get('frame_index', -1), -1)
        frame_order = _safe_int(item.get('frame_order', -1), -1)
        if frame_index >= 0:
            group['frame_indexes'].add(frame_index)
        if frame_order >= 0:
            group['frame_orders'].add(frame_order)
        frame_path = _safe_text(item.get('frame_path'), '')
        crop_raw_path = _safe_text(item.get('crop_raw_path'), '')
        crop_treated_path = _safe_text(item.get('crop_treated_path'), '')
        if frame_path:
            group['frame_paths'].append(frame_path)
        if crop_raw_path:
            group['crop_raw_paths'].append(crop_raw_path)
        if crop_treated_path:
            group['crop_treated_paths'].append(crop_treated_path)

        if frame_index >= 0 and (
            group['frame_index'] < 0
            or confidence >= previous_best_confidence
        ):
            group['frame_index'] = frame_index
        if frame_order >= 0 and (
            group['frame_order'] < 0
            or confidence >= previous_best_confidence
        ):
            group['frame_order'] = frame_order
        timestamp_seconds = _safe_float(item.get('timestamp_seconds', -1.0), -1.0)
        if timestamp_seconds >= 0:
            group['timestamp_seconds'] = timestamp_seconds
        minute_index = _safe_int(item.get('minute_index', -1), -1)
        if minute_index >= 0:
            group['minute_index'] = minute_index
        minute_range = _safe_text(item.get('minute_range', ''), '')
        if minute_range:
            group['minute_range'] = minute_range

    candidates: List[Dict[str, Any]] = []
    for group in groups.values():
        support_count = len([engine for engine in group['support_engines'] if engine])
        source_count = int(group.get('source_count', 0) or 0)
        best_confidence = float(group.get('best_confidence', 0.0))
        if not _should_keep_fragment(group['text'], best_confidence, support_count, source_count):
            continue

        avg_confidence = float(group['conf_sum']) / max(1, source_count)
        frame_path = next((path for path in group.get('frame_paths', []) if path), '')
        crop_raw_path = next((path for path in group.get('crop_raw_paths', []) if path), '')
        crop_treated_path = next((path for path in group.get('crop_treated_paths', []) if path), '')
        timestamp_seconds = _safe_float(group.get('timestamp_seconds', -1.0), -1.0)
        minute_index = _safe_int(group.get('minute_index', -1), -1)
        minute_range = _safe_text(group.get('minute_range', ''), '')
        if minute_index >= 0 and not minute_range:
            minute_start = minute_index * 60
            minute_range = f'{_format_timecode(minute_start)}-{_format_timecode(minute_start + 59.999)}'
        elif minute_index < 0 and timestamp_seconds >= 0:
            minute_index = max(0, int(timestamp_seconds // 60))
            minute_start = minute_index * 60
            minute_range = f'{_format_timecode(minute_start)}-{_format_timecode(minute_start + 59.999)}'

        rank_priority = _fragment_priority(group['text'], best_confidence, support_count, source_count)
        candidate = {
            'text': group['text'],
            'normalized_text': group['normalized_text'],
            'fragment_length': int(group['fragment_length']),
            'fragment_kind': group['fragment_kind'],
            'slot_hint': group['slot_hint'],
            'support_count': support_count,
            'source_count': source_count,
            'avg_confidence': round(avg_confidence, 2),
            'best_confidence': round(best_confidence, 2),
            'best_score': round(float(group.get('best_score', 0.0)), 2),
            'score': round(float(best_confidence) + (support_count * 9.0) + (source_count * 3.0), 2),
            'rank_priority': round(rank_priority, 4),
            'support_engines': sorted([engine for engine in group['support_engines'] if engine]),
            'regions': sorted([region for region in group['regions'] if region]),
            'origins': sorted([origin for origin in group['origins'] if origin]),
            'source_types': sorted([item for item in group['source_types'] if item]),
            'minute_index': minute_index,
            'minute_range': minute_range or 'Indefinido',
            'timestamp_seconds': round(timestamp_seconds, 4) if timestamp_seconds >= 0 else -1.0,
            'timestamp_label': _format_timecode(timestamp_seconds) if timestamp_seconds >= 0 else 'Indefinido',
            'frame_index': _safe_int(group.get('frame_index', -1), -1),
            'frame_order': _safe_int(group.get('frame_order', -1), -1),
            'frame_path': frame_path,
            'frame_url': f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else '',
            'crop_raw_path': crop_raw_path,
            'crop_raw_url': f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}" if crop_raw_path else '',
            'crop_treated_path': crop_treated_path,
            'crop_treated_url': f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}" if crop_treated_path else '',
            'frame_indexes': sorted({idx for idx in group.get('frame_indexes', []) if idx >= 0}),
            'frame_orders': sorted({idx for idx in group.get('frame_orders', []) if idx >= 0}),
            'analysis_modes': sorted([mode for mode in group.get('analysis_modes', set()) if mode]),
            'analysis_ids': sorted([aid for aid in group.get('analysis_ids', set()) if aid]),
            'best_frame_signature': '',
        }
        if candidate['frame_path'] or candidate['timestamp_seconds'] >= 0:
            signature_seed = '|'.join([
                candidate['text'],
                candidate['minute_range'],
                str(candidate['frame_index']),
                str(candidate['timestamp_seconds']),
            ])
            candidate['best_frame_signature'] = hashlib.sha1(signature_seed.encode('utf-8')).hexdigest()[:18]
        candidate['label'] = f"{candidate['text']} | parcial"
        candidate['support_label'] = f"{candidate['support_count']} motor(es) | {candidate['source_count']} leitura(s)"
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            float(item.get('rank_priority', 0.0)),
            float(item.get('support_count', 0)),
            float(item.get('best_confidence', 0.0)),
            float(item.get('avg_confidence', 0.0)),
            -float(item.get('fragment_length', 0)),
        ),
        reverse=True,
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate['rank'] = index

    return candidates[:max(1, int(max_candidates or 8))]


def build_partial_plate_overview(partial_candidates, limit=4):
    entries = [entry for entry in (partial_candidates if isinstance(partial_candidates, list) else []) if isinstance(entry, dict)]
    if not entries:
        return {
            'has_partial': False,
            'count': 0,
            'primary_text': '-',
            'summary': '-',
            'top_candidates': [],
        }

    top_candidates = entries[:max(1, int(limit or 4))]
    summary_parts = []
    for item in top_candidates:
        text = _safe_text(item.get('text'), '-')
        support_label = _safe_text(item.get('support_label'), '')
        minute_range = _safe_text(item.get('minute_range'), '')
        details = []
        if support_label and support_label != '-':
            details.append(support_label)
        if minute_range and minute_range != 'Indefinido':
            details.append(minute_range)
        suffix = f" ({' | '.join(details)})" if details else ''
        summary_parts.append(f'{text}{suffix}')

    primary_text = _safe_text(top_candidates[0].get('text'), '-')
    return {
        'has_partial': True,
        'count': len(entries),
        'primary_text': primary_text,
        'summary': '; '.join(summary_parts),
        'top_candidates': top_candidates,
    }
