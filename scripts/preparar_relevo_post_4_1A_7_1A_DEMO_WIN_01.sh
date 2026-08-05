#!/usr/bin/env bash
set -euo pipefail

REPO="${1:-$HOME/projects/emoparse_v3.0/EmoParse}"
SERVICE="${2:-$HOME/projects/emoparse-service}"
OUT_PARENT="${3:-$HOME/Downloads}"
STAMP="$(date +%Y%m%d_%H%M%S)"
NAME="EmoParse_relevo_post_4_1A_7_1A_DEMO_WIN_01_${STAMP}"
OUT="$OUT_PARENT/$NAME"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

for cmd in git rsync zip sha256sum find sort cmp xargs; do
  command -v "$cmd" >/dev/null || { echo "ERROR: falta $cmd" >&2; exit 1; }
done
[[ -d "$REPO/.git" ]] || { echo "ERROR: repositorio inválido: $REPO" >&2; exit 1; }
[[ -f "$SERVICE/pyproject.toml" ]] || { echo "ERROR: servicio inválido: $SERVICE" >&2; exit 1; }

mkdir -p "$OUT"
STATUS_BEFORE="$(git -C "$REPO" status --porcelain=v1 -uall)"

REPO_STAGE="$TMP/EmoParse_repo_POST_4_1A_7_1A_DEMO_WIN_01_FILTRADO_${STAMP}"
mkdir -p "$REPO_STAGE"

while IFS= read -r -d '' rel; do
  case "$rel" in
    .git/*|.venv/*|.env|models/*|runs/*|exports/*|logs/*|.build/*|*/__pycache__/*|.mypy_cache/*|.pytest_cache/*|.ruff_cache/*) continue ;;
    data/casarosada.csv|data/golden_v2/*|docs/img/readme/*|_prueba/*|tutorial/screenshots/*) continue ;;
    docs/other/EMOPARSE_HACIA_LA_AUTOMATIZACION_DEL_ANALISIS_DE_EMOCIONES_DISCURSIVAS_CON_IA_GENERATIVA.pdf|docs/other/TESIS.pdf) continue ;;
    evals/golden/v2/*_pasada*.csv) continue ;;
    docs/assets/img/*.png|docs/assets/img/*/*.png|docs/assets/img/*/*/*.png|docs/assets/img/*/*/*/*.png) continue ;;
  esac
  src="$REPO/$rel"
  [[ -e "$src" ]] || continue
  mkdir -p "$REPO_STAGE/$(dirname "$rel")"
  cp -a "$src" "$REPO_STAGE/$rel"
done < <(git -C "$REPO" ls-files -z --cached --others --exclude-standard)

rm -rf "$REPO_STAGE/.dev" "$REPO_STAGE/.assistant"
cp -a "$REPO/.dev" "$REPO_STAGE/.dev"
cp -a "$REPO/.assistant" "$REPO_STAGE/.assistant"
find "$REPO_STAGE" -type d -name __pycache__ -prune -exec rm -rf {} +
find "$REPO_STAGE" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find "$REPO_STAGE/docs/assets/img" -type f -iname '*.png' -delete 2>/dev/null || true

hash_tree() {
  local root="$1"
  (cd "$root" && find . -type f -print0 | sort -z | xargs -0 sha256sum)
}
hash_tree "$REPO/.dev" > "$TMP/dev_source.sha256"
hash_tree "$REPO_STAGE/.dev" > "$TMP/dev_zip.sha256"
cmp "$TMP/dev_source.sha256" "$TMP/dev_zip.sha256"
hash_tree "$REPO/.assistant" > "$TMP/assistant_source.sha256"
hash_tree "$REPO_STAGE/.assistant" > "$TMP/assistant_zip.sha256"
cmp "$TMP/assistant_source.sha256" "$TMP/assistant_zip.sha256"

[[ ! -e "$REPO_STAGE/data/casarosada.csv" ]]
[[ ! -e "$REPO_STAGE/docs/img/readme" ]]
[[ ! -e "$REPO_STAGE/_prueba" ]]
[[ ! -e "$REPO_STAGE/tutorial/screenshots" ]]
[[ -z "$(find "$REPO_STAGE/docs/assets/img" -type f -iname '*.png' -print 2>/dev/null)" ]]
[[ ! -e "$REPO_STAGE/.env" && ! -e "$REPO_STAGE/.venv" && ! -e "$REPO_STAGE/runs" ]]

REPO_ZIP="$OUT/$(basename "$REPO_STAGE").zip"
(cd "$TMP" && zip -qr "$REPO_ZIP" "$(basename "$REPO_STAGE")")

SERVICE_STAGE="$TMP/emoparse-service_POST_4_1A_7_1A_DEMO_WIN_01_FILTRADO_${STAMP}"
rsync -a "$SERVICE/" "$SERVICE_STAGE/" \
  --exclude='.git/' --exclude='.venv/' --exclude='.secrets/' --exclude='data/' \
  --exclude='exports/' --exclude='.build/' --exclude='__pycache__/' \
  --exclude='.mypy_cache/' --exclude='.pytest_cache/' --exclude='.ruff_cache/' \
  --exclude='*.pyc' --exclude='*.pyo'
[[ ! -e "$SERVICE_STAGE/.secrets" && ! -e "$SERVICE_STAGE/data" ]]
SERVICE_ZIP="$OUT/$(basename "$SERVICE_STAGE").zip"
(cd "$TMP" && zip -qr "$SERVICE_ZIP" "$(basename "$SERVICE_STAGE")")

CTX="$TMP/EmoParse_contexto_post_4_1A_7_1A_DEMO_WIN_01_${STAMP}"
mkdir -p "$CTX/repo" "$CTX/service" "$CTX/golden_manifests"
CONT="$REPO/.dev/historico/relevos/CONTINUIDAD_NUEVA_CONVERSACION_POST_4_1A_7_1A_DEMO_WIN_01.md"
cp "$CONT" "$CTX/CONTINUIDAD_NUEVA_CONVERSACION_POST_4_1A_7_1A_DEMO_WIN_01.md"

git -C "$REPO" status --short --branch --untracked-files=all > "$CTX/repo/git-status.txt"
git -C "$REPO" diff --stat > "$CTX/repo/git-diff-stat.txt"
git -C "$REPO" diff --name-status > "$CTX/repo/git-diff-name-status.txt"
git -C "$REPO" log -n 12 --decorate --oneline > "$CTX/repo/git-log.txt"
git -C "$REPO" show --stat --oneline HEAD > "$CTX/repo/git-show-stat.txt"
git -C "$REPO" remote -v > "$CTX/repo/git-remote.txt"
cp "$REPO/config.yaml" "$REPO/CHANGELOG.md" "$CTX/repo/"
cp -a "$REPO/.assistant" "$CTX/repo/.assistant"
cp -a "$REPO/.dev/operativo" "$CTX/repo/operativo"
cp -a "$REPO/.dev/referencia" "$CTX/repo/referencia"
cp "$SERVICE/README.md" "$SERVICE/SERVICE_MANIFEST.json" "$CTX/service/"

VERSION="$(grep -E '^__version__[[:space:]]*=' "$REPO/src/emoparse/version.py" | head -n 1 | sed -E 's/.*["'"'"']([^"'"'"']+)["'"'"'].*/\1/')"
{
  echo "EmoParse version: $VERSION"
  echo 'knowledge=v19'
  echo 'prompt=v54'
  echo 'ontology=v27'
  echo 'schema=v41'
  echo "HEAD=$(git -C "$REPO" rev-parse HEAD)"
} > "$CTX/repo/versiones.txt"

for f in \
  "$REPO/runs/golden_v2/manifest_preparacion.json" \
  "$REPO/.build/golden_v2/muestras_pasada1.sha256" \
  "$REPO/data/golden_v2/context/manifest.json" \
  "$REPO/data/golden_v2/context/articulo_context_manifest.json" \
  "$REPO/data/golden_v2/context/discurso_context_manifest.json"; do
  [[ -f "$f" ]] && cp "$f" "$CTX/golden_manifests/"
done

{
  for f in \
    "$REPO/runs/golden_v2/tuit.sqlite" \
    "$REPO/runs/golden_v2/articulo_periodistico.sqlite" \
    "$REPO/runs/golden_v2/discurso_presidencial.sqlite" \
    "$REPO/evals/golden/v2/tuit_pasada1.csv" \
    "$REPO/evals/golden/v2/articulo_periodistico_pasada1.csv" \
    "$REPO/evals/golden/v2/discurso_presidencial_pasada1.csv" \
    "$REPO/data/golden_v2/context/tuit_annotation_context.jsonl" \
    "$REPO/data/golden_v2/context/articulo_annotation_context.jsonl" \
    "$REPO/data/golden_v2/context/discurso_annotation_context.jsonl" \
    "$SERVICE/data/annotations.sqlite"; do
      [[ -f "$f" ]] && sha256sum "$f"
  done
} > "$CTX/local-artifacts-sha256.txt"

if [[ -x "$SERVICE/.venv/bin/emoparse-annotate" && -f "$SERVICE/data/annotations.sqlite" ]]; then
  "$SERVICE/.venv/bin/emoparse-annotate" --db "$SERVICE/data/annotations.sqlite" status \
    > "$CTX/service/campaign-status.txt"
fi
find "$REPO/.build/golden_v2" -maxdepth 1 -type f -printf '%f\n' 2>/dev/null | sort \
  > "$CTX/golden_manifests/log-inventory.txt" || true

CTX_ZIP="$OUT/$(basename "$CTX").zip"
(cd "$TMP" && zip -qr "$CTX_ZIP" "$(basename "$CTX")")
cp "$CONT" "$OUT/CONTINUIDAD_NUEVA_CONVERSACION_POST_4_1A_7_1A_DEMO_WIN_01.md"
cp "$REPO/.dev/referencia/EMPAQUETADO_RELEVOS.md" "$OUT/REGLAS_ZIP_CONVERSACIONES.md"

{
  echo "Repositorio ZIP: $(basename "$REPO_ZIP")"
  echo "Servicio ZIP: $(basename "$SERVICE_ZIP")"
  echo "Contexto ZIP: $(basename "$CTX_ZIP")"
  echo "Archivos .dev verificados: $(find "$REPO/.dev" -type f | wc -l)"
  echo "Archivos .assistant verificados: $(find "$REPO/.assistant" -type f | wc -l)"
  echo "No se incluyeron bases, tokens, .env, corpus crudos ni rutas excluidas."
  echo "El repositorio original no fue modificado por el proceso."
} > "$OUT/MANIFIESTO_ZIP_REPOSITORIO.txt"

STATUS_AFTER="$(git -C "$REPO" status --porcelain=v1 -uall)"
[[ "$STATUS_BEFORE" == "$STATUS_AFTER" ]] || {
  echo 'ERROR: cambió el working tree durante el empaquetado.' >&2
  exit 1
}

(
  cd "$OUT"
  sha256sum \
    "$(basename "$REPO_ZIP")" \
    "$(basename "$SERVICE_ZIP")" \
    "$(basename "$CTX_ZIP")" \
    CONTINUIDAD_NUEVA_CONVERSACION_POST_4_1A_7_1A_DEMO_WIN_01.md \
    REGLAS_ZIP_CONVERSACIONES.md \
    MANIFIESTO_ZIP_REPOSITORIO.txt > SHA256SUMS.txt
)

printf 'Relevo preparado en: %s\n' "$OUT"
printf 'Adjuntar en la nueva conversación:\n'
printf '  %s\n' "$OUT/CONTINUIDAD_NUEVA_CONVERSACION_POST_4_1A_7_1A_DEMO_WIN_01.md"
printf '  %s\n' "$REPO_ZIP" "$SERVICE_ZIP" "$CTX_ZIP" "$OUT/SHA256SUMS.txt"
