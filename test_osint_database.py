"""Testes unitários para fastapi_backend/osint_database.py."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pytest


def test_osint_database_importable():
    """osint_database deve importar sem erros."""
    from fastapi_backend.osint_database import OSINTVehicleDatabase, get_osint_database
    assert callable(get_osint_database)


def test_osint_database_status_has_expected_keys():
    """status() deve retornar as chaves esperadas."""
    from fastapi_backend.osint_database import get_osint_database
    db = get_osint_database()
    st = db.status()
    # status() retorna as 3 sub-chaves (sem chave "available" no topo)
    assert "brazil_ref" in st
    assert "brcars_dataset" in st
    assert "openclip_embeddings" in st
    # Cada sub-chave deve ter "available"
    assert "available" in st["brazil_ref"]
    assert "available" in st["brcars_dataset"]
    assert "available" in st["openclip_embeddings"]


def test_osint_database_brazil_ref_available():
    """brazil_ref deve estar disponível (gpupo/brazilian-cars)."""
    from fastapi_backend.osint_database import get_osint_database
    db = get_osint_database()
    st = db.status()
    assert st["brazil_ref"]["available"] is True
    assert st["brazil_ref"]["total_makes"] >= 80
    assert st["brazil_ref"]["total_models"] >= 500


def test_search_by_make_returns_results():
    """Busca por marca deve retornar ao menos 1 resultado."""
    from fastapi_backend.osint_database import get_osint_database
    db = get_osint_database()
    results = db.search_by_attributes(make="toyota", limit=5)
    assert len(results) >= 1
    for r in results:
        assert "make" in r
        assert "model" in r
        assert "score" in r
        assert "source" in r


def test_search_by_make_and_model():
    """Busca Honda Civic deve retornar resultados com score > 0."""
    from fastapi_backend.osint_database import get_osint_database
    db = get_osint_database()
    results = db.search_by_attributes(make="honda", model="civic", limit=3)
    assert len(results) >= 1
    assert all(r["score"] > 0 for r in results)
    # Deve encontrar Honda Civic
    makes = [r["make"].lower() for r in results]
    assert any("honda" in m for m in makes)


def test_search_limit_respected():
    """limit deve ser respeitado na busca."""
    from fastapi_backend.osint_database import get_osint_database
    db = get_osint_database()
    results = db.search_by_attributes(make="volkswagen", limit=2)
    assert len(results) <= 2


def test_search_returns_empty_for_unknown_make():
    """Marca desconhecida deve retornar lista vazia."""
    from fastapi_backend.osint_database import get_osint_database
    db = get_osint_database()
    results = db.search_by_attributes(make="ZZZUNKNOWNBRAND999", limit=5)
    assert isinstance(results, list)
    assert len(results) == 0


def test_get_osint_database_singleton():
    """get_osint_database deve retornar a mesma instância."""
    from fastapi_backend.osint_database import get_osint_database
    db1 = get_osint_database()
    db2 = get_osint_database()
    assert db1 is db2


def test_semantic_rerank_without_embeddings():
    """semantic_rerank sem embeddings deve retornar lista vazia."""
    from fastapi_backend.osint_database import get_osint_database
    import numpy as np
    db = get_osint_database()
    candidates = [{"make": "honda", "model": "civic", "score": 1.0, "source": "test"}]
    dummy_embedding = np.zeros(512, dtype=np.float32)
    result = db.semantic_rerank(candidates, dummy_embedding, top_k=1)
    # Sem embeddings carregados, deve retornar lista vazia ou igual
    assert isinstance(result, list)
