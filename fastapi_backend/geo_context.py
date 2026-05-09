"""
Geo Context Analyzer - Grom OCR

Extrai metadados GPS EXIF de imagens e, quando disponível, faz reverse geocoding.
Suporta provedores:
- Mapbox (token em GROM_MAPBOX_TOKEN)
- HERE (api key em GROM_HERE_API_KEY)
- Nominatim (fallback sem chave)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

import requests
from PIL import ExifTags, Image

logger = logging.getLogger(__name__)

_GPS_TAG_ID = None
for _k, _v in ExifTags.TAGS.items():
    if _v == "GPSInfo":
        _GPS_TAG_ID = _k
        break


def _to_float(value: Any) -> Optional[float]:
    """Converte racional EXIF em float com tolerancia a formatos variados."""
    if value is None:
        return None
    try:
        # PIL pode trazer tuple(num, den) ou objeto Rational
        if isinstance(value, tuple) and len(value) == 2:
            den = float(value[1]) if float(value[1]) != 0 else 1.0
            return float(value[0]) / den
        return float(value)
    except Exception:
        return None


def _dms_to_decimal(dms: Any, ref: str) -> Optional[float]:
    """Converte coordenada DMS EXIF para decimal."""
    if not dms:
        return None
    try:
        degrees = _to_float(dms[0])
        minutes = _to_float(dms[1])
        seconds = _to_float(dms[2])
        if degrees is None or minutes is None or seconds is None:
            return None
        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
        if str(ref or "").upper() in ("S", "W"):
            decimal *= -1.0
        return decimal
    except Exception:
        return None


def extract_exif_gps(image_path: str) -> Dict[str, Any]:
    """Extrai coordenadas GPS do EXIF (quando existir)."""
    result: Dict[str, Any] = {
        "status": "no_gps_metadata",
        "gps_present": False,
        "gps_extracted": False,
        "latitude": None,
        "longitude": None,
        "altitude_m": None,
        "timestamp_utc": "",
    }

    if not os.path.exists(image_path):
        result["status"] = "file_not_found"
        return result

    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if not exif or _GPS_TAG_ID is None:
                return result

            gps_info_raw = None
            # Pillow expõe a IFD GPS de forma mais confiável via get_ifd
            try:
                gps_ifd = getattr(ExifTags, 'IFD', None)
                gps_ifd_id = getattr(gps_ifd, 'GPSInfo', None) if gps_ifd else None
                if gps_ifd_id is not None and hasattr(exif, 'get_ifd'):
                    gps_info_raw = exif.get_ifd(gps_ifd_id)
            except Exception:
                gps_info_raw = None

            if not gps_info_raw:
                gps_info_raw = exif.get(_GPS_TAG_ID)

            if not gps_info_raw:
                return result

            # Alguns arquivos retornam apenas o ponteiro inteiro para a IFD GPS.
            if isinstance(gps_info_raw, int):
                try:
                    gps_ifd = getattr(ExifTags, 'IFD', None)
                    gps_ifd_id = getattr(gps_ifd, 'GPSInfo', None) if gps_ifd else None
                    if gps_ifd_id is not None and hasattr(exif, 'get_ifd'):
                        gps_info_raw = exif.get_ifd(gps_ifd_id)
                except Exception:
                    pass

            if not hasattr(gps_info_raw, 'items'):
                return result

            result["gps_present"] = True

            gps_info = {}
            for tag_id, val in gps_info_raw.items():
                tag_name = ExifTags.GPSTAGS.get(tag_id, str(tag_id))
                gps_info[tag_name] = val

            lat = _dms_to_decimal(gps_info.get("GPSLatitude"), gps_info.get("GPSLatitudeRef", "N"))
            lon = _dms_to_decimal(gps_info.get("GPSLongitude"), gps_info.get("GPSLongitudeRef", "E"))
            alt = _to_float(gps_info.get("GPSAltitude"))

            if lat is None or lon is None:
                result.update(
                    {
                        "status": "gps_invalid",
                        "gps_extracted": False,
                        "gps_raw": gps_info,
                    }
                )
                return result

            # Coordenadas nulas ou NaN devem ser tratadas como metadado corrompido.
            if any(v != v for v in [lat, lon]):
                result.update(
                    {
                        "status": "gps_invalid",
                        "gps_extracted": False,
                        "gps_raw": gps_info,
                    }
                )
                return result

            result.update(
                {
                    "status": "gps_extracted",
                    "gps_present": True,
                    "gps_extracted": True,
                    "latitude": round(lat, 7),
                    "longitude": round(lon, 7),
                    "altitude_m": round(alt, 2) if alt is not None else None,
                    "timestamp_utc": str(gps_info.get("GPSTimeStamp", "")),
                    "gps_raw": gps_info,
                }
            )
            return result
    except Exception as exc:
        logger.warning("Falha ao extrair EXIF GPS: %s", exc)
        result["status"] = "gps_extraction_error"
        result["error"] = str(exc)
        return result


def _reverse_geocode_nominatim(lat: float, lon: float, timeout: int = 10) -> Dict[str, Any]:
    url = "https://nominatim.openstreetmap.org/reverse"
    headers = {
        "User-Agent": os.getenv("GROM_NOMINATIM_USER_AGENT", "grom-ocr-forensic/1.0")
    }
    params = {
        "lat": lat,
        "lon": lon,
        "format": "jsonv2",
        "zoom": 18,
        "addressdetails": 1,
    }
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return {
        "provider": "nominatim",
        "display_name": data.get("display_name", ""),
        "address": data.get("address", {}),
        "raw": data,
    }


def _reverse_geocode_here(lat: float, lon: float, api_key: str, timeout: int = 10) -> Dict[str, Any]:
    url = "https://revgeocode.search.hereapi.com/v1/revgeocode"
    params = {
        "at": f"{lat},{lon}",
        "lang": "pt-BR",
        "apiKey": api_key,
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    first = (data.get("items") or [{}])[0]
    return {
        "provider": "here",
        "display_name": first.get("title", ""),
        "address": first.get("address", {}),
        "raw": data,
    }


def _reverse_geocode_mapbox(lat: float, lon: float, token: str, timeout: int = 10) -> Dict[str, Any]:
    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{lon},{lat}.json"
    params = {
        "access_token": token,
        "language": "pt",
        "limit": 1,
    }
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    feat = (data.get("features") or [{}])[0]
    return {
        "provider": "mapbox",
        "display_name": feat.get("place_name", ""),
        "address": {
            "text": feat.get("text", ""),
            "context": feat.get("context", []),
        },
        "raw": data,
    }


def reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """Resolve coordenadas para endereço usando provedor disponível."""
    mapbox_token = os.getenv("GROM_MAPBOX_TOKEN", "").strip()
    here_api_key = os.getenv("GROM_HERE_API_KEY", "").strip()

    errors = []

    # Ordem de prioridade: Mapbox -> HERE -> Nominatim
    if mapbox_token:
        try:
            return _reverse_geocode_mapbox(lat, lon, mapbox_token)
        except Exception as exc:
            errors.append(f"mapbox:{exc}")

    if here_api_key:
        try:
            return _reverse_geocode_here(lat, lon, here_api_key)
        except Exception as exc:
            errors.append(f"here:{exc}")

    try:
        return _reverse_geocode_nominatim(lat, lon)
    except Exception as exc:
        errors.append(f"nominatim:{exc}")

    return {
        "provider": "none",
        "display_name": "",
        "address": {},
        "error": "reverse_geocode_failed",
        "details": errors,
    }


def analyze_spatial_context(image_path: str) -> Dict[str, Any]:
    """
    Pipeline completo de contexto geoespacial por imagem.

    Funciona mesmo sem placa detectada, focando em metadados da evidência.
    """
    gps = extract_exif_gps(image_path)
    result: Dict[str, Any] = {
        "status": gps.get("status", "unknown"),
        "gps_extracted": bool(gps.get("gps_extracted", False)),
        "latitude": gps.get("latitude"),
        "longitude": gps.get("longitude"),
        "altitude_m": gps.get("altitude_m"),
        "reverse_geocode": {},
        "spatial_evidence": {
            "source": os.path.basename(image_path),
            "image_has_gps": bool(gps.get("gps_extracted", False)),
        },
    }

    if not result["gps_extracted"]:
        return result

    lat = result.get("latitude")
    lon = result.get("longitude")
    if lat is None or lon is None:
        result["status"] = "gps_invalid"
        return result

    rev = reverse_geocode(float(lat), float(lon))
    result["reverse_geocode"] = rev
    result["status"] = "spatial_context_ready" if rev.get("provider") != "none" else "gps_only"
    return result


def get_geo_context_info() -> Dict[str, Any]:
    return {
        "mapbox_configured": bool(os.getenv("GROM_MAPBOX_TOKEN", "").strip()),
        "here_configured": bool(os.getenv("GROM_HERE_API_KEY", "").strip()),
        "nominatim_available": True,
    }
