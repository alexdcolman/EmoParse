#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EMOPARSE_BIN="${EMOPARSE_BIN:-emoparse}"
PYTHON_BIN="${PYTHON_BIN:-python}"
CONFIG="${CONFIG:-config.yaml}"
SOURCE_DIR="${SOURCE_DIR:-data/golden_v2/source}"
RUN_DIR="${RUN_DIR:-runs/golden_v2}"
TARGET_POSTS="${TARGET_POSTS:-240}"
TARGET_ARTICLE_DOCUMENTS="${TARGET_ARTICLE_DOCUMENTS:-30}"
TARGET_SPEECH_DOCUMENTS="${TARGET_SPEECH_DOCUMENTS:-24}"
PAGINA12_CANDIDATES="${PAGINA12_CANDIDATES:-$((TARGET_ARTICLE_DOCUMENTS * 2))}"
TUIT_QUERY="${TUIT_QUERY:-Milei}"

TUIT_INPUT="$SOURCE_DIR/tuit.jsonl"
ARTICULO_INPUT="$SOURCE_DIR/articulo_periodistico.csv"
DISCURSO_INPUT="$SOURCE_DIR/discurso_presidencial.csv"

TUIT_DB="$RUN_DIR/tuit.sqlite"
ARTICULO_DB="$RUN_DIR/articulo_periodistico.sqlite"
DISCURSO_DB="$RUN_DIR/discurso_presidencial.sqlite"
MANIFEST="$RUN_DIR/manifest_preparacion.json"

command -v "$EMOPARSE_BIN" >/dev/null 2>&1 || {
    echo "ERROR: no encuentro '$EMOPARSE_BIN'. Activá .venv antes de ejecutar." >&2
    exit 1
}
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
    echo "ERROR: no encuentro '$PYTHON_BIN'. Activá .venv antes de ejecutar." >&2
    exit 1
}
[[ -f "$CONFIG" ]] || {
    echo "ERROR: config no encontrado: $CONFIG" >&2
    exit 1
}

mkdir -p "$SOURCE_DIR" "$RUN_DIR"

count_jsonl() {
    local path="$1"
    "$PYTHON_BIN" - "$path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.exists():
    print(0)
else:
    print(sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()))
PY
}

count_csv() {
    local path="$1"
    "$PYTHON_BIN" - "$path" <<'PY'
import csv
from pathlib import Path
import sys

path = Path(sys.argv[1])
if not path.exists():
    print(0)
else:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        print(sum(1 for _ in csv.DictReader(handle)))
PY
}

acquire_csv_corpus() {
    local source="$1"
    local output="$2"
    local mode="$3"
    local target="$4"
    local max_candidates="${5:-$target}"
    local current
    current="$(count_csv "$output")"
    if (( current >= target )); then
        echo "== $source: objetivo ya alcanzado ($current textos) =="
        return
    fi

    local candidate="$SOURCE_DIR/.${source}_candidate.csv"
    rm -f "$candidate"
    echo "== Adquiriendo candidatos de $source =="
    "$EMOPARSE_BIN" scrape \
        --source "$source" \
        --output "$candidate" \
        --max "$max_candidates" \
        --mode "$mode"
    "$PYTHON_BIN" scripts/merge_golden_v2_csv.py \
        --corpus "$output" \
        --candidate "$candidate" \
        --target "$target"
    rm -f "$candidate"
}

current_posts="$(count_jsonl "$TUIT_INPUT")"
remaining_posts=$((TARGET_POSTS - current_posts))
if (( remaining_posts > 0 )); then
    echo "== Adquiriendo $remaining_posts posts nuevos de Bluesky =="
    "$EMOPARSE_BIN" acquire \
        --source bluesky \
        --query "$TUIT_QUERY" \
        --lang es \
        --max "$remaining_posts" \
        --out "$TUIT_INPUT"
else
    echo "== Bluesky: objetivo ya alcanzado ($current_posts posts) =="
fi

acquire_csv_corpus \
    pagina12 "$ARTICULO_INPUT" http "$TARGET_ARTICLE_DOCUMENTS" "$PAGINA12_CANDIDATES"
acquire_csv_corpus \
    casarosada "$DISCURSO_INPUT" auto "$TARGET_SPEECH_DOCUMENTS" "$TARGET_SPEECH_DOCUMENTS"

posts_count="$(count_jsonl "$TUIT_INPUT")"
articles_count="$(count_csv "$ARTICULO_INPUT")"
speeches_count="$(count_csv "$DISCURSO_INPUT")"
if (( posts_count < TARGET_POSTS )); then
    echo "ERROR: Bluesky produjo $posts_count posts; se requieren $TARGET_POSTS." >&2
    exit 1
fi
if (( articles_count < TARGET_ARTICLE_DOCUMENTS )); then
    echo "ERROR: Página/12 produjo $articles_count textos; se requieren $TARGET_ARTICLE_DOCUMENTS." >&2
    exit 1
fi
if (( speeches_count < TARGET_SPEECH_DOCUMENTS )); then
    echo "ERROR: Casa Rosada produjo $speeches_count textos; se requieren $TARGET_SPEECH_DOCUMENTS." >&2
    exit 1
fi

prepare_run() {
    local genre="$1"
    local input="$2"
    local run_id="$3"
    local db="$4"
    local resume_args=()
    if [[ -f "$db" ]]; then
        resume_args=(--resume)
    fi

    "$EMOPARSE_BIN" run \
        --config "$CONFIG" \
        --input "$input" \
        --genre "$genre" \
        --run-id "$run_id" \
        --db "$db" \
        --prepare-only \
        "${resume_args[@]}"
}

prepare_run tuit "$TUIT_INPUT" golden_v2_tuit "$TUIT_DB"
prepare_run articulo_periodistico \
    "$ARTICULO_INPUT" \
    golden_v2_articulo_periodistico \
    "$ARTICULO_DB"
prepare_run discurso_presidencial \
    "$DISCURSO_INPUT" \
    golden_v2_discurso_presidencial \
    "$DISCURSO_DB"

"$PYTHON_BIN" scripts/validate_golden_v2_corpora.py \
    --tuit-db "$TUIT_DB" \
    --articulo-db "$ARTICULO_DB" \
    --discurso-db "$DISCURSO_DB" \
    --out "$MANIFEST"
