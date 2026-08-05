# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.components.tab_modelos
#
#  Comparación post-hoc de runs independientes del mismo corpus.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from emoparse.app import data as data_layer
from emoparse.evaluation.run_comparison import (
    RunOverview,
    compare_runs,
    load_run_overview,
)


def render(runs_dir: Path, active_db: Path) -> None:
    """Renderiza la comparación de modelos y configuraciones entre runs."""
    st.markdown("### Comparar modelos")
    st.markdown(
        "<p style='color:var(--text-dim);font-size:0.88rem;'>"
        "Seleccioná runs independientes construidos sobre el mismo corpus. "
        "La vista compara procedencia, reportes persistidos, acuerdo y referencias."
        "</p>",
        unsafe_allow_html=True,
    )

    runs = data_layer.list_runs(runs_dir)
    if not runs:
        st.info("No hay runs disponibles para comparar.")
        return

    by_path = {run.path.resolve(): run for run in runs}
    options = [run.path.resolve() for run in runs]
    active = active_db.resolve()
    default = [active] if active in by_path else options[:1]
    selected = st.multiselect(
        "Runs",
        options=options,
        default=default,
        format_func=lambda path: by_path[path].name,
        key="model_comparison_runs",
    )
    if not selected:
        st.info("Seleccioná al menos un run.")
        return

    overviews: list[RunOverview] = []
    failures: list[str] = []
    for path in selected:
        try:
            overviews.append(load_run_overview(path))
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        st.error("No se pudieron leer algunos runs: " + " · ".join(failures))
    if not overviews:
        return

    _render_metadata(overviews)
    _render_models(overviews)
    _render_reports(overviews)

    if len(overviews) < 2:
        st.caption("Seleccioná al menos dos runs para calcular acuerdo y coincidencias.")
        return

    try:
        comparison = compare_runs([overview.path for overview in overviews])
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        st.error(f"No se pudo realizar la comparación: {exc}")
        return

    if comparison.same_corpus:
        st.success(f"Corpus coincidente: {comparison.common_units} unidades comunes.")
    else:
        st.warning(
            "Los runs no contienen exactamente el mismo corpus. "
            f"La comparación usa {comparison.common_units} unidades comunes."
        )
        st.dataframe(
            pd.DataFrame(
                [
                    {"run": name, "firma_corpus": signature}
                    for name, signature in comparison.corpus_signatures.items()
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("#### Acuerdo entre runs")
    agreement = pd.DataFrame(comparison.agreement)
    if not agreement.empty:
        agreement["alpha"] = agreement["alpha"].map(_format_number)
        st.dataframe(agreement, hide_index=True, use_container_width=True)
    else:
        st.info("No hay unidades comunes suficientes para calcular acuerdo.")

    st.markdown("#### Coincidencias referenciales")
    references = pd.DataFrame(comparison.reference_matches)
    if references.empty:
        st.info("No hay referencias comparables.")
    else:
        st.dataframe(references, hide_index=True, use_container_width=True)

    st.markdown("#### Violaciones de contrato")
    violations = pd.DataFrame(comparison.contract_violations)
    if violations.empty:
        st.info("No hay resultados referenciales para comprobar.")
    else:
        st.dataframe(violations, hide_index=True, use_container_width=True)


def _render_metadata(overviews: list[RunOverview]) -> None:
    rows = []
    for overview in overviews:
        rows.append(
            {
                "run": overview.path.stem,
                "run_id": overview.run_id,
                "género": _genre_label(overview),
                "estado": overview.status or "—",
                "unidades": overview.units,
                "emociones": overview.emotions,
                "knowledge": overview.versions.get("knowledge") or "—",
                "prompt": overview.versions.get("prompt") or "—",
                "ontology": overview.versions.get("ontology") or "—",
                "schema": overview.versions.get("schema") or "—",
                "notas": overview.notes or "—",
            }
        )
    st.markdown("#### Runs seleccionados")
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def _render_models(overviews: list[RunOverview]) -> None:
    rows: list[dict[str, Any]] = []
    mixed: list[str] = []
    for overview in overviews:
        stages = sorted(set(overview.configured_models) | set(overview.observed_models))
        for stage in stages:
            observed = overview.observed_models.get(stage, ())
            rows.append(
                {
                    "run": overview.path.stem,
                    "stage": stage,
                    "configurado": overview.configured_models.get(stage, "—"),
                    "observado": ", ".join(observed) if observed else "—",
                    "mixto": "sí" if len(observed) > 1 else "no",
                }
            )
        if overview.mixed_stages:
            details = "; ".join(
                f"{stage}: {', '.join(aliases)}"
                for stage, aliases in sorted(overview.mixed_stages.items())
            )
            mixed.append(f"{overview.path.stem} ({details})")

    st.markdown("#### Modelos por etapa")
    if mixed:
        st.error("Run mixto detectado: " + " · ".join(mixed))
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    else:
        st.info("Estos runs todavía no conservan procedencia observada por etapa.")


def _render_reports(overviews: list[RunOverview]) -> None:
    golden_rows: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    dimension_rows: list[dict[str, Any]] = []
    for overview in overviews:
        golden = overview.latest_reports.get("golden")
        if golden is not None:
            payload = _payload(golden)
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            golden_rows.append(
                {
                    "run": overview.path.stem,
                    "género": payload.get("genre") or overview.genre or "—",
                    "golden": golden.get("golden_version") or "—",
                    "fecha": golden.get("recorded_at") or "—",
                    "unidades": metrics.get("unidades"),
                    "precisión": _format_number(metrics.get("precision")),
                    "recall": _format_number(metrics.get("recall")),
                    "f1": _format_number(metrics.get("f1")),
                }
            )
            aggregate = payload.get("aggregate_metrics")
            if isinstance(aggregate, dict):
                aggregate_rows.append(
                    {
                        "run": overview.path.stem,
                        "golden": golden.get("golden_version") or "—",
                        "unidades": aggregate.get("unidades"),
                        "precisión": _format_number(aggregate.get("precision")),
                        "recall": _format_number(aggregate.get("recall")),
                        "f1": _format_number(aggregate.get("f1")),
                    }
                )
            dimensions = metrics.get("dimensiones")
            if isinstance(dimensions, dict):
                for dimension, values in dimensions.items():
                    values = values if isinstance(values, dict) else {}
                    dimension_rows.append(
                        {
                            "run": overview.path.stem,
                            "dimensión": dimension,
                            "correctas": values.get("correctas"),
                            "evaluadas": values.get("evaluadas"),
                            "accuracy": _format_number(values.get("accuracy")),
                        }
                    )

        control = overview.latest_reports.get("control")
        if control is not None:
            payload = _payload(control)
            metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
            control_rows.append(
                {
                    "run": overview.path.stem,
                    "fecha": control.get("recorded_at") or "—",
                    "unidades": metrics.get("unidades"),
                    "emociones": metrics.get("emociones_detectadas"),
                    "unidades_con_emoción": metrics.get("unidades_con_emocion"),
                    "tasa_detección": _format_number(metrics.get("tasa_deteccion")),
                }
            )

    st.markdown("#### Reportes persistidos")
    if golden_rows:
        st.markdown("**Golden**")
        st.dataframe(pd.DataFrame(golden_rows), hide_index=True, use_container_width=True)
        if aggregate_rows:
            st.markdown("**Resultado agregado multigénero**")
            st.dataframe(
                pd.DataFrame(aggregate_rows).drop_duplicates(),
                hide_index=True,
                use_container_width=True,
            )
        if dimension_rows:
            st.dataframe(pd.DataFrame(dimension_rows), hide_index=True, use_container_width=True)
    else:
        st.info("Los runs seleccionados no tienen reportes contra golden persistidos.")

    if control_rows:
        st.markdown("**Corpus de control**")
        st.dataframe(pd.DataFrame(control_rows), hide_index=True, use_container_width=True)


def _payload(report: dict[str, Any]) -> dict[str, Any]:
    payload = report.get("payload")
    return payload if isinstance(payload, dict) else {}


def _genre_label(overview: RunOverview) -> str:
    if not overview.genre:
        return "—"
    if overview.genre_source in {None, "snapshot"}:
        return overview.genre
    return f"{overview.genre} (inferido)"


def _format_number(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.3f}"
    except (TypeError, ValueError):
        return str(value)
