# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.evaluation.sampling
#
#  Muestreo estratificado para anotación humana a ciegas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import random
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from emoparse.evaluation.annotations import ANNOTATION_COLUMNS
from emoparse.genres.presentation import presentation_from_config


def make_annotation_sample(
    db_path: Path | str,
    n: int = 200,
    seed: int = 42,
    *,
    min_texts: int = 1,
    max_per_text: int | None = None,
    genre_override: str | None = None,
) -> pd.DataFrame:
    """Muestra reproducible, diversa y ciega de unidades para anotar."""
    if n < 1:
        raise ValueError("`n` debe ser mayor o igual que 1")
    if min_texts < 1:
        raise ValueError("`min_texts` debe ser mayor o igual que 1")
    if max_per_text is not None and max_per_text < 1:
        raise ValueError("`max_per_text` debe ser mayor o igual que 1")

    conn = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        frases = conn.execute(
            "SELECT codigo, unit_idx, frase FROM frases ORDER BY codigo, unit_idx"
        ).fetchall()
        con_emocion = {
            (str(r["codigo"]), int(r["frase_idx"]))
            for r in conn.execute("SELECT DISTINCT codigo, frase_idx FROM emociones").fetchall()
        }
        contextos = _contextos_de_hilo(conn)
        genre = genre_override or _run_genre(conn)
    finally:
        conn.close()

    if not genre:
        raise ValueError(
            "el run no conserva metadata de género; indicá `--genero` para etiquetar la muestra"
        )
    if len(frases) < n:
        raise ValueError(f"el run contiene {len(frases)} unidades y se pidieron {n}")

    available_texts = {str(row["codigo"]) for row in frases}
    if len(available_texts) < min_texts:
        raise ValueError(
            f"el run contiene {len(available_texts)} textos y se requieren al menos {min_texts}"
        )

    positives = [row for row in frases if _row_key(row) in con_emocion]
    negatives = [row for row in frases if _row_key(row) not in con_emocion]
    rng = random.Random(seed)
    selected = _stratified_diverse_sample(
        positives,
        negatives,
        n=n,
        rng=rng,
        max_per_text=max_per_text,
    )
    rng.shuffle(selected)

    selected_texts = {str(row["codigo"]) for row in selected}
    if len(selected_texts) < min_texts:
        raise ValueError(
            "la combinación de tamaño y límite por texto solo produjo "
            f"{len(selected_texts)} textos; se requieren {min_texts}"
        )

    rows: list[dict[str, Any]] = []
    for index, row in enumerate(selected, start=1):
        rows.append(
            {
                "id_muestra": f"u{index:04d}",
                "genero": genre,
                "codigo": str(row["codigo"]),
                "unit_idx": int(row["unit_idx"]),
                "contexto": contextos.get(str(row["codigo"]), ""),
                "texto": str(row["frase"]),
                **{column: "" for column in ANNOTATION_COLUMNS},
            }
        )
    return pd.DataFrame(rows)


def _stratified_diverse_sample(
    positives: list[sqlite3.Row],
    negatives: list[sqlite3.Row],
    *,
    n: int,
    rng: random.Random,
    max_per_text: int | None,
) -> list[sqlite3.Row]:
    target_positive = min(n // 2, len(positives))
    target_negative = min(n - target_positive, len(negatives))
    remaining = n - target_positive - target_negative
    if remaining:
        positive_spare = len(positives) - target_positive
        add_positive = min(remaining, positive_spare)
        target_positive += add_positive
        remaining -= add_positive
        target_negative += min(remaining, len(negatives) - target_negative)

    counts: dict[str, int] = defaultdict(int)
    selected: list[sqlite3.Row] = []
    chosen_keys: set[tuple[str, int]] = set()
    for rows, target in ((positives, target_positive), (negatives, target_negative)):
        picked = _sample_round_robin(
            rows,
            target,
            rng=rng,
            max_per_text=max_per_text,
            counts=counts,
            chosen_keys=chosen_keys,
        )
        selected.extend(picked)

    if len(selected) < n:
        remaining_rows = [
            row for row in (*positives, *negatives) if _row_key(row) not in chosen_keys
        ]
        selected.extend(
            _sample_round_robin(
                remaining_rows,
                n - len(selected),
                rng=rng,
                max_per_text=max_per_text,
                counts=counts,
                chosen_keys=chosen_keys,
            )
        )
    if len(selected) < n:
        limit = f" con max_per_text={max_per_text}" if max_per_text is not None else ""
        raise ValueError(f"no se pudieron seleccionar {n} unidades diversas{limit}")
    return selected


def _sample_round_robin(
    rows: list[sqlite3.Row],
    target: int,
    *,
    rng: random.Random,
    max_per_text: int | None,
    counts: dict[str, int],
    chosen_keys: set[tuple[str, int]],
) -> list[sqlite3.Row]:
    by_text: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_text[str(row["codigo"])].append(row)
    for group in by_text.values():
        rng.shuffle(group)
    texts = list(by_text)
    rng.shuffle(texts)

    selected: list[sqlite3.Row] = []
    while len(selected) < target:
        progressed = False
        for text in texts:
            if len(selected) >= target:
                break
            if max_per_text is not None and counts[text] >= max_per_text:
                continue
            group = by_text[text]
            while group and _row_key(group[-1]) in chosen_keys:
                group.pop()
            if not group:
                continue
            row = group.pop()
            selected.append(row)
            chosen_keys.add(_row_key(row))
            counts[text] += 1
            progressed = True
        if not progressed:
            break
    return selected


def _row_key(row: sqlite3.Row) -> tuple[str, int]:
    return str(row["codigo"]), int(row["unit_idx"])


def _run_genre(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT config FROM runs LIMIT 1").fetchone()
    except sqlite3.OperationalError:
        return None
    if row is None or not row["config"]:
        return None
    try:
        config = json.loads(str(row["config"]))
    except json.JSONDecodeError:
        return None
    presentation = presentation_from_config(config)
    return presentation.genre_id if presentation is not None else None


def _contextos_de_hilo(conn: sqlite3.Connection) -> dict[str, str]:
    """Contexto conversacional por post (padre inmediato), si el run lo tiene."""
    try:
        rows = conn.execute(
            "SELECT p.post_id, padre.autor_handle AS h, padre.texto AS t "
            "FROM posts p JOIN posts padre ON padre.post_id = p.en_respuesta_a"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {str(r["post_id"]): f"[responde a @{r['h']}]: {r['t']}" for r in rows}
