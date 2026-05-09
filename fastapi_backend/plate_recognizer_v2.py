#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Plate Recognizer Client - Versão 2 (com enabled correto)
"""

import os
import requests
import logging
from typing import Dict, Any, Optional, List, Tuple

logger = logging.getLogger(__name__)

class PlateRecognizerClient:
    """Cliente para Plate Recognizer API."""

    def __init__(self):
        import os
        # Re-read env vars in case they were loaded after module import
        self.api_token = os.getenv('PLATE_RECOGNIZER_TOKEN', '') or os.environ.get('PLATE_RECOGNIZER_TOKEN', '')
        self.api_url = 'https://api.platerecognizer.com/v1/plate-reader/'
        self.timeout = int(os.getenv('PLATE_RECOGNIZER_TIMEOUT', '30') or 30)
        self.enabled = bool(self.api_token)  # Simples: se tem token, está habilitado

    def recognize(self, image_path: str, regions: List[str] = None) -> Optional[Dict[str, Any]]:
        """Reconhecer placa via Plate Recognizer API."""

        if not self.enabled:
            return None

        if not os.path.exists(image_path):
            logger.error(f"Arquivo não encontrado: {image_path}")
            return None

        try:
            with open(image_path, 'rb') as fp:
                response = requests.post(
                    self.api_url,
                    files={'upload': fp},
                    headers={'Authorization': f'Token {self.api_token}'},
                    params={'regions': ','.join(regions or ['br'])},
                    timeout=self.timeout
                )

            if response.status_code in (200, 201):
                result = response.json()
                logger.info(f"Plate Recognizer sucesso: {result.get('results', [])}")
                return result
            else:
                logger.error(f"Plate Recognizer erro {response.status_code}: {response.text[:300]}")
                return None

        except requests.Timeout:
            logger.error(f"Plate Recognizer timeout")
            return None
        except Exception as e:
            logger.error(f"Plate Recognizer falha: {e}")
            return None

    def extract_plate_text(self, result: Dict[str, Any]) -> Optional[str]:
        """Extrair texto de placa dos resultados."""
        if not result or 'results' not in result:
            return None

        results = result.get('results', [])
        if not results:
            return None

        best = max(results, key=lambda x: x.get('score', 0))
        return best.get('plate', None)

    def extract_metadata(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Extrair metadata útil dos resultados."""
        if not result or 'results' not in result:
            return {}

        results = result.get('results', [])
        if not results:
            return {}

        best = max(results, key=lambda x: x.get('score', 0))

        return {
            'plate': best.get('plate'),
            'confidence': best.get('score', 0),
            'vehicle_make': best.get('vehicle', {}).get('make', ''),
            'vehicle_model': best.get('vehicle', {}).get('model', ''),
            'vehicle_color': best.get('vehicle', {}).get('color', ''),
            'raw_result': best
        }


# Instância global
_plate_recognizer_client = None

def get_plate_recognizer() -> PlateRecognizerClient:
    """Obter cliente singleton."""
    global _plate_recognizer_client
    if _plate_recognizer_client is None:
        # Re-load env vars to ensure we get latest values
        import os
        from pathlib import Path
        _env_path = Path(__file__).parent.parent / '.env'
        if _env_path.exists():
            with open(_env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if key not in os.environ:
                            os.environ[key] = value.strip()

        _plate_recognizer_client = PlateRecognizerClient()
    return _plate_recognizer_client


def recognize_plate_external(image_path: str, regions: List[str] = None) -> Tuple[bool, Optional[str], Dict[str, Any]]:
    """Interface pública: reconhecer placa via serviço externo."""
    client = get_plate_recognizer()

    if not client.enabled:
        return False, None, {'error': 'Plate Recognizer não configurado'}

    result = client.recognize(image_path, regions)

    if not result:
        return False, None, {'error': 'Falha ao conectar com Plate Recognizer'}

    plate_text = client.extract_plate_text(result)
    metadata = client.extract_metadata(result)

    if plate_text:
        return True, plate_text, metadata
    else:
        return False, None, {'error': 'Nenhuma placa detectada'}
