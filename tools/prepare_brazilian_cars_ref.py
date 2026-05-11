#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_URL = "https://github.com/gpupo/brazilian-cars.git"
DEFAULT_CLONE_DIR = PROJECT_ROOT / "data" / "datasets" / "brazilian-cars-ref" / "repo"
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "data" / "datasets" / "brazilian-cars-ref" / "models.json"
DEFAULT_OUTPUT_RAW_JSON = PROJECT_ROOT / "data" / "datasets" / "brazilian-cars-ref" / "vehicles_raw.json"

SQL_CANDIDATES = [
    Path("Resources/data/current/bc_vehicle.sql"),
    Path("resources/data/current/bc_vehicle.sql"),
    Path("data/current/bc_vehicle.sql"),
]

MODELS_TXT_CANDIDATES = [
    Path("Resources/data/current/models.txt"),
    Path("resources/data/current/models.txt"),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clona/atualiza gpupo/brazilian-cars e converte o arquivo bc_vehicle.sql "
            "em JSON para uso no pipeline OSINT."
        )
    )
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL, help="URL do repositório a clonar")
    parser.add_argument(
        "--clone-dir",
        default=str(DEFAULT_CLONE_DIR),
        help="Pasta destino do clone",
    )
    parser.add_argument(
        "--output-json",
        default=str(DEFAULT_OUTPUT_JSON),
        help="Arquivo JSON de saída (estrutura por fabricante/modelo)",
    )
    parser.add_argument(
        "--output-raw-json",
        default=str(DEFAULT_OUTPUT_RAW_JSON),
        help="Arquivo JSON de saída com linhas brutas da tabela",
    )
    parser.add_argument(
        "--skip-clone",
        action="store_true",
        help="Não executa clone/pull; usa clone-dir existente",
    )
    parser.add_argument(
        "--no-pull",
        action="store_true",
        help="Quando clone-dir já existe, não executa git pull",
    )
    return parser.parse_args()


def run_command(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def ensure_git_available() -> None:
    if shutil.which("git") is None:
        raise RuntimeError("git não encontrado no PATH.")


def clone_or_update_repo(repo_url: str, clone_dir: Path, allow_pull: bool) -> None:
    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    if clone_dir.exists() and (clone_dir / ".git").exists():
        if allow_pull:
            print(f"[INFO] Repositório já existe, atualizando: {clone_dir}")
            run_command(["git", "pull", "--ff-only"], cwd=clone_dir)
        else:
            print(f"[INFO] Repositório já existe, mantendo estado atual: {clone_dir}")
        return

    if clone_dir.exists() and not (clone_dir / ".git").exists():
        raise RuntimeError(
            f"Destino existe mas não é repositório git: {clone_dir}. "
            "Remova ou escolha outro --clone-dir."
        )

    print(f"[INFO] Clonando repositório: {repo_url}")
    run_command(["git", "clone", repo_url, str(clone_dir)])


def try_read_text(path: Path) -> str:
    encodings = ["utf-8", "utf-8-sig", "latin-1"]
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"Não foi possível ler {path} com os encodings testados.")


def locate_sql_file(clone_dir: Path) -> Path:
    for candidate in SQL_CANDIDATES:
        maybe = clone_dir / candidate
        if maybe.exists():
            return maybe

    matches = list(clone_dir.rglob("bc_vehicle.sql"))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        "bc_vehicle.sql não encontrado no repositório clonado. "
        "Confirme a estrutura em Resources/data/current/."
    )


def locate_models_txt_file(clone_dir: Path) -> Path:
    for candidate in MODELS_TXT_CANDIDATES:
        maybe = clone_dir / candidate
        if maybe.exists():
            return maybe

    matches = list(clone_dir.rglob("models.txt"))
    if matches:
        return matches[0]

    raise FileNotFoundError(
        "models.txt não encontrado no repositório clonado. "
        "Confirme a estrutura em Resources/data/current/."
    )


def split_sql_tuples(values_blob: str) -> list[str]:
    tuples: list[str] = []
    depth = 0
    in_quote = False
    escaped = False
    start = -1

    for i, ch in enumerate(values_blob):
        if in_quote:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_quote = False
            continue

        if ch == "'":
            in_quote = True
            continue

        if ch == "(":
            if depth == 0:
                start = i + 1
            depth += 1
            continue

        if ch == ")":
            depth -= 1
            if depth == 0 and start >= 0:
                tuples.append(values_blob[start:i])
                start = -1
            continue

    return tuples


def parse_tuple_values(tuple_values: str) -> list[Any]:
    reader = csv.reader([tuple_values], delimiter=",", quotechar="'", escapechar="\\")
    parsed = next(reader)
    return [coerce_sql_value(value) for value in parsed]


def coerce_sql_value(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""

    upper = value.upper()
    if upper == "NULL":
        return None

    if re.fullmatch(r"[-+]?\d+", value):
        try:
            return int(value)
        except ValueError:
            return value

    if re.fullmatch(r"[-+]?\d+\.\d+", value):
        try:
            return float(value)
        except ValueError:
            return value

    return value


def parse_sql_insert_rows(sql_text: str) -> list[dict[str, Any]]:
    pattern = re.compile(
        r"INSERT\s+INTO\s+`?[^`\s\(]+`?\s*\((?P<cols>.*?)\)\s*VALUES\s*(?P<vals>.*?);",
        flags=re.IGNORECASE | re.DOTALL,
    )

    rows: list[dict[str, Any]] = []
    for match in pattern.finditer(sql_text):
        columns_blob = match.group("cols")
        values_blob = match.group("vals")

        columns = [col.strip().strip("`").strip() for col in columns_blob.split(",")]
        tuple_blobs = split_sql_tuples(values_blob)

        for tuple_blob in tuple_blobs:
            values = parse_tuple_values(tuple_blob)
            row: dict[str, Any] = {}
            for idx, column in enumerate(columns):
                row[column] = values[idx] if idx < len(values) else None
            rows.append(row)

    return rows


def parse_models_txt_rows(models_txt: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current_make = ""

    make_pattern = re.compile(
        r"^\+\-+\+\-+\+\-+\s+(?P<make>.+?)\s+\-+\+\-+\+\-+\+\-+\+$"
    )
    row_pattern = re.compile(
        r"^\|\s*(?P<id>\d+)\s*\|\s*(?P<family>.*?)\s*\|\s*(?P<name>.*?)\s*\|\s*(?P<year>\d{4})\s*\|\s*(?P<fuel>.*?)\s*\|\s*(?P<model_id>\d+)\s*\|$"
    )

    for raw_line in models_txt.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue

        make_match = make_pattern.match(line)
        if make_match:
            current_make = make_match.group("make").strip()
            continue

        row_match = row_pattern.match(line)
        if row_match and current_make:
            rows.append(
                {
                    "id": int(row_match.group("id")),
                    "family": row_match.group("family").strip(),
                    "name": row_match.group("name").strip(),
                    "model_year": int(row_match.group("year")),
                    "fuel_type": row_match.group("fuel").strip(),
                    "model_identifier": int(row_match.group("model_id")),
                    "manufacturer": current_make,
                }
            )

    return rows


def normalize_records(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_make: dict[str, dict[str, Any]] = {}

    for row in rows:
        make = str(row.get("manufacturer") or row.get("make") or "").strip()
        model = str(row.get("family") or row.get("model") or row.get("name") or "").strip()
        variant = str(row.get("name") or "").strip()

        if not make or not model:
            continue

        year = row.get("model_year") or row.get("year")
        fuel = row.get("fuel_type")
        model_identifier = row.get("model_identifier")

        make_key = make.upper()
        model_key = model.upper()

        make_bucket = by_make.setdefault(make_key, {})
        model_entry = make_bucket.setdefault(
            model_key,
            {
                "nome": model,
                "anos": set(),
                "variantes": set(),
                "combustiveis": set(),
                "model_identifiers": set(),
            },
        )

        if isinstance(year, int):
            model_entry["anos"].add(year)
        if variant:
            model_entry["variantes"].add(variant)
        if isinstance(fuel, str) and fuel.strip():
            model_entry["combustiveis"].add(fuel.strip())
        if isinstance(model_identifier, int):
            model_entry["model_identifiers"].add(model_identifier)

    models: dict[str, list[dict[str, Any]]] = {}
    for make_key, model_map in sorted(by_make.items()):
        models[make_key] = []
        for _, model_entry in sorted(model_map.items(), key=lambda item: item[0]):
            models[make_key].append(
                {
                    "nome": model_entry["nome"],
                    "anos": sorted(model_entry["anos"]),
                    "variantes": sorted(model_entry["variantes"]),
                    "combustiveis": sorted(model_entry["combustiveis"]),
                    "model_identifiers": sorted(model_entry["model_identifiers"]),
                }
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "gpupo/brazilian-cars (bc_vehicle.sql)",
        "total_makes": len(models),
        "total_models": sum(len(items) for items in models.values()),
        "models": models,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    clone_dir = Path(args.clone_dir).resolve()
    output_json = Path(args.output_json).resolve()
    output_raw_json = Path(args.output_raw_json).resolve()

    if not args.skip_clone:
        ensure_git_available()
        clone_or_update_repo(args.repo_url, clone_dir, allow_pull=not args.no_pull)
    else:
        if not clone_dir.exists():
            raise FileNotFoundError(
                f"--skip-clone foi informado, mas clone-dir não existe: {clone_dir}"
            )

    sql_file = locate_sql_file(clone_dir)
    print(f"[INFO] Usando SQL: {sql_file}")

    sql_text = try_read_text(sql_file)
    rows = parse_sql_insert_rows(sql_text)
    source_label = "gpupo/brazilian-cars (bc_vehicle.sql)"

    if not rows:
        models_txt_file = locate_models_txt_file(clone_dir)
        print(
            "[INFO] bc_vehicle.sql sem INSERTs. "
            f"Aplicando fallback em: {models_txt_file}"
        )
        rows = parse_models_txt_rows(try_read_text(models_txt_file))
        source_label = "gpupo/brazilian-cars (models.txt fallback)"

    if not rows:
        raise RuntimeError(
            "Não foi possível extrair registros de bc_vehicle.sql nem de models.txt."
        )

    normalized = normalize_records(rows)
    normalized["source"] = source_label

    raw_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_label,
        "origin_file": str(sql_file),
        "total_rows": len(rows),
        "rows": rows,
    }

    write_json(output_json, normalized)
    write_json(output_raw_json, raw_payload)

    print(f"[OK] JSON estruturado salvo em: {output_json}")
    print(f"[OK] JSON bruto salvo em: {output_raw_json}")
    print(
        "[OK] Resumo -> "
        f"marcas: {normalized['total_makes']}, modelos: {normalized['total_models']}, linhas: {len(rows)}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        print(f"[ERRO] Comando falhou ({exc.returncode}): {exc.cmd}", file=sys.stderr)
        raise SystemExit(exc.returncode)
    except Exception as exc:
        print(f"[ERRO] {exc}", file=sys.stderr)
        raise SystemExit(1)
