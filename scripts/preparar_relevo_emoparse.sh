#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-$HOME/projects/emoparse_v3.0/EmoParse}"
OUT_PARENT="${2:-$HOME/Downloads/emoparse}"
LABEL_RAW="${3:-relevo}"
CONTINUIDAD="${4:-}"
STAMP="$(date +%Y%m%d_%H%M%S)"
LABEL="$(printf '%s' "$LABEL_RAW" | tr -cs '[:alnum:]_.-' '_' | sed 's/^_*//; s/_*$//')"
[[ -n "$LABEL" ]] || LABEL="relevo"
OUT="$OUT_PARENT/EmoParse_${LABEL}_${STAMP}"
TMP="$(mktemp -d)"
trap 'rm -rf -- "$TMP"' EXIT

for cmd in git zip unzip sha256sum find sort cmp xargs python3; do
  command -v "$cmd" >/dev/null || {
    echo "ERROR: falta el comando requerido: $cmd" >&2
    exit 1
  }
done

[[ -d "$REPO/.git" ]] || {
  echo "ERROR: no es un repositorio Git: $REPO" >&2
  exit 1
}
[[ -f "$REPO/.dev/referencia/EMPAQUETADO_RELEVOS.md" ]] || {
  echo "ERROR: falta .dev/referencia/EMPAQUETADO_RELEVOS.md" >&2
  exit 1
}
[[ -d "$REPO/.dev" && -d "$REPO/.assistant" ]] || {
  echo "ERROR: faltan .dev/ o .assistant/" >&2
  exit 1
}
if [[ -n "$CONTINUIDAD" && ! -f "$CONTINUIDAD" ]]; then
  echo "ERROR: no existe el documento de continuidad: $CONTINUIDAD" >&2
  exit 1
fi

mkdir -p -- "$OUT_PARENT"
[[ ! -e "$OUT" ]] || {
  echo "ERROR: el destino ya existe: $OUT" >&2
  exit 1
}
mkdir -- "$OUT"

git -C "$REPO" status --porcelain=v1 -uall > "$TMP/status_before.txt"

REPO_STAGE="$TMP/EmoParse"
mkdir -p -- "$REPO_STAGE"

is_excluded() {
  local rel="$1"
  case "$rel" in
    .dev/*|.assistant/*) return 0 ;;
    .git/*|.github/*|.build/*) return 0 ;;
    .venv/*|venv/*|env/*|*/.venv/*|*/venv/*|*/env/*) return 0 ;;
    .cache/*|*/.cache/*|.mypy_cache/*|*/.mypy_cache/*|.pytest_cache/*|*/.pytest_cache/*|.ruff_cache/*|*/.ruff_cache/*|__pycache__/*|*/__pycache__/*) return 0 ;;
    .env.example) return 1 ;;
    .env|.env.*|*/.env|*/.env.*|.secrets/*|*/.secrets/*|.streamlit/secrets.toml|*/.streamlit/secrets.toml|.pypirc|*/.pypirc) return 0 ;;
    models/*|*/models/*|*.gguf|*.safetensors|*.ckpt|*.pt|*.pth) return 0 ;;
    runs/*|*/runs/*|exports/*|*/exports/*|logs/*|*/logs/*|*.log) return 0 ;;
    *.sqlite|*.sqlite-*|*.sqlite3|*.sqlite3-*|*.db|*.db-*|*.db-journal) return 0 ;;
    data/ejemplos/*) return 1 ;;
    data/*) return 0 ;;
    docs/img/readme/*|docs/assets/img/*.png|docs/assets/img/*/*.png|docs/assets/img/*/*/*.png|docs/assets/img/*/*/*/*.png) return 0 ;;
    _prueba/*|tutorial/screenshots/*) return 0 ;;
    docs/other/EMOPARSE_HACIA_LA_AUTOMATIZACION_DEL_ANALISIS_DE_EMOCIONES_DISCURSIVAS_CON_IA_GENERATIVA.pdf|docs/other/TESIS.pdf) return 0 ;;
    evals/golden/v2/*_pasada*.csv) return 0 ;;
    *.pyc|*.pyo|*.pem|*.key|id_rsa|id_rsa.*|id_ed25519|id_ed25519.*|credentials*.json|*/credentials*.json|service-account*.json|*/service-account*.json) return 0 ;;
  esac
  return 1
}

while IFS= read -r -d '' rel; do
  is_excluded "$rel" && continue
  src="$REPO/$rel"
  [[ -e "$src" ]] || continue
  mkdir -p -- "$REPO_STAGE/$(dirname "$rel")"
  cp -a -- "$src" "$REPO_STAGE/$rel"
done < <(git -C "$REPO" ls-files -z --cached --others --exclude-standard)

# Las instrucciones internas se copian completas desde el árbol local, fuera del filtro de Git.
cp -a -- "$REPO/.dev" "$REPO_STAGE/.dev"
cp -a -- "$REPO/.assistant" "$REPO_STAGE/.assistant"

hash_tree() {
  local root="$1"
  (
    cd "$root"
    find . -type f -print0 | sort -z | xargs -0 -r sha256sum
  )
}

hash_tree "$REPO/.dev" > "$TMP/dev_source.sha256"
hash_tree "$REPO_STAGE/.dev" > "$TMP/dev_stage.sha256"
cmp "$TMP/dev_source.sha256" "$TMP/dev_stage.sha256"
hash_tree "$REPO/.assistant" > "$TMP/assistant_source.sha256"
hash_tree "$REPO_STAGE/.assistant" > "$TMP/assistant_stage.sha256"
cmp "$TMP/assistant_source.sha256" "$TMP/assistant_stage.sha256"

python3 - "$REPO_STAGE" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
forbidden_parts = {
    ".git",
    ".github",
    ".build",
    ".venv",
    "venv",
    "env",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "models",
    "runs",
    "exports",
    "logs",
    ".secrets",
}
forbidden_suffixes = {
    ".pyc",
    ".pyo",
    ".gguf",
    ".safetensors",
    ".ckpt",
    ".pt",
    ".pth",
    ".sqlite",
    ".sqlite3",
    ".db",
    ".log",
    ".pem",
    ".key",
}
private_key = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
secret_patterns = [
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
]

for path in root.rglob("*"):
    rel = path.relative_to(root)
    parts = rel.parts
    if any(part in forbidden_parts for part in parts):
        raise SystemExit(f"ruta excluida presente: {rel}")
    if path.is_dir():
        continue
    name = path.name.lower()
    if path.suffix.lower() in forbidden_suffixes:
        raise SystemExit(f"archivo excluido presente: {rel}")
    if (
        name.startswith(".env") and name != ".env.example"
        or name in {".pypirc", "secrets.toml", "id_rsa", "id_ed25519"}
        or "credentials" in name
        or "service-account" in name
    ):
        raise SystemExit(f"credencial potencial presente: {rel}")
    if parts[:1] == ("data",) and (len(parts) < 2 or parts[1] != "ejemplos"):
        raise SystemExit(f"dato o corpus local presente: {rel}")
    if len(parts) >= 3 and parts[:3] == ("docs", "assets", "img") and path.suffix.lower() == ".png":
        raise SystemExit(f"PNG excluido presente: {rel}")
    if rel.as_posix() in {
        "docs/other/EMOPARSE_HACIA_LA_AUTOMATIZACION_DEL_ANALISIS_DE_EMOCIONES_DISCURSIVAS_CON_IA_GENERATIVA.pdf",
        "docs/other/TESIS.pdf",
    }:
        raise SystemExit(f"documento excluido presente: {rel}")
    try:
        data = path.read_bytes()
    except OSError:
        continue
    if private_key.search(data):
        raise SystemExit(f"clave privada detectada: {rel}")
    if any(pattern.search(data) for pattern in secret_patterns):
        raise SystemExit(f"token potencial detectado: {rel}")
PY

find "$REPO_STAGE" -type f -printf '%P\n' | LC_ALL=C sort > "$TMP/MANIFIESTO_REPOSITORIO.txt"
REPO_ZIP="$OUT/EmoParse_REPO_${LABEL}_${STAMP}.zip"
(
  cd "$TMP"
  zip -qr "$REPO_ZIP" EmoParse
)
unzip -tq "$REPO_ZIP" >/dev/null
python3 - "$REPO_ZIP" <<'PY'
from pathlib import PurePosixPath
from zipfile import ZipFile
import sys
with ZipFile(sys.argv[1]) as zf:
    for name in zf.namelist():
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts:
            raise SystemExit(f"ruta insegura en ZIP: {name}")
PY

CTX_STAGE="$TMP/EmoParse_contexto"
mkdir -p -- "$CTX_STAGE"
cp -a -- "$REPO/.dev" "$CTX_STAGE/.dev"
cp -a -- "$REPO/.assistant" "$CTX_STAGE/.assistant"
cp -- "$TMP/MANIFIESTO_REPOSITORIO.txt" "$CTX_STAGE/MANIFIESTO_REPOSITORIO.txt"
git -C "$REPO" rev-parse HEAD > "$CTX_STAGE/GIT_HEAD.txt"
git -C "$REPO" rev-parse --verify origin/main > "$CTX_STAGE/GIT_ORIGIN_MAIN.txt" 2>/dev/null || :
git -C "$REPO" status --short --branch --untracked-files=all > "$CTX_STAGE/GIT_STATUS.txt"
git -C "$REPO" diff --stat -- . \
  ':(exclude).github/**' ':(exclude).build/**' ':(exclude)data/**' \
  ':(exclude)runs/**' ':(exclude)exports/**' ':(exclude)logs/**' \
  > "$CTX_STAGE/WORKING_TREE_STAT.txt"
git -C "$REPO" diff --name-status -- . \
  ':(exclude).github/**' ':(exclude).build/**' ':(exclude)data/**' \
  ':(exclude)runs/**' ':(exclude)exports/**' ':(exclude)logs/**' \
  > "$CTX_STAGE/WORKING_TREE_FILES.txt"
[[ -f "$REPO/CHANGELOG.md" ]] && cp -- "$REPO/CHANGELOG.md" "$CTX_STAGE/CHANGELOG.md"
[[ -f "$REPO/config.yaml" ]] && cp -- "$REPO/config.yaml" "$CTX_STAGE/config.yaml"
[[ -n "$CONTINUIDAD" ]] && cp -- "$CONTINUIDAD" "$CTX_STAGE/$(basename "$CONTINUIDAD")"

python3 - "$CTX_STAGE" <<'PY'
from pathlib import Path
import re
import sys
root = Path(sys.argv[1])
private_key = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")
secret_patterns = [
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,255}"),
    re.compile(rb"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{20,}"),
]
for path in root.rglob("*"):
    if not path.is_file():
        continue
    lower = path.name.lower()
    if lower.startswith(".env") and lower != ".env.example":
        raise SystemExit(f"credencial en contexto: {path.relative_to(root)}")
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".gguf", ".safetensors", ".log"}:
        raise SystemExit(f"artefacto local en contexto: {path.relative_to(root)}")
    data = path.read_bytes()
    if private_key.search(data):
        raise SystemExit(f"clave privada en contexto: {path.relative_to(root)}")
    if any(pattern.search(data) for pattern in secret_patterns):
        raise SystemExit(f"token potencial en contexto: {path.relative_to(root)}")
PY

CTX_ZIP="$OUT/EmoParse_CONTEXTO_${LABEL}_${STAMP}.zip"
(
  cd "$TMP"
  zip -qr "$CTX_ZIP" EmoParse_contexto
)
unzip -tq "$CTX_ZIP" >/dev/null
python3 - "$CTX_ZIP" <<'PY'
from pathlib import PurePosixPath
from zipfile import ZipFile
import sys
with ZipFile(sys.argv[1]) as zf:
    for name in zf.namelist():
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts:
            raise SystemExit(f"ruta insegura en ZIP: {name}")
PY

git -C "$REPO" status --porcelain=v1 -uall > "$TMP/status_after.txt"
cmp "$TMP/status_before.txt" "$TMP/status_after.txt"

cat > "$OUT/MANIFIESTO.txt" <<EOF_MANIFEST
Repositorio: $REPO
ZIP de repositorio: $(basename "$REPO_ZIP")
ZIP de contexto: $(basename "$CTX_ZIP")
.dev verificado: $(find "$REPO/.dev" -type f | wc -l) archivos
.assistant verificado: $(find "$REPO/.assistant" -type f | wc -l) archivos
Exclusiones, secretos, integridad y rutas internas: OK
Working tree original sin cambios: OK
EOF_MANIFEST

(
  cd "$OUT"
  sha256sum "$(basename "$REPO_ZIP")" "$(basename "$CTX_ZIP")" MANIFIESTO.txt > SHA256SUMS.txt
)

printf 'Relevo preparado en: %s\n' "$OUT"
printf 'Archivos:\n  %s\n  %s\n  %s\n' "$REPO_ZIP" "$CTX_ZIP" "$OUT/SHA256SUMS.txt"
