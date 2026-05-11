"""
Semantic Search veicular com OpenCLIP.

Traduz texto ou imagem em embeddings densos para busca semântica
sobre candidatos de marca/modelo de veículos brasileiros.

Design:
- Lazy init: só carrega modelo quando necessário.
- Fallback gracioso: quando open_clip não instalado, retorna candidatos
  sem score semântico (pipeline não quebra).
- Suporta: ViT-B-32 (padrão), outros modelos open_clip via parâmetros.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Import opcional de open_clip
# ---------------------------------------------------------------------------
try:
    import open_clip  # type: ignore

    _OPEN_CLIP_AVAILABLE = True
except ImportError:
    open_clip = None  # type: ignore
    _OPEN_CLIP_AVAILABLE = False
    logger.info(
        "semantic_search: open_clip não disponível. "
        "Instale com: pip install open-clip-torch  "
        "— busca semântica desativada."
    )

try:
    import torch  # type: ignore

    _TORCH_AVAILABLE = True
except ImportError:
    torch = None  # type: ignore
    _TORCH_AVAILABLE = False


# ---------------------------------------------------------------------------
# SemanticVehicleSearch
# ---------------------------------------------------------------------------


class SemanticVehicleSearch:
    """
    Busca semântica baseada em OpenCLIP.

    Uso principal:
    - embed_text("Toyota Corolla prata 2022") → vetor 512-d
    - embed_image(img_array)                  → vetor 512-d
    - search_query("Sedan prata 2020-2022", candidates) → candidatos reordenados
    """

    def __init__(
        self,
        model_name: str = "ViT-B-32",
        pretrained: str = "openai",
        device: Optional[str] = None,
    ) -> None:
        if not _OPEN_CLIP_AVAILABLE or not _TORCH_AVAILABLE:
            raise RuntimeError(
                "open_clip e torch são necessários para SemanticVehicleSearch. "
                "Execute: pip install open-clip-torch"
            )

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("SemanticVehicleSearch: carregando %s/%s em %s…", model_name, pretrained, self.device)

        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=pretrained
        )
        self.model = self.model.to(self.device)
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer(model_name)
        logger.info("SemanticVehicleSearch: modelo carregado.")

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    def embed_text(self, text: str) -> np.ndarray:
        """Texto → vetor normalizado (float32, shape [D])."""
        with torch.no_grad():
            tokens = self.tokenizer([text]).to(self.device)
            features = self.model.encode_text(tokens)
            features = features / (features.norm(dim=-1, keepdim=True) + 1e-8)
        return features.cpu().numpy()[0].astype(np.float32)

    def embed_image(self, image: np.ndarray) -> np.ndarray:
        """
        Array HxWx3 (uint8 BGR ou RGB) → vetor normalizado (float32, shape [D]).
        Usa preprocess do open_clip (resize + normalize).
        """
        from PIL import Image as PILImage  # type: ignore

        if image.shape[2] == 3:
            pil_img = PILImage.fromarray(image[..., ::-1])  # BGR → RGB
        else:
            pil_img = PILImage.fromarray(image)

        img_tensor = self.preprocess(pil_img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            features = self.model.encode_image(img_tensor)
            features = features / (features.norm(dim=-1, keepdim=True) + 1e-8)
        return features.cpu().numpy()[0].astype(np.float32)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_query(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        weight: float = 0.4,
    ) -> List[Dict[str, Any]]:
        """
        Reordena candidatos combinando score estrutural + score semântico.

        query:      texto livre, ex. "Sedan prata 2020-2022 Brasil"
        candidates: lista [{make, model, year, color, score, ...}]
        weight:     peso do score semântico no score final (0.0–1.0)

        Retorna candidatos com 'semantic_score' e 'score' atualizados.
        """
        if not candidates:
            return candidates

        try:
            query_emb = self.embed_text(query)

            for cand in candidates:
                desc = " ".join(
                    filter(
                        None,
                        [
                            str(cand.get("make", "")),
                            str(cand.get("model", "")),
                            str(cand.get("year", "")),
                            str(cand.get("color", "")),
                        ],
                    )
                )
                cand_emb = self.embed_text(desc)
                sim = float(np.dot(query_emb, cand_emb))  # ambos normalizados
                cand["semantic_score"] = sim
                cand["score"] = cand.get("score", 0.8) + weight * sim

            return sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)
        except Exception as exc:
            logger.warning("SemanticVehicleSearch.search_query falhou: %s", exc)
            return candidates

    def rerank_with_image(
        self,
        image: np.ndarray,
        candidates: List[Dict[str, Any]],
        weight: float = 0.5,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Reordena candidatos usando embedding de imagem real.
        Compara embedding de imagem com embedding textual de cada candidato.
        """
        if not candidates:
            return candidates

        try:
            img_emb = self.embed_image(image)

            for cand in candidates:
                desc = " ".join(
                    filter(
                        None,
                        [
                            str(cand.get("make", "")),
                            str(cand.get("model", "")),
                            str(cand.get("year", "")),
                            str(cand.get("color", "")),
                        ],
                    )
                )
                text_emb = self.embed_text(desc)
                sim = float(np.dot(img_emb, text_emb))
                cand["image_semantic_score"] = sim
                cand["score"] = cand.get("score", 0.8) + weight * sim

            return sorted(candidates, key=lambda x: x.get("score", 0.0), reverse=True)[:top_k]
        except Exception as exc:
            logger.warning("SemanticVehicleSearch.rerank_with_image falhou: %s", exc)
            return candidates[:top_k]


# ---------------------------------------------------------------------------
# Singleton com fallback
# ---------------------------------------------------------------------------

_semantic_search: Optional[SemanticVehicleSearch] = None
_init_failed: bool = False


def get_semantic_search() -> Optional[SemanticVehicleSearch]:
    """
    Lazy singleton.
    Retorna None se open_clip não estiver disponível (não quebra o pipeline).
    """
    global _semantic_search, _init_failed

    if _semantic_search is not None:
        return _semantic_search
    if _init_failed:
        return None

    try:
        _semantic_search = SemanticVehicleSearch()
        return _semantic_search
    except RuntimeError:
        logger.info("get_semantic_search: busca semântica indisponível (open_clip não instalado).")
        _init_failed = True
        return None
    except Exception as exc:
        logger.warning("get_semantic_search: falha inesperada: %s", exc)
        _init_failed = True
        return None


def is_semantic_search_available() -> bool:
    """Retorna True se OpenCLIP está disponível e carregado."""
    return _OPEN_CLIP_AVAILABLE and _TORCH_AVAILABLE
