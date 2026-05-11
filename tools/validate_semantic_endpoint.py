import json
import sys

sys.path.insert(0, "C:/Grom_OCR")

from fastapi.testclient import TestClient
from fastapi_backend.main import app


def main() -> None:
    client = TestClient(app)
    response = client.get(
        "/osint/search",
        params={
            "make": "honda",
            "model": "civic",
            "limit": 5,
            "query": "sedan branco urbano",
        },
    )
    payload = response.json()
    out = {
        "status_code": response.status_code,
        "status": payload.get("status"),
        "total": payload.get("total"),
        "semantic_reranking_applied": payload.get("semantic_reranking_applied"),
        "first_candidate": (payload.get("candidates") or [{}])[0],
    }

    with open("C:/Grom_OCR/resultado_osint_semantic_runtime.json", "w", encoding="utf-8") as fp:
        json.dump(out, fp, ensure_ascii=False, indent=2)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
