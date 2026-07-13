#!/usr/bin/env python3
"""
audit.py — Auditoría heurística de una exportación de EmoParse.

Corre sobre los tres CSV que produce `emoparse export` (discursos.csv,
frases.csv, emociones.csv) y reporta, de forma repetible, los problemas
estructurales y de coherencia que un ojo experto detectaría a mano.
Pensado para correrlo después de cada cambio de prompt/heurística/modelo
y ver moverse los números.

Uso desde la raíz del proyecto:
    python evaluation/scripts/audit.py exports/mi_run/

Salida: reporte por consola + audit_report.json con todas las métricas
(para diffear entre runs o graficar la evolución).
"""
from __future__ import annotations
import csv, json, sys, os, re
from collections import Counter, defaultdict

# ───────────────────────── Helpers ─────────────────────────

def read_csv(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))

def parse_json(s):
    s = (s or "").strip()
    if not s or s in ("[]", "null", "None"):
        return []
    try:
        return json.loads(s)
    except Exception:
        return "ERR"

def is_true(v):
    return str(v).strip().lower() in ("true", "1", "yes")

def pct(n, d):
    return 0.0 if not d else round(100.0 * n / d, 1)

# Conceptos abstractos típicos que no son actores/experienciadores
# Ir agregando según se vean en las exportaciones, si se utilizan
# distintos discursos o géneros.
ABSTRACT_HINTS = re.compile(
    r"\b(justicia social|teor[ií]a|propiedad privada|mercado|mercados|"
    r"competencia|divisi[oó]n del trabajo|cooperaci[oó]n|libertad|"
    r"regulaci[oó]n|inflaci[oó]n|socialismo|capitalismo|estatismo|"
    r"econom[ií]a|ideolog[ií]a|concepto|sistema|modelo)\b",
    re.IGNORECASE,
)
BARE_TOKEN = re.compile(r"^(el|la|los|las|lo|yo|t[uú]|[eé]l|ella|ellos|ellas|"
                        r"nosotros|ustedes|esto|eso|aquello)$", re.IGNORECASE)

FINDINGS = []  # (severidad, area, mensaje)

def add(sev, area, msg):
    FINDINGS.append((sev, area, msg))

# ───────────────────────── Checks ─────────────────────────

def audit_discursos(rows, report):
    if not rows:
        add("WARN", "discursos", "No se encontró discursos.csv")
        return
    r0 = rows[0]
    cols = set(r0.keys())
    # think-leak (Qwen3 y similares dejan <think>...</think>)
    leak_fields = [c for c in cols
                   if c.startswith("summarizer__") and "<think>" in (r0.get(c) or "")]
    report["summarizer_think_leak"] = leak_fields
    if leak_fields:
        add("ALTO", "summarizer",
            f"Razonamiento <think> filtrado en {leak_fields}. "
            "El bloque de cadena-de-pensamiento quedó dentro del resumen.")
    # codigo vacío
    empty_cod = sum(1 for r in rows if not (r.get("codigo") or "").strip())
    report["discursos_codigo_vacio"] = empty_cod
    if empty_cod:
        add("ALTO", "input/export",
            f"{empty_cod}/{len(rows)} discursos con `codigo` vacío "
            "(rompe trazabilidad y join entre tablas).")
    # titulo placeholder
    sin_tit = sum(1 for r in rows
                  if (r.get("titulo") or "").strip().lower() in ("", "sin título", "sin titulo"))
    report["discursos_sin_titulo"] = sin_tit
    if sin_tit:
        add("MEDIO", "input/scraper",
            f"{sin_tit}/{len(rows)} discursos sin título real ('Sin título').")
    # ciudad contaminada con país
    if "metadata__ciudad" in cols:
        dirty = [r.get("metadata__ciudad") for r in rows
                 if "," in (r.get("metadata__ciudad") or "")]
        report["ciudad_con_coma"] = dirty
        if dirty:
            add("BAJO", "metadata",
                f"Campo ciudad con país embebido: {dirty[:3]} "
                "(debería ser solo ciudad; país va en su campo).")

def audit_export_integrity(frases, emociones, report):
    if frases is not None and "codigo" not in (frases[0] if frases else {}):
        add("ALTO", "export",
            "frases.csv no incluye columna `codigo`: con >1 discurso no se "
            "puede joinear frase→discurso.")
        report["frases_sin_codigo"] = True
    if emociones is not None and "codigo" not in (emociones[0] if emociones else {}):
        add("ALTO", "export",
            "emociones.csv no incluye columna `codigo` (ni frase_idx único "
            "global): con >1 discurso el join es ambiguo.")
        report["emociones_sin_codigo"] = True

def audit_passes(frases, emociones, report):
    if not frases:
        return
    has_p2 = any(parse_json(r.get("emociones_pass2_payload")) for r in frases)
    p1_frases = sum(1 for r in frases if parse_json(r.get("emociones_payload")) not in ([], "ERR"))
    p2_frases = sum(1 for r in frases if parse_json(r.get("emociones_pass2_payload")) not in ([], "ERR"))
    p1_total = sum(len(parse_json(r.get("emociones_payload")))
                   for r in frases if parse_json(r.get("emociones_payload")) not in ([], "ERR"))
    p2_total = sum(len(parse_json(r.get("emociones_pass2_payload")))
                   for r in frases if parse_json(r.get("emociones_pass2_payload")) not in ([], "ERR"))
    report.update(dict(frases_total=len(frases),
                       pass1_frases_con_emocion=p1_frases, pass1_emociones=p1_total,
                       pass2_frases_con_emocion=p2_frases, pass2_emociones=p2_total))
    # ¿emociones.csv refleja pass1 o pass2?
    if emociones:
        n_exp = len(emociones)
        origen = "pass1" if abs(n_exp - p1_total) <= abs(n_exp - p2_total) else "pass2"
        report["emociones_export_origen_probable"] = origen
        if has_p2 and origen == "pass1" and p2_total != p1_total:
            add("ALTO", "pipeline/wiring",
                f"Corriste pass2 (detecta en {p2_frases} frases / {p2_total} emociones) "
                f"pero emociones.csv parece venir de pass1 ({p1_total}). "
                "El pass2 quedó huérfano: explode/characterizer no lo consumen.")
    # recall proxy
    rate = pct(p1_frases, len(frases))
    report["pass1_recall_proxy_pct"] = rate
    if rate < 25:
        add("MEDIO", "emotions",
            f"Solo {rate}% de las frases tienen emoción en pass1 "
            f"({p1_frases}/{len(frases)}). Recall posiblemente bajo para el género.")

def audit_actores(frases, report):
    if not frases:
        return
    abstract_actors = Counter()
    bare_actors = Counter()
    total_actors = 0
    name_variants = defaultdict(set)
    for r in frases:
        a = parse_json(r.get("actores_payload"))
        if a == "ERR":
            continue
        for x in a:
            name = (x.get("actor") or "").strip()
            total_actors += 1
            if BARE_TOKEN.match(name):
                bare_actors[name] += 1
            elif ABSTRACT_HINTS.search(name):
                abstract_actors[name] += 1
            key = re.sub(r"^(el|la|los|las)\s+", "", name.lower()).strip()
            name_variants[key].add(name)
    report["actores_total"] = total_actors
    report["actores_abstractos"] = dict(abstract_actors)
    report["actores_pronombre_desnudo"] = dict(bare_actors)
    if bare_actors:
        add("MEDIO", "actors/normalize",
            f"Actores que son solo pronombre/artículo sin resolver: "
            f"{dict(bare_actors)} → normalize_actors no corrió o no resolvió correferencias.")
    if abstract_actors:
        add("MEDIO", "actors",
            f"Conceptos abstractos detectados como actores (posible "
            f"sobre-detección): {list(abstract_actors)[:6]}")

def audit_caracterizacion(emociones, enunciador, report):
    if not emociones:
        return
    n = len(emociones)
    echo = [e for e in emociones
            if (e.get("caracterizacion__fuente") or "").strip().lower()
            == (e.get("caracterizacion__tipo_fuente") or "").strip().lower()
            and (e.get("caracterizacion__fuente") or "").strip()]
    report["fuente_echo_tipo"] = len(echo)
    if echo:
        add("ALTO", "characterizer",
            f"{len(echo)}/{n} emociones con `fuente` = literal de `tipo_fuente` "
            f"(p.ej. 'actor','situacion'). El prompt pide fuente CONCRETA en "
            "lenguaje natural; el modelo eco-repite la categoría.")
    canon_empty = sum(1 for e in emociones if not (e.get("tipo_emocion_canonico") or "").strip())
    report["canonico_vacio"] = canon_empty
    if canon_empty:
        add("ALTO", "normalize_emotions",
            f"{canon_empty}/{n} emociones SIN nombre canónico. "
            "normalize_emotions no corrió/falló o falta cargar la ontología. "
            "Rompe toda agregación por emoción.")
    # coherencias tipo domain-validator (informativas)
    afor_alta = sum(1 for e in emociones
                    if e.get("caracterizacion__foria") == "aforico"
                    and e.get("caracterizacion__intensidad") == "alta")
    if afor_alta:
        add("BAJO", "coherencia",
            f"{afor_alta} emociones afóricas con intensidad alta (V04: tensión).")
    noid_alta = sum(1 for e in emociones
                    if "no" in (e.get("caracterizacion__tipo_fuente") or "")
                    and e.get("caracterizacion__intensidad") == "alta")
    if noid_alta:
        add("BAJO", "coherencia",
            f"{noid_alta} emociones con fuente no identificada e intensidad alta (V02).")
    # experienciador == enunciador
    if enunciador:
        same = sum(1 for e in emociones if enunciador.lower() in (e.get("experienciador") or "").lower())
        report["experienciador_es_enunciador"] = same
    # experienciadores heterogéneos para "la misma" entidad
    exps = Counter((e.get("experienciador") or "").strip() for e in emociones)
    report["experienciadores"] = dict(exps)

def audit_actantes(emociones, report):
    if not emociones:
        return
    n = len(emociones)
    comps = {
        "mediador": ("actantes__mediador__presente", "actantes__mediador__tipo"),
        "verificador_normativo": ("actantes__verificador_normativo__presente", "actantes__verificador_normativo__tipo"),
        "verificador_observacional": ("actantes__verificador_observacional__presente", "actantes__verificador_observacional__tipo"),
        "operador_modificacion": ("actantes__operador_modificacion__presente", "actantes__operador_modificacion__funcion"),
    }
    rep = {}
    for comp, (pcol, tcol) in comps.items():
        present = sum(1 for e in emociones if is_true(e.get(pcol)))
        tipos = Counter((e.get(tcol) or "").strip() for e in emociones if is_true(e.get(pcol)))
        rep[comp] = {"presente_pct": pct(present, n), "tipos": dict(tipos)}
        # uniformidad: componente casi siempre presente y con un solo valor
        if present >= 0.9 * n and len(tipos) <= 1 and present > 0:
            add("MEDIO", "actants",
                f"'{comp}' presente en {pct(present,n)}% con un único valor "
                f"{list(tipos)}: el componente no discrimina (default colapsado).")
    report["actantes"] = rep

# ───────────────────────── Main ─────────────────────────

def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "."
    discursos = read_csv(os.path.join(base, "discursos.csv"))
    frases = read_csv(os.path.join(base, "frases.csv"))
    emociones = read_csv(os.path.join(base, "emociones.csv"))

    enunciador = ""
    if discursos:
        enunciador = (discursos[0].get("enunciation__enunciador") or "").strip()

    report = {}
    audit_discursos(discursos, report)
    audit_export_integrity(frases, emociones, report)
    audit_passes(frases, emociones, report)
    audit_actores(frases, report)
    audit_caracterizacion(emociones, enunciador, report)
    audit_actantes(emociones, report)

    # ── imprimir ──
    order = {"ALTO": 0, "MEDIO": 1, "BAJO": 2, "WARN": 3}
    FINDINGS.sort(key=lambda f: order.get(f[0], 9))
    print("\n" + "=" * 74)
    print(f"  EMOPARSE AUDIT — {os.path.abspath(base)}")
    print("=" * 74)
    print(f"  discursos={len(discursos or [])}  frases={len(frases or [])}  "
          f"emociones={len(emociones or [])}")
    print("-" * 74)
    if not FINDINGS:
        print("  Sin hallazgos. 🎉")
    for sev, area, msg in FINDINGS:
        tag = {"ALTO": "[!!]", "MEDIO": "[! ]", "BAJO": "[· ]", "WARN": "[? ]"}[sev]
        # wrap simple
        print(f"  {tag} ({area}) {msg}")
    print("-" * 74)
    counts = Counter(f[0] for f in FINDINGS)
    print(f"  Totales: " + "  ".join(f"{k}={counts.get(k,0)}" for k in ("ALTO","MEDIO","BAJO","WARN")))
    print("=" * 74 + "\n")

    report["_findings"] = [{"sev": s, "area": a, "msg": m} for s, a, m in FINDINGS]
    out = os.path.join(base, "audit_report.json")
    try:
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    except OSError:
        out = os.path.join(os.getcwd(), "audit_report.json")
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)
    print(f"  Métricas completas → {out}\n")

if __name__ == "__main__":
    main()
