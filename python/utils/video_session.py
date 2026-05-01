from __future__ import annotations

import hashlib
import json
import os
from urllib.parse import quote_plus

from utils.partial_plate import _fragment_priority, _should_keep_fragment
from typing import Any, Dict, Iterable, List


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


def _safe_text(value, fallback='-'):
    text = '' if value is None else str(value).strip()
    return text if text else fallback


def _format_timecode(seconds):
    total = max(0, int(round(_safe_float(seconds, 0.0))))
    minutes = total // 60
    remaining = total % 60
    return f'{minutes:02d}:{remaining:02d}'


def _normalize_candidate_text(text):
    normalized = ''.join(ch for ch in str(text or '').upper() if ch.isalnum())
    return normalized or 'SEM_TEXTO'


def build_video_scan_record_path(analysis_id, save_dir):
    analysis_id = _safe_text(analysis_id, '').strip()
    if not analysis_id:
        analysis_id = hashlib.sha1(os.urandom(16)).hexdigest()[:16]
    save_dir = save_dir or os.getcwd()
    os.makedirs(save_dir, exist_ok=True)
    return os.path.join(save_dir, f'grom_ocr_video_scan_{analysis_id}.json')


def save_video_scan_record(record, save_dir, analysis_id=None):
    record = record if isinstance(record, dict) else {}
    if analysis_id is None:
        analysis_id = record.get('analysis_id', '')
    path = build_video_scan_record_path(analysis_id, save_dir)
    payload = dict(record)
    payload['analysis_id'] = _safe_text(payload.get('analysis_id', analysis_id), analysis_id)
    payload['record_path'] = path
    with open(path, 'w', encoding='utf-8') as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return path


def load_video_scan_record(save_dir, analysis_id):
    path = build_video_scan_record_path(analysis_id, save_dir)
    if not os.path.exists(path):
        return {}, path
    try:
        with open(path, 'r', encoding='utf-8') as stream:
            data = json.load(stream)
            return data if isinstance(data, dict) else {}, path
    except Exception:
        return {}, path


def _candidate_rank_key(candidate):
    return (
        _safe_int(candidate.get('frames_count', 0), 0),
        _safe_float(candidate.get('style_rank_priority', 0.0), 0.0),
        _safe_float(candidate.get('best_confidence', candidate.get('confidence', 0.0)), 0.0),
        _safe_float(candidate.get('best_score', candidate.get('score', 0.0)), 0.0),
        -_safe_float(candidate.get('best_timestamp_seconds', candidate.get('timestamp_seconds', 0.0)), 0.0),
    )


def aggregate_video_candidates(frame_results, max_candidates=24):
    groups: Dict[str, Dict[str, Any]] = {}
    entries = [entry for entry in frame_results if isinstance(entry, dict)]

    for entry in entries:
        text = _safe_text(entry.get('ocr', ''), '').strip()
        if not text:
            continue

        normalized_text = _normalize_candidate_text(text)
        timestamp_seconds = _safe_float(entry.get('timestamp_seconds', 0.0), 0.0)
        minute_index = max(0, int(timestamp_seconds // 60))
        minute_start = minute_index * 60
        minute_end = minute_start + 59.999
        pattern = _safe_text(entry.get('pattern', 'Indefinido'), 'Indefinido')
        candidate_key = f'{normalized_text}|{pattern}|{minute_index}'

        group = groups.get(candidate_key)
        if group is None:
            group = {
                'candidate_id': hashlib.sha1(candidate_key.encode('utf-8')).hexdigest()[:16],
                'text': text,
                'normalized_text': normalized_text,
                'pattern': pattern,
                'minute_index': minute_index,
                'minute_label': f'{minute_index:02d}',
                'minute_range': f'{_format_timecode(minute_start)}-{_format_timecode(minute_end)}',
                'frames_count': 0,
                'confidence_sum': 0.0,
                'score_sum': 0.0,
                'best_confidence': 0.0,
                'best_score': 0.0,
                'best_timestamp_seconds': 0.0,
                'best_frame': {},
                'frame_indexes': [],
                'frame_orders': [],
                'frame_paths': [],
                'plate_paths': [],
            }
            groups[candidate_key] = group

        confidence = _safe_float(entry.get('confidence', 0.0), 0.0)
        score = _safe_float(entry.get('score', 0.0), 0.0)
        timestamp_seconds = _safe_float(entry.get('timestamp_seconds', 0.0), 0.0)
        group['frames_count'] += 1
        group['confidence_sum'] += confidence
        group['score_sum'] += score
        group['frame_indexes'].append(_safe_int(entry.get('frame_index', 0), 0))
        group['frame_orders'].append(_safe_int(entry.get('frame_order', 0), 0))
        frame_path = _safe_text(entry.get('frame_path', ''), '')
        if frame_path:
            group['frame_paths'].append(frame_path)
        plate_path = _safe_text(entry.get('crop_treated_path', '') or entry.get('crop_raw_path', ''), '')
        if plate_path:
            group['plate_paths'].append(plate_path)

        is_better = (
            confidence > group['best_confidence']
            or (
                confidence == group['best_confidence']
                and score > group['best_score']
            )
        )
        if is_better:
            group['best_confidence'] = confidence
            group['best_score'] = score
            group['best_timestamp_seconds'] = timestamp_seconds
            group['best_frame'] = dict(entry)

    candidates: List[Dict[str, Any]] = []
    for group in groups.values():
        best_frame = dict(group.get('best_frame', {}))
        frame_path = _safe_text(best_frame.get('frame_path', ''), '')
        crop_raw_path = _safe_text(best_frame.get('crop_raw_path', ''), '')
        crop_treated_path = _safe_text(best_frame.get('crop_treated_path', ''), '')
        candidate = {
            'candidate_id': group['candidate_id'],
            'text': group['text'],
            'normalized_text': group['normalized_text'],
            'pattern': group['pattern'],
            'minute_index': group['minute_index'],
            'minute_label': group['minute_label'],
            'minute_range': group['minute_range'],
            'timestamp_seconds': _safe_float(best_frame.get('timestamp_seconds', group['best_timestamp_seconds']), 0.0),
            'timestamp_label': _format_timecode(best_frame.get('timestamp_seconds', group['best_timestamp_seconds'])),
            'frame_index': _safe_int(best_frame.get('frame_index', 0), 0),
            'frame_order': _safe_int(best_frame.get('frame_order', 0), 0),
            'frame_path': frame_path,
            'frame_url': f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else '',
            'crop_raw_path': crop_raw_path,
            'crop_raw_url': f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}" if crop_raw_path else '',
            'crop_treated_path': crop_treated_path,
            'crop_treated_url': f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}" if crop_treated_path else '',
            'crop_preview_path': crop_treated_path or crop_raw_path or frame_path,
            'crop_preview_url': (
                f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}"
                if crop_treated_path
                else (
                    f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}"
                    if crop_raw_path
                    else (f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else '')
                )
            ),
            'best_confidence': round(_safe_float(group.get('best_confidence', 0.0), 0.0), 2),
            'best_score': round(_safe_float(group.get('best_score', 0.0), 0.0), 2),
            'style_rank_priority': round(_safe_float(best_frame.get('style_rank_priority', 0.0), 0.0), 3),
            'support_rank': round(_safe_float(best_frame.get('support_rank', best_frame.get('support_count', 0.0)), 0.0), 3),
            'frames_count': int(group.get('frames_count', 0) or 0),
            'avg_confidence': round(group['confidence_sum'] / max(1, int(group['frames_count'] or 1)), 2),
            'avg_score': round(group['score_sum'] / max(1, int(group['frames_count'] or 1)), 2),
            'frame_indexes': sorted({idx for idx in group.get('frame_indexes', []) if idx >= 0}),
            'frame_orders': sorted({idx for idx in group.get('frame_orders', []) if idx >= 0}),
            'frame_paths': list(dict.fromkeys(group.get('frame_paths', []))),
            'plate_paths': list(dict.fromkeys(group.get('plate_paths', []))),
            'best_frame': best_frame,
            'best_frame_signature': hashlib.sha1(
                '|'.join([
                    group['candidate_id'],
                    str(best_frame.get('frame_index', 0)),
                    str(best_frame.get('timestamp_seconds', 0.0)),
                    _safe_text(best_frame.get('ocr', ''), ''),
                ]).encode('utf-8')
            ).hexdigest()[:18],
        }
        candidates.append(candidate)

    candidates.sort(key=_candidate_rank_key, reverse=True)
    for index, candidate in enumerate(candidates, start=1):
        candidate['rank'] = index
        candidate['label'] = f"{candidate['minute_range']} | {candidate['text']} | {candidate['pattern']}"
        candidate['support_label'] = f"{candidate['frames_count']} quadros | minuto {candidate['minute_label']}"

    return candidates[:max_candidates], candidates


def aggregate_video_partial_candidates(frame_results, max_candidates=24):
    groups: Dict[str, Dict[str, Any]] = {}
    entries = [entry for entry in frame_results if isinstance(entry, dict)]

    for frame_entry in entries:
        frame_index = _safe_int(frame_entry.get('frame_index', 0), 0)
        frame_order = _safe_int(frame_entry.get('frame_order', 0), 0)
        frame_timestamp = _safe_float(frame_entry.get('timestamp_seconds', 0.0), 0.0)
        frame_minute_index = max(0, int(frame_timestamp // 60)) if frame_timestamp >= 0 else 0
        frame_minute_start = frame_minute_index * 60
        frame_minute_range = f'{_format_timecode(frame_minute_start)}-{_format_timecode(frame_minute_start + 59.999)}'
        frame_path = _safe_text(frame_entry.get('frame_path', ''), '')
        crop_raw_path = _safe_text(frame_entry.get('crop_raw_path', ''), '')
        crop_treated_path = _safe_text(frame_entry.get('crop_treated_path', ''), '')
        analysis_mode = _safe_text(frame_entry.get('analysis_mode', ''), 'video')
        analysis_id = _safe_text(frame_entry.get('analysis_id', ''), '')
        partial_candidates = frame_entry.get('partial_plate_candidates', [])
        if isinstance(partial_candidates, dict):
            partial_candidates = [partial_candidates]
        if not isinstance(partial_candidates, list):
            partial_candidates = []

        if not partial_candidates:
            fallback_text = _normalize_candidate_text(frame_entry.get('partial_plate_text', ''))
            if fallback_text:
                partial_candidates = [{
                    'text': fallback_text,
                    'normalized_text': fallback_text,
                    'fragment_length': len(fallback_text),
                    'fragment_kind': 'fragmento_parcial',
                    'slot_hint': ''.join('L' if char.isalpha() else 'D' if char.isdigit() else '?' for char in fallback_text),
                    'support_count': 1,
                    'source_count': 1,
                    'avg_confidence': _safe_float(frame_entry.get('confidence', frame_entry.get('avg_conf', 0.0)), 0.0),
                    'best_confidence': _safe_float(frame_entry.get('confidence', frame_entry.get('avg_conf', 0.0)), 0.0),
                    'best_score': _safe_float(frame_entry.get('score', 0.0), 0.0),
                    'score': _safe_float(frame_entry.get('score', 0.0), 0.0),
                    'support_engines': [_safe_text(frame_entry.get('engine', ''), 'video_frame')],
                    'regions': [_safe_text(frame_entry.get('region', ''), '')],
                    'origins': ['frame_result_fallback'],
                    'source_types': ['fallback'],
                    'minute_index': frame_minute_index,
                    'minute_range': frame_minute_range,
                    'timestamp_seconds': frame_timestamp,
                    'timestamp_label': _format_timecode(frame_timestamp),
                    'frame_index': frame_index,
                    'frame_order': frame_order,
                    'frame_path': frame_path,
                    'frame_url': f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else '',
                    'crop_raw_path': crop_raw_path,
                    'crop_raw_url': f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}" if crop_raw_path else '',
                    'crop_treated_path': crop_treated_path,
                    'crop_treated_url': f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}" if crop_treated_path else '',
                    'analysis_modes': [analysis_mode] if analysis_mode else [],
                    'analysis_ids': [analysis_id] if analysis_id else [],
                    'label': f'{fallback_text} | parcial',
                    'support_label': '1 motor(es) | 1 leitura(s)',
                }]

        for item in partial_candidates:
            if not isinstance(item, dict):
                continue
            text = _normalize_candidate_text(item.get('text', '') or item.get('normalized_text', ''))
            if not text:
                continue

            minute_index = _safe_int(item.get('minute_index', frame_minute_index), frame_minute_index)
            if minute_index < 0:
                minute_index = frame_minute_index
            minute_start = max(0, minute_index) * 60
            minute_range = _safe_text(item.get('minute_range', ''), '')
            if not minute_range:
                minute_range = f'{_format_timecode(minute_start)}-{_format_timecode(minute_start + 59.999)}'

            slot_hint = _safe_text(
                item.get('slot_hint', ''),
                ''.join('L' if char.isalpha() else 'D' if char.isdigit() else '?' for char in text),
            )
            candidate_key = f'{text}|{minute_index}|{slot_hint}'
            group = groups.get(candidate_key)
            if group is None:
                group = {
                    'candidate_id': hashlib.sha1(candidate_key.encode('utf-8')).hexdigest()[:16],
                    'text': text,
                    'normalized_text': text,
                    'fragment_length': len(text),
                    'fragment_kind': _safe_text(item.get('fragment_kind', ''), 'fragmento_parcial'),
                    'slot_hint': slot_hint,
                    'support_engines': set(),
                    'regions': set(),
                    'origins': set(),
                    'source_types': set(),
                    'analysis_modes': set(),
                    'analysis_ids': set(),
                    'source_count': 0,
                    'source_frame_count': 0,
                    'frame_indexes': set(),
                    'frame_orders': set(),
                    'frame_paths': [],
                    'crop_raw_paths': [],
                    'crop_treated_paths': [],
                    'minute_index': minute_index,
                    'minute_range': minute_range,
                    'timestamp_seconds': _safe_float(item.get('timestamp_seconds', frame_timestamp), frame_timestamp),
                    'frame_index': _safe_int(item.get('frame_index', frame_index), frame_index),
                    'frame_order': _safe_int(item.get('frame_order', frame_order), frame_order),
                    'conf_sum': 0.0,
                    'score_sum': 0.0,
                    'best_confidence': 0.0,
                    'best_score': 0.0,
                    'best_rank_priority': 0.0,
                    'best_frame': {},
                }
                groups[candidate_key] = group

            support_engines = item.get('support_engines', [])
            if isinstance(support_engines, (list, tuple, set)):
                for engine in support_engines:
                    engine_text = _safe_text(engine, '')
                    if engine_text:
                        group['support_engines'].add(engine_text)
            else:
                engine_text = _safe_text(support_engines, '')
                if engine_text:
                    group['support_engines'].add(engine_text)

            for field_name in ('regions', 'origins', 'source_types', 'analysis_modes', 'analysis_ids'):
                value = item.get(field_name, [])
                if isinstance(value, (list, tuple, set)):
                    for entry in value:
                        entry_text = _safe_text(entry, '')
                        if entry_text:
                            group[field_name].add(entry_text)
                else:
                    entry_text = _safe_text(value, '')
                    if entry_text:
                        group[field_name].add(entry_text)

            confidence = _safe_float(
                item.get('best_confidence')
                or item.get('avg_confidence')
                or item.get('confidence')
                or item.get('conf'),
                0.0,
            )
            score = _safe_float(
                item.get('best_score')
                or item.get('avg_score')
                or item.get('score'),
                0.0,
            )
            rank_priority = _safe_float(item.get('rank_priority', 0.0), 0.0)
            group['source_count'] += max(1, _safe_int(item.get('source_count', 1), 1))
            group['conf_sum'] += confidence
            group['score_sum'] += score
            group['best_confidence'] = max(float(group['best_confidence']), confidence)
            group['best_score'] = max(float(group['best_score']), score)
            group['best_rank_priority'] = max(float(group['best_rank_priority']), rank_priority)

            frame_index_value = _safe_int(item.get('frame_index', frame_index), frame_index)
            frame_order_value = _safe_int(item.get('frame_order', frame_order), frame_order)
            if frame_index_value >= 0:
                group['frame_indexes'].add(frame_index_value)
            if frame_order_value >= 0:
                group['frame_orders'].add(frame_order_value)
            group['source_frame_count'] = len(group['frame_indexes'])

            item_frame_path = _safe_text(item.get('frame_path', '') or frame_path, frame_path)
            item_crop_raw_path = _safe_text(item.get('crop_raw_path', '') or crop_raw_path, crop_raw_path)
            item_crop_treated_path = _safe_text(item.get('crop_treated_path', '') or crop_treated_path, crop_treated_path)
            if item_frame_path:
                group['frame_paths'].append(item_frame_path)
            if item_crop_raw_path:
                group['crop_raw_paths'].append(item_crop_raw_path)
            if item_crop_treated_path:
                group['crop_treated_paths'].append(item_crop_treated_path)

            timestamp_seconds = _safe_float(item.get('timestamp_seconds', frame_timestamp), frame_timestamp)
            if timestamp_seconds >= 0:
                group['timestamp_seconds'] = timestamp_seconds
            if minute_index >= 0:
                group['minute_index'] = minute_index
                group['minute_range'] = minute_range
            current_best_confidence = float(group['best_frame'].get('best_confidence', group['best_confidence'])) if group['best_frame'] else float(group['best_confidence'])
            current_best_score = float(group['best_frame'].get('best_score', group['best_score'])) if group['best_frame'] else float(group['best_score'])
            if frame_index_value >= 0 and (
                not group['best_frame']
                or confidence > current_best_confidence
                or (confidence == current_best_confidence and score > current_best_score)
            ):
                best_frame = dict(item)
                best_frame.setdefault('text', text)
                best_frame.setdefault('normalized_text', text)
                best_frame.setdefault('minute_index', minute_index)
                best_frame.setdefault('minute_range', minute_range)
                best_frame.setdefault('timestamp_seconds', timestamp_seconds)
                best_frame.setdefault('frame_index', frame_index_value)
                best_frame.setdefault('frame_order', frame_order_value)
                best_frame.setdefault('frame_path', item_frame_path)
                best_frame.setdefault('crop_raw_path', item_crop_raw_path)
                best_frame.setdefault('crop_treated_path', item_crop_treated_path)
                best_frame.setdefault('support_label', _safe_text(item.get('support_label', ''), ''))
                best_frame.setdefault('label', _safe_text(item.get('label', ''), f'{text} | parcial'))
                best_frame['best_confidence'] = confidence
                best_frame['best_score'] = score
                best_frame['rank_priority'] = rank_priority
                group['best_frame'] = best_frame

    candidates: List[Dict[str, Any]] = []
    for group in groups.values():
        support_engines = [engine for engine in group['support_engines'] if engine]
        support_count = len(support_engines)
        source_count = int(group.get('source_count', 0) or 0)
        best_confidence = float(group.get('best_confidence', 0.0))
        if not _should_keep_fragment(group['text'], best_confidence, support_count, source_count):
            continue

        avg_confidence = float(group['conf_sum']) / max(1, source_count)
        avg_score = float(group['score_sum']) / max(1, source_count)
        frame_path = next((path for path in group.get('frame_paths', []) if path), '')
        crop_raw_path = next((path for path in group.get('crop_raw_paths', []) if path), '')
        crop_treated_path = next((path for path in group.get('crop_treated_paths', []) if path), '')
        minute_index = _safe_int(group.get('minute_index', -1), -1)
        minute_range = _safe_text(group.get('minute_range', ''), 'Indefinido')
        if minute_index >= 0 and minute_range == 'Indefinido':
            minute_start = minute_index * 60
            minute_range = f'{_format_timecode(minute_start)}-{_format_timecode(minute_start + 59.999)}'

        best_frame = dict(group.get('best_frame', {}))
        timestamp_seconds = _safe_float(best_frame.get('timestamp_seconds', group.get('timestamp_seconds', -1.0)), -1.0)
        frame_index = _safe_int(best_frame.get('frame_index', group.get('frame_index', -1)), -1)
        frame_order = _safe_int(best_frame.get('frame_order', group.get('frame_order', -1)), -1)
        fragment_kind = _safe_text(group.get('fragment_kind', ''), 'fragmento_parcial')
        slot_hint = _safe_text(group.get('slot_hint', ''), '')
        rank_priority = max(
            _safe_float(group.get('best_rank_priority', 0.0), 0.0),
            _fragment_priority(group['text'], best_confidence, support_count, source_count),
        )
        candidate = {
            'candidate_id': group['candidate_id'],
            'text': group['text'],
            'normalized_text': group['normalized_text'],
            'fragment_length': int(group['fragment_length']),
            'fragment_kind': fragment_kind,
            'slot_hint': slot_hint,
            'support_count': support_count,
            'source_count': source_count,
            'source_frame_count': int(len(group.get('frame_indexes', [])) or 0),
            'frames_count': int(len(group.get('frame_indexes', [])) or 0),
            'avg_confidence': round(avg_confidence, 2),
            'best_confidence': round(best_confidence, 2),
            'best_score': round(float(group.get('best_score', 0.0)), 2),
            'avg_score': round(avg_score, 2),
            'score': round(float(best_confidence) + (support_count * 9.0) + (source_count * 3.0), 2),
            'rank_priority': round(rank_priority, 4),
            'support_engines': support_engines,
            'regions': sorted([region for region in group['regions'] if region]),
            'origins': sorted([origin for origin in group['origins'] if origin]),
            'source_types': sorted([item for item in group['source_types'] if item]),
            'analysis_modes': sorted([mode for mode in group['analysis_modes'] if mode]),
            'analysis_ids': sorted([aid for aid in group['analysis_ids'] if aid]),
            'minute_index': minute_index,
            'minute_range': minute_range,
            'timestamp_seconds': round(timestamp_seconds, 4) if timestamp_seconds >= 0 else -1.0,
            'timestamp_label': _format_timecode(timestamp_seconds) if timestamp_seconds >= 0 else 'Indefinido',
            'frame_index': frame_index,
            'frame_order': frame_order,
            'frame_path': frame_path,
            'frame_url': f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else '',
            'crop_raw_path': crop_raw_path,
            'crop_raw_url': f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}" if crop_raw_path else '',
            'crop_treated_path': crop_treated_path,
            'crop_treated_url': f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}" if crop_treated_path else '',
            'best_frame': best_frame,
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
        candidate['label'] = f"{candidate['minute_range']} | {candidate['text']} | parcial"
        candidate['support_label'] = f"{candidate['support_count']} motor(es) | {candidate['source_count']} leitura(s)"
        candidate['minute_label'] = f'{minute_index:02d}' if minute_index >= 0 else 'Ind'
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            float(item.get('rank_priority', 0.0)),
            float(item.get('support_count', 0)),
            float(item.get('best_confidence', 0.0)),
            float(item.get('avg_confidence', 0.0)),
            float(item.get('source_frame_count', 0)),
            -float(item.get('fragment_length', 0)),
        ),
        reverse=True,
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate['rank'] = index

    return candidates[:max(1, int(max_candidates or 24))], candidates


def select_candidates_by_ids(frame_candidates, selected_candidate_ids):
    candidates = [entry for entry in frame_candidates if isinstance(entry, dict)]
    if not selected_candidate_ids:
        return []
    selected = []
    selected_ids = []
    for item in selected_candidate_ids:
        candidate_id = str(item).strip()
        if candidate_id:
            selected_ids.append(candidate_id)
    candidate_map = {
        str(candidate.get('candidate_id', '')).strip(): candidate
        for candidate in candidates
        if str(candidate.get('candidate_id', '')).strip()
    }
    for candidate_id in selected_ids:
        candidate = candidate_map.get(candidate_id)
        if candidate is not None and candidate not in selected:
            selected.append(candidate)
    return selected


def normalize_video_target_entry(target):
    target = dict(target) if isinstance(target, dict) else {}
    best_frame = dict(target.get('best_frame', {})) if isinstance(target.get('best_frame'), dict) else {}

    frame_path = _safe_text(target.get('frame_path', '') or best_frame.get('frame_path', ''), '')
    crop_raw_path = _safe_text(target.get('crop_raw_path', '') or best_frame.get('crop_raw_path', ''), '')
    crop_treated_path = _safe_text(target.get('crop_treated_path', '') or best_frame.get('crop_treated_path', ''), '')
    text = _safe_text(target.get('text', '') or best_frame.get('ocr', '') or best_frame.get('text', ''), 'SEM_TEXTO')
    pattern = _safe_text(target.get('pattern', '') or best_frame.get('pattern', ''), 'Indefinido')
    timestamp_seconds = _safe_float(target.get('timestamp_seconds', best_frame.get('timestamp_seconds', 0.0)), 0.0)
    frame_index = _safe_int(target.get('frame_index', best_frame.get('frame_index', 0)), 0)
    frame_order = _safe_int(target.get('frame_order', best_frame.get('frame_order', 0)), 0)
    minute_index = _safe_int(target.get('minute_index', int(timestamp_seconds // 60 if timestamp_seconds else 0)), 0)
    minute_range = _safe_text(target.get('minute_range', ''), '')
    if not minute_range:
        minute_start = max(0, minute_index) * 60
        minute_range = f'{_format_timecode(minute_start)}-{_format_timecode(minute_start + 59.999)}'

    best_confidence = _safe_float(target.get('best_confidence', target.get('confidence', best_frame.get('confidence', 0.0))), 0.0)
    best_score = _safe_float(target.get('best_score', target.get('score', best_frame.get('score', 0.0))), 0.0)
    avg_confidence = _safe_float(target.get('avg_confidence', target.get('confidence', best_confidence)), best_confidence)
    avg_score = _safe_float(target.get('avg_score', target.get('score', best_score)), best_score)
    frames_count = _safe_int(target.get('frames_count', target.get('support_count', 1)), 1)

    normalized = dict(target)
    normalized['best_frame'] = best_frame or dict(target)
    normalized['frame_path'] = frame_path
    normalized['frame_url'] = f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else ''
    normalized['crop_raw_path'] = crop_raw_path
    normalized['crop_raw_url'] = f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}" if crop_raw_path else ''
    normalized['crop_treated_path'] = crop_treated_path
    normalized['crop_treated_url'] = f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}" if crop_treated_path else ''
    normalized['crop_preview_path'] = crop_treated_path or crop_raw_path or frame_path
    normalized['crop_preview_url'] = (
        f"/artifact/{quote_plus(os.path.basename(crop_treated_path))}"
        if crop_treated_path
        else (
            f"/artifact/{quote_plus(os.path.basename(crop_raw_path))}"
            if crop_raw_path
            else (f"/artifact/{quote_plus(os.path.basename(frame_path))}" if frame_path else '')
        )
    )
    normalized['text'] = text
    normalized['pattern'] = pattern
    normalized['timestamp_seconds'] = round(timestamp_seconds, 4)
    normalized['timestamp_label'] = _format_timecode(timestamp_seconds)
    normalized['frame_index'] = frame_index
    normalized['frame_order'] = frame_order
    normalized['minute_index'] = minute_index
    normalized['minute_label'] = f'{minute_index:02d}'
    normalized['minute_range'] = minute_range
    normalized['best_confidence'] = round(best_confidence, 2)
    normalized['best_score'] = round(best_score, 2)
    normalized['style_rank_priority'] = round(_safe_float(target.get('style_rank_priority', best_frame.get('style_rank_priority', 0.0)), 0.0), 3)
    normalized['support_rank'] = round(_safe_float(target.get('support_rank', best_frame.get('support_rank', target.get('support_count', 0.0))), 0.0), 3)
    normalized['avg_confidence'] = round(avg_confidence, 2)
    normalized['avg_score'] = round(avg_score, 2)
    normalized['frames_count'] = frames_count
    normalized['label'] = _safe_text(target.get('label', ''), f'{minute_range} | {text} | {pattern}')
    normalized['support_label'] = _safe_text(target.get('support_label', ''), f'{frames_count} quadros | minuto {minute_index:02d}')
    normalized['display_label'] = f'{minute_range} | {text} | {pattern}'
    return normalized
