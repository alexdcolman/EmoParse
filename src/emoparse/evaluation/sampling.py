# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.sampling
#
#  Muestreo estratificado para anotación humana a ciegas.
#
#  Produce una planilla (CSV) con una fila por unidad muestreada: SOLO el
#  texto y su contexto, sin ninguna salida del modelo (anotación ciega).
#  La estratificación equilibra unidades donde el modelo detectó y no
#  detectó emociones (garantiza cobertura de ambos casos sin revelar cuál
#  es cuál) y muestrea proporcionalmente por discurso.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import random
import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd

#: Columnas vacías que completa cada anotador (ver evals/manual_anotacion.md).
ANNOTATION_COLUMNS: tuple[str, ...] = (
    "hay_emocion",       # si | no
    "emocion_1_experienciador", "emocion_1_tipo", "emocion_1_foria",
    "emocion_2_experienciador", "emocion_2_tipo", "emocion_2_foria",
    "emocion_3_experienciador", "emocion_3_tipo", "emocion_3_foria",
    "dudas_comentarios",
)


def make_annotation_sample(
    db_path: Path | str,
    n: int = 300,
    seed: int = 42,
) -> pd.DataFrame:
    """Muestra estratificada de unidades para anotar a ciegas."""
    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        frases = conn.execute(
            "SELECT codigo, unit_idx, frase FROM frases ORDER BY codigo, unit_idx"
        ).fetchall()
        con_emocion = {
            (str(r["codigo"]), int(r["frase_idx"]))
            for r in conn.execute(
                "SELECT DISTINCT codigo, frase_idx FROM emociones"
            ).fetchall()
        }
        contextos = _contextos_de_hilo(conn)
    finally:
        conn.close()

    positivas = [f for f in frases
                 if (str(f["codigo"]), int(f["unit_idx"])) in con_emocion]
    negativas = [f for f in frases
                 if (str(f["codigo"]), int(f["unit_idx"])) not in con_emocion]

    rng = random.Random(seed)
    mitad = n // 2
    muestra = (
        rng.sample(positivas, min(mitad, len(positivas)))
        + rng.sample(negativas, min(n - mitad, len(negativas)))
    )
    rng.shuffle(muestra)  # el orden no debe delatar el estrato

    rows: list[dict[str, Any]] = []
    for i, f in enumerate(muestra, start=1):
        rows.append({
            "id_muestra": f"u{i:04d}",
            "codigo": str(f["codigo"]),
            "unit_idx": int(f["unit_idx"]),
            "contexto": contextos.get(str(f["codigo"]), ""),
            "texto": str(f["frase"]),
            **{c: "" for c in ANNOTATION_COLUMNS},
        })
    return pd.DataFrame(rows)


def _contextos_de_hilo(conn: sqlite3.Connection) -> dict[str, str]:
    """Contexto conversacional por post (padre inmediato), si el run lo tiene."""
    try:
        rows = conn.execute(
            "SELECT p.post_id, padre.autor_handle AS h, padre.texto AS t "
            "FROM posts p JOIN posts padre ON padre.post_id = p.en_respuesta_a"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {
        str(r["post_id"]): f"[responde a @{r['h']}]: {r['t']}"
        for r in rows
    }
