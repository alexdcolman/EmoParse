#!/usr/bin/env python3
"""
eval_against_gold.py — Evalúa las emociones detectadas por EmoParse contra un gold.

QUÉ HACE
  Compara, frase por frase, lo que detectó un run (columna emociones_payload /
  emociones_pass2_payload de frases.csv) contra lo anotado a mano en el gold,
  y reporta cuatro métricas INDEPENDIENTES (no un único score opaco):
    1) DETECCIÓN      presencia de emoción por frase: precisión / recall / F1.
    2) TIPO           recall y precisión de los tipos, donde ambos detectan.
    3) EXPERIENCIADOR acuerdo laxo sobre quién siente.
    4) ARRASTRE       % de emociones del modelo justificadas por el contexto
                      previo (síntoma del bug de pass2).
  Además escribe un diff fila-a-fila (TP/FP/FN/TN) para inspección manual.

FORMATO DEL GOLD (CSV)
  Columnas: unit_idx, frase, claude_opus_4_8, [correccion_experto], ...
  Para cada frase usa `correccion_experto` si está completa; si no,
  `claude_opus_4_8`. Celda de emociones: una o varias separadas por
  '|' (también acepta ';' o salto de línea). Cada emoción se escribe:
        tipo (experienciador) [tag]
    · tipo            la emoción; todo lo anterior al primer '('. Alternativas
                      con '/': "satisfaccion/ironia" matchea cualquiera.
    · (experienciador) primer paréntesis; QUIÉN siente la emoción.
    · [tag]           y un "(conf-baja)" extra se ignoran en el match
                      (son nota humana; conf-baja además actúa como peso).
  Sin emoción en la frase → escribir 'NINGUNA' sola en la celda.

PARÁMETROS
  base                  carpeta del run con frases.csv (p. ej. exports/q2/)
  gold                  CSV del gold (p. ej. evaluation/gold/gold.csv)
  --pass {pass1,pass2}  qué columna del modelo evaluar (default: pass2)
  --equivalences FILE   JSON de clusters de equivalencias; canoniza gold y
                        modelo antes de comparar el tipo. Sin esto: match
                        exacto por lema.
  --exclude-low-conf    ignora las emociones del gold marcadas "(conf-baja)";
                        las frases que SOLO tenían conf-baja salen del scoring
                        (no cuentan como acierto ni error).
  --out FILE            CSV con el diff fila-a-fila (default: eval_diff.csv).

CÓMO CORRER (desde la raíz del proyecto; gold y JSON en evaluation/gold/)
  # 1) Base de cada pase, match exacto — para el A/B pass1 vs pass2:
  python evaluation/scripts/eval_against_gold.py exports/*/ \
         evaluation/gold/gold.csv --pass pass1 --out evaluation/diff_pass1.csv
  python evaluation/scripts/eval_against_gold.py exports/*/ \
         evaluation/gold/gold.csv --pass pass2 --out evaluation/diff_pass2.csv

  # 2) Vista principal: con equivalencias (los sinónimos cuentan igual):
  python evaluation/scripts/eval_against_gold.py exports/*/ \
         evaluation/gold/gold.csv --pass pass2 \
         --equivalences evaluation/gold/equivalencias.json \
         --out evaluation/diff_pass2_eq.csv

  # 3) Vista estricta: solo emociones de alta confianza:
  python evaluation/scripts/eval_against_gold.py exports/*/ \
         evaluation/gold/gold.csv --pass pass2 \
         --equivalences evaluation/gold/equivalencias.json --exclude-low-conf

  (base es UN directorio de run, el que contiene frases.csv; si exports/*/
  expande a varios, pasá el que querés evaluar, p. ej. exports/q2/.)
  Mirá en el diff los FP -> sobre-detección, y los FN -> lo que se pierde.
"""
from __future__ import annotations
import csv, json, os, re, argparse, unicodedata
from collections import defaultdict


def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")

def norm(s):
    return re.sub(r"\s+", " ", strip_accents((s or "").strip().lower()))

def lemma(s):
    s = norm(s)
    for suf in ("cion", "miento", "encia", "ancia", "idad", "eza", "ura",
                "os", "as", "es", "a", "o", "e"):
        if len(s) > 5 and s.endswith(suf):
            return s[:-len(suf)]
    return s

CANON_LOOKUP: dict[str, str] = {}


def load_equivalences(path):
    """Carga clusters de equivalencias y arma lookup norm(termino)->canonico.

    Formato: {"clusters": {"<canonico>": ["term1", "term2", ...], ...}}.
    Si un termino aparece en mas de un cluster, se avisa y gana el primero.
    """
    import json as _json
    data = _json.load(open(path, encoding="utf-8"))
    clusters = data.get("clusters", {})
    seen = {}
    for canonico, terms in clusters.items():
        c = norm(canonico)
        for t in [canonico, *terms]:
            tn = norm(t)
            if tn in seen and seen[tn] != c:
                print(f"  [aviso] equivalencias: '{tn}' en >1 cluster "
                      f"({seen[tn]} y {c}); queda en {seen[tn]}.")
                continue
            seen.setdefault(tn, c)
    CANON_LOOKUP.update(seen)
    return len(clusters)


def canon(label):
    """Canoniza una etiqueta: cluster si esta en equivalencias, si no su lema."""
    n = norm(label)
    return CANON_LOOKUP.get(n) or lemma(label)


def parse_json(s):
    s = (s or "").strip()
    if not s or s in ("[]", "null", "None"):
        return []
    try:
        return json.loads(s)
    except Exception:
        return []

_PAREN = re.compile(r"\(([^)]*)\)")
#: Paréntesis que son tags (confianza/modo), no experienciadores.
_TAG_PAREN = re.compile(r"^(conf[\s_-]|infer|expl|potencial|hipotetic|virtual)", re.I)


def _experienciador(raw):
    """Primer paréntesis cuyo contenido NO sea un tag (conf-*, infer, expl...)."""
    for m in _PAREN.finditer(raw):
        content = m.group(1).strip()
        if _TAG_PAREN.match(strip_accents(content.lower())):
            continue
        return content
    return ""

def parse_gold_cell(cell, exclude_low_conf=False):
    """Devuelve lista de (set_de_canonicos_tipo, experienciador)."""
    cell = (cell or "").strip()
    if not cell or norm(cell).startswith("ninguna"):
        return []
    out = []
    for raw in re.split(r"[;|\n]+", cell):
        raw = raw.strip()
        if not raw:
            continue
        if exclude_low_conf and "conf-baja" in raw.lower():
            continue
        exp = _experienciador(raw)
        tipo_part = raw.split("(")[0]
        tipo_part = re.sub(r"\[.*?\]", "", tipo_part).strip()
        cset = {canon(t) for t in re.split(r"[/]", tipo_part) if t.strip()}
        cset = {c for c in cset if c}
        if cset:
            out.append((cset, exp))
    return out

CARRY = re.compile(r"contexto anterior|frase anterior|mantiene|persiste|"
                   r"se mantiene|menciona que|del contexto|previo|reforzad",
                   re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="carpeta del export (con frases.csv)")
    ap.add_argument("gold", help="gold borrador o corregido (CSV)")
    ap.add_argument("--pass", dest="which", default="pass2",
                    choices=["pass1", "pass2"])
    ap.add_argument("--equivalences", default=None,
                    help="JSON de clusters de equivalencias (opcional)")
    ap.add_argument("--exclude-low-conf", dest="excl", action="store_true",
                    help="ignora emociones del gold marcadas (conf-baja)")
    ap.add_argument("--out", default="eval_diff.csv")
    args = ap.parse_args()

    n_clusters = load_equivalences(args.equivalences) if args.equivalences else 0

    col = "emociones_payload" if args.which == "pass1" else "emociones_pass2_payload"
    with open(os.path.join(args.base, "frases.csv"), encoding="utf-8-sig") as fh:
        frases = {r["unit_idx"]: r for r in csv.DictReader(fh)}

    with open(args.gold, encoding="utf-8-sig") as fh:
        gold_rows = list(csv.DictReader(fh))

    tp = fp = fn = tn = 0
    g_match = g_total = m_match = m_total = 0
    exp_ok = exp_tot = 0
    carry_n = carry_d = 0
    diffs = []

    for g in gold_rows:
        idx = g["unit_idx"]
        cell = (g.get("correccion_experto") or "").strip() or g.get("claude_opus_4_8", "")
        gold = parse_gold_cell(cell, exclude_low_conf=args.excl)
        if args.excl and not gold and parse_gold_cell(cell, exclude_low_conf=False):
            continue

        fr = frases.get(idx, {})
        model_em = parse_json(fr.get(col)) or parse_json(fr.get("emociones_payload"))
        model = [(canon(e.get("tipo_emocion", "")), norm(e.get("experienciador", "")))
                 for e in model_em if e.get("tipo_emocion")]
        for e in model_em:
            carry_d += 1
            if CARRY.search(e.get("justificacion", "") or ""):
                carry_n += 1

        gold_has, model_has = bool(gold), bool(model)
        if gold_has and model_has: tp += 1
        elif gold_has: fn += 1
        elif model_has: fp += 1
        else: tn += 1

        if gold_has and model_has:
            model_lemmas = {ml for ml, _ in model}
            gold_universe = set().union(*[s for s, _ in gold])
            for lemas, exp in gold:
                g_total += 1
                if lemas & model_lemmas:
                    g_match += 1
                    if exp:
                        exp_tot += 1
                        me = " ".join(m_exp for _, m_exp in model)
                        toks = [t for t in re.split(r"\W+", norm(exp)) if len(t) > 3]
                        if any(t in me for t in toks):
                            exp_ok += 1
            for ml, _ in model:
                m_total += 1
                if ml in gold_universe:
                    m_match += 1

        status = ("TP" if gold_has and model_has else
                  "FN (modelo se perdio)" if gold_has else
                  "FP (modelo de mas)" if model_has else "TN")
        diffs.append({
            "unit_idx": idx, "status": status,
            "modelo_n": len(model), "gold": cell,
            "modelo": ";".join(sorted({ml for ml, _ in model})),
            "frase": (fr.get("frase", "") or "")[:80],
        })

    prec = tp / (tp + fp) if (tp + fp) else 0
    rec = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0

    print("\n" + "=" * 62)
    print(f"  EVAL vs GOLD  ({args.which})   frases={len(gold_rows)}")
    print(f"  equivalencias: {('%d clusters' % n_clusters) if n_clusters else 'NO (match exacto por lema)'}"
          f"   |   exclude-low-conf: {'si' if args.excl else 'no'}")
    print("=" * 62)
    print("  1) DETECCION (presencia por frase)")
    print(f"       TP={tp} FP={fp} FN={fn} TN={tn}")
    print(f"       precision={prec:.2f}  recall={rec:.2f}  F1={f1:.2f}")
    print("  2) TIPO (en frases donde ambos detectan)")
    if g_total:
        print(f"       recall de tipos    = {g_match}/{g_total} = {g_match/g_total:.2f}")
    if m_total:
        print(f"       precision de tipos = {m_match}/{m_total} = {m_match/m_total:.2f}")
    if exp_tot:
        print("  3) EXPERIENCIADOR (sobre tipos acertados con exp anotado)")
        print(f"       acuerdo = {exp_ok}/{exp_tot} = {exp_ok/exp_tot:.2f}")
    if carry_d:
        print("  4) ARRASTRE (sintoma del bug de pass2)")
        print(f"       emociones del modelo con justif. de contexto previo: "
              f"{carry_n}/{carry_d} = {carry_n/carry_d:.0%}")
    print("=" * 62)

    with open(args.out, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["unit_idx", "status", "modelo_n",
                                           "gold", "modelo", "frase"])
        w.writeheader()
        for d in sorted(diffs, key=lambda x: (x["status"], int(x["unit_idx"]))):
            w.writerow(d)
    print(f"  Diff fila-a-fila -> {args.out}")
    print("  (mira los FP -- ahi esta la sobre-deteccion -- y los FN)\n")


if __name__ == "__main__":
    main()
