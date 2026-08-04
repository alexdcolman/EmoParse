#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate

BUILD=".build/prompt_regression/gemma4"
CONFIG="$BUILD/config.gemma4.yaml"
mkdir -p "$BUILD"

echo "=== Huella de prompts ==="
python scripts/prompt_footprint.py | tee "$BUILD/prompt_footprint.log"

python - "$CONFIG" <<'PY'
from pathlib import Path
import sys
import yaml

out = Path(sys.argv[1])
config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))

model = config["models"]["gemma4-31b"]
assert int(model["context_length"]) == 4096, model
assert int(model["max_tokens"]) == 2048, model

for stage in (
    "metadata",
    "enunciation",
    "enunciator_id",
    "emotions",
    "characterizer",
):
    config["pipeline"]["stages"][stage] = "gemma4-31b"

config["versions"] = {
    "knowledge": "v19",
    "prompt": "v54",
    "ontology": "v27",
    "schema": "v41",
}

out.write_text(
    yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
    encoding="utf-8",
)
print(f"Config preparada: {out}")
print(
    "Gemma4:",
    f"context_length={model['context_length']}",
    f"max_tokens={model['max_tokens']}",
)
PY

run_one() {
  local name="$1"
  local input="$2"
  local db="$BUILD/${name}.sqlite"
  local exports="$BUILD/${name}_exports"
  local log="$BUILD/${name}.log"
  local rc_file="$BUILD/${name}.exit_code"

  rm -f "$db" "$rc_file"
  rm -rf "$exports"

  echo
  echo "=== Run: $name ==="

  set +e
  python -m emoparse run \
    --config "$CONFIG" \
    --input "$input" \
    --run-id "gemma4_prompt_${name}" \
    --db "$db" \
    --genre tuit \
    --stages technoparse,metadata,enunciation,emotions,explode_emotions,normalize_emotions,characterizer \
    --overwrite-db \
    2>&1 | tee "$log"
  local rc="${PIPESTATUS[0]}"
  set -e

  printf '%s\n' "$rc" > "$rc_file"

  if [[ -f "$db" ]]; then
    python -m emoparse status --db "$db" \
      2>&1 | tee "$BUILD/${name}_status.log" || true

    mkdir -p "$exports"
    python -m emoparse export --db "$db" --output-dir "$exports" \
      2>&1 | tee "$BUILD/${name}_export.log" || true
  fi
}

run_one "semantic_23" "data/ejemplos/tuits_ejemplo.jsonl"
run_one "long_thread_12" \
  "evals/prompt_regression/gemma4_posts/long_thread.jsonl"

echo
echo "=== Informe automático ==="

python - "$BUILD" <<'PY'
from pathlib import Path
import re
import sqlite3
import sys

build = Path(sys.argv[1])
names = ("semantic_23", "long_thread_12")
risk_re = re.compile(
    r"context|token|too long|exceed|truncat|schema|json|grammar",
    re.IGNORECASE,
)

lines = [
    "# Regresión de prompts con gemma4-31b",
    "",
    "Versiones: knowledge=v19, prompt=v54, ontology=v27, schema=v41.",
    "",
]

for name in names:
    db = build / f"{name}.sqlite"
    log = build / f"{name}.log"
    rc_file = build / f"{name}.exit_code"
    rc = rc_file.read_text(encoding="utf-8").strip() if rc_file.exists() else "sin dato"

    lines.extend([f"## {name}", "", f"- exit code: `{rc}`"])

    if db.exists():
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row

        def count(query: str) -> int:
            return int(con.execute(query).fetchone()[0])

        run = con.execute(
            """
            SELECT run_id, status, knowledge_version, prompt_version,
                   ontology_version, schema_version
            FROM runs
            ORDER BY started_at DESC
            LIMIT 1
            """
        ).fetchone()

        lines.append(f"- run: `{dict(run) if run else None}`")
        lines.append(f"- posts: {count('SELECT COUNT(*) FROM discursos')}")
        lines.append(f"- unidades: {count('SELECT COUNT(*) FROM frases')}")
        lines.append(f"- emociones: {count('SELECT COUNT(*) FROM emociones')}")

        phrase_errors = count(
            """
            SELECT COUNT(*) FROM frases
            WHERE emociones_error IS NOT NULL
               OR emociones_pass2_error IS NOT NULL
            """
        )
        characterizer_errors = count(
            """
            SELECT COUNT(*) FROM emociones
            WHERE caracterizacion_error IS NOT NULL
            """
        )
        lines.append(f"- errores emotions: {phrase_errors}")
        lines.append(f"- errores characterizer: {characterizer_errors}")

        models = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT model_alias FROM llm_cache ORDER BY model_alias"
            )
        ]
        lines.append(f"- modelos registrados: `{models}`")
        con.close()
    else:
        lines.append("- base no creada")

    matches: list[str] = []
    if log.exists():
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if risk_re.search(line):
                matches.append(line.strip())
    lines.append(f"- líneas de riesgo en log: {len(matches)}")
    for match in matches[:20]:
        lines.append(f"  - `{match[:300]}`")
    lines.append("")

report = build / "report.md"
report.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
print(report)
print(report.read_text(encoding="utf-8"))
PY

OUT="$HOME/Downloads/EmoParse_Gemma4_prompt_regression_$(date +%Y%m%d_%H%M%S).zip"
zip -q -r "$OUT" "$BUILD"

echo
sha256sum "$OUT"
echo
echo "Resultados:"
echo "$BUILD"
echo "$OUT"
