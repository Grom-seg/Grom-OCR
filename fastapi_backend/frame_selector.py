"""
Frame Selector e HDR Merge — Grom OCR

Funcionalidades:
  - select_best_frame(): escolhe o frame mais nítido de uma sequência (burst)
  - merge_hdr(): fusão de múltiplas exposições via Mertens (OpenCV)
  - lap_variance(): variância do Laplaciano (métrica de nitidez)

Sem dependências externas além de opencv-python.

Uso típico:
  # Burst de 5 frames → melhor frame
  best = select_best_frame(frames)

  # Multi-exposição → HDR fusion
  hdr  = merge_hdr([frame_sub, frame_normal, frame_over])
"""

import logging
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Métrica de nitidez
# ---------------------------------------------------------------------------

def lap_variance(img: np.ndarray) -> float:
    """
    Variância do Laplaciano como métrica de nitidez.

    Maior valor = imagem mais nítida.
    Funciona com imagens BGR ou grayscale.

    Args:
        img: np.ndarray BGR ou GRAY.

    Returns:
        float — variância do Laplaciano. Retorna 0.0 para imagem vazia.
    """
    if img is None or img.size == 0:
        return 0.0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


# ---------------------------------------------------------------------------
# Seleção de melhor frame
# ---------------------------------------------------------------------------

def select_best_frame(frames: List[np.ndarray]) -> np.ndarray:
    """
    Seleciona o frame mais nítido de uma sequência burst.

    Usa variância do Laplaciano como métrica — sem IA, sem modelo.
    Indicado para câmeras que capturam burst de 3–10 frames por disparo.

    Args:
        frames: lista de np.ndarray BGR. Frames None/vazios são ignorados.

    Returns:
        Frame com maior nitidez. Se todos forem None/vazios, retorna o
        primeiro não-None encontrado.

    Raises:
        ValueError: se todos os frames forem None ou lista vazia.
    """
    if not frames:
        raise ValueError('Lista de frames vazia.')

    valid = [(i, f) for i, f in enumerate(frames) if f is not None and f.size > 0]
    if not valid:
        raise ValueError('Nenhum frame válido na lista.')

    best_idx, best_frame = valid[0]
    best_var = lap_variance(best_frame)

    for i, frame in valid[1:]:
        var = lap_variance(frame)
        if var > best_var:
            best_var = var
            best_idx = i
            best_frame = frame

    logger.debug(
        'select_best_frame: %d frames analisados, melhor=%d (lap_var=%.1f)',
        len(valid), best_idx, best_var,
    )
    return best_frame


# ---------------------------------------------------------------------------
# HDR Merge via Mertens
# ---------------------------------------------------------------------------

def merge_hdr(
    frames: List[np.ndarray],
    contrast_weight: float = 1.0,
    saturation_weight: float = 1.0,
    exposure_weight: float = 1.0,
) -> np.ndarray:
    """
    Fusão de múltiplas exposições usando algoritmo de Mertens (OpenCV).

    Não requer EXIF nem metadados de câmera. Ideal para:
      - Sequências burst com variação natural de exposição
      - Cenas com alto contraste (faróis + fundo escuro)
      - Condições ccpd_fn equivalentes (noite, contraluz)

    Args:
        frames: lista de imagens BGR com dimensões compatíveis.
                Frames None/vazios são filtrados.
        contrast_weight: peso do contraste local (default 1.0).
        saturation_weight: peso da saturação (default 1.0).
        exposure_weight: peso do nível de exposição (default 1.0).

    Returns:
        Imagem BGR uint8 com fusão de exposições.

    Notes:
        - 1 frame: retorna diretamente sem processamento.
        - Frames com tamanhos diferentes: redimensiona para o menor.
        - A fusão de Mertens não produz HDR 32-bit; produz LDR otimizado.
    """
    if not frames:
        raise ValueError('Lista de frames vazia para HDR merge.')

    valid = [f for f in frames if f is not None and f.size > 0]
    if not valid:
        raise ValueError('Nenhum frame válido para HDR merge.')

    if len(valid) == 1:
        return valid[0]

    # Normaliza tamanho para o menor (evita artefatos de alinhamento)
    h_min = min(f.shape[0] for f in valid)
    w_min = min(f.shape[1] for f in valid)

    resized = [
        cv2.resize(f, (w_min, h_min), interpolation=cv2.INTER_AREA)
        if f.shape[:2] != (h_min, w_min) else f
        for f in valid
    ]

    merge = cv2.createMergeMertens(
        contrast_weight=contrast_weight,
        saturation_weight=saturation_weight,
        exposure_weight=exposure_weight,
    )
    fused_f32 = merge.process(resized)

    # Converte de float [0,1] para uint8 [0,255]
    fused = np.clip(fused_f32 * 255.0, 0, 255).astype(np.uint8)

    logger.debug(
        'merge_hdr: fundiu %d frames → shape=%s, mean=%.1f',
        len(resized), fused.shape, fused.mean(),
    )
    return fused


# ---------------------------------------------------------------------------
# Utilitário: carrega lista de caminhos em frames
# ---------------------------------------------------------------------------

def load_frames_from_paths(paths: List[str]) -> List[np.ndarray]:
    """
    Carrega imagens de disco como lista de arrays BGR.

    Usa fallback np.fromfile para paths Unicode no Windows.

    Args:
        paths: lista de caminhos de arquivo.

    Returns:
        Lista de np.ndarray. Frames que falharam no carregamento são None.
    """
    frames = []
    for path in paths:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            try:
                data = np.fromfile(path, dtype=np.uint8)
                img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size > 0 else None
            except Exception:
                img = None
        if img is None:
            logger.warning('load_frames_from_paths: falha ao carregar %s', path)
        frames.append(img)
    return frames
