# ══════════════════════════════════════════════════════════════════════════════
#  tests.contrato.test_payload_selection
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pandas as pd
import pytest

from emoparse.inputs.seleccion import Seleccion, SeleccionError, aplicar_seleccion
from emoparse.pipeline.payload_selection import PayloadSelectionEngine
from emoparse.pipeline.status import collect_stage_statuses
from emoparse.storage.db import Database
from emoparse.storage.discursos import DiscursosRepository
from emoparse.storage.frases import FrasesRepository
from emoparse.storage.models import RunContext
from emoparse.storage.runs import RunsRepository


def _selection(*filters: dict) -> Seleccion:
    return Seleccion.model_validate({"seleccion": list(filters)})


def _bootstrap(db: Database) -> tuple[DiscursosRepository, FrasesRepository]:
    RunsRepository(db).bootstrap(RunContext(run_id="selector_test"))
    discursos = DiscursosRepository(db)
    frases = FrasesRepository(db)
    for code in ("A", "B", "C"):
        discursos.upsert_input(code, {"contenido": f"Texto {code}", "fuente": "x"})
    return discursos, frases


def test_selection_splits_input_and_payload_filters() -> None:
    selection = _selection(
        {"field": "fuente", "op": "eq", "value": "x"},
        {"field": "metadata.tipo_discurso", "op": "eq", "value": "politico"},
    )

    assert [item.field for item in selection.input_filters()] == ["fuente"]
    assert [item.field for item in selection.payload_filters()] == ["metadata.tipo_discurso"]
    assert selection.payload_filters()[0].payload_path == "tipo_discurso"


def test_payload_only_selection_does_not_filter_input_dataframe() -> None:
    selection = _selection({"field": "metadata.tipo_discurso", "op": "eq", "value": "politico"})
    frame = pd.DataFrame(
        [
            {"codigo": "A", "contenido": "Uno"},
            {"codigo": "B", "contenido": "Dos"},
        ]
    )

    result = aplicar_seleccion(frame, selection)

    assert list(result["codigo"]) == ["A", "B"]


def test_payload_filter_activates_only_after_producer(database: Database) -> None:
    discursos, _ = _bootstrap(database)
    discursos.set_payload("A", "metadata", {"tipo_discurso": "politico"})
    discursos.set_payload("B", "metadata", {"tipo_discurso": "entrevista"})
    discursos.set_payload("C", "metadata", {"tipo_discurso": "politico"})
    selection = _selection({"field": "metadata.tipo_discurso", "op": "eq", "value": "politico"})
    engine = PayloadSelectionEngine(
        database,
        selection,
        ("metadata", "enunciation", "actors"),
    )

    engine.prepare()

    assert engine.scope_for("metadata") is None
    assert engine.scope_for("enunciation") == frozenset({"A", "C"})
    assert engine.scope_for("actors") == frozenset({"A", "C"})


def test_disabled_incomplete_producer_fails_explicitly(database: Database) -> None:
    _bootstrap(database)
    selection = _selection({"field": "enunciation.enunciador", "op": "eq", "value": "presidente"})
    engine = PayloadSelectionEngine(database, selection, ("actors", "emotions"))

    with pytest.raises(SeleccionError, match="enunciation.*completa"):
        engine.prepare()


def test_filter_without_later_enabled_stage_is_rejected(database: Database) -> None:
    discursos, _ = _bootstrap(database)
    for code in ("A", "B", "C"):
        discursos.set_payload(code, "metadata", {"tipo_discurso": "politico"})
    selection = _selection({"field": "metadata.tipo_discurso", "op": "eq", "value": "politico"})
    engine = PayloadSelectionEngine(database, selection, ("metadata",))

    with pytest.raises(SeleccionError, match="ninguna stage habilitada posterior"):
        engine.prepare()


def test_unsupported_payload_source_is_rejected(database: Database) -> None:
    _bootstrap(database)
    selection = _selection({"field": "modalidad.naturaleza", "op": "eq", "value": "persona"})
    engine = PayloadSelectionEngine(database, selection, ("modalidad", "semas"))

    with pytest.raises(SeleccionError, match="todavía no expone"):
        engine.prepare()


def test_status_distinguishes_outside_scope_from_pending_and_not_applicable(
    database: Database,
) -> None:
    discursos, frases = _bootstrap(database)
    tipos = {"A": "politico", "B": "politico", "C": "entrevista"}
    for code, tipo in tipos.items():
        discursos.set_payload(code, "metadata", {"tipo_discurso": tipo})
    frases.upsert_frases(
        [
            ("A", 0, "Frase A"),
            ("B", 0, "Frase B"),
            ("C", 0, "Frase C"),
        ]
    )
    frases.set_payload("A", 0, "actores", [{"actor": "A"}])
    frases.set_payload("C", 0, "actores", [{"actor": "C"}])

    selection = _selection({"field": "metadata.tipo_discurso", "op": "eq", "value": "politico"})
    engine = PayloadSelectionEngine(database, selection, ("metadata", "actors"))
    engine.prepare()
    assert engine.scope_for("actors") == frozenset({"A", "B"})

    status = next(
        item
        for item in collect_stage_statuses(database._get_connection())
        if item.stage == "actors"
    )

    assert status.completed == 1
    assert status.pending == 1
    assert status.fuera_alcance == 1
    assert status.no_aplica == 0


def test_run_without_payload_selector_restores_full_pending_universe(
    database: Database,
) -> None:
    discursos, frases = _bootstrap(database)
    for code in ("A", "B", "C"):
        discursos.set_payload(
            code,
            "metadata",
            {"tipo_discurso": "politico" if code != "C" else "entrevista"},
        )
    frases.upsert_frases([(code, 0, f"Frase {code}") for code in ("A", "B", "C")])
    frases.set_payload("A", 0, "actores", [{"actor": "A"}])
    frases.set_payload("C", 0, "actores", [{"actor": "C"}])

    selection = _selection({"field": "metadata.tipo_discurso", "op": "eq", "value": "politico"})
    selected = PayloadSelectionEngine(database, selection, ("metadata", "actors"))
    selected.prepare()
    selected.scope_for("actors")

    full = PayloadSelectionEngine(database, None, ("actors",))
    full.prepare()
    status = next(
        item
        for item in collect_stage_statuses(database._get_connection())
        if item.stage == "actors"
    )

    assert status.completed == 2
    assert status.pending == 1
    assert status.fuera_alcance == 0


def test_stage_executes_only_codes_in_dynamic_scope(database: Database) -> None:
    from emoparse.pipeline.stages import TechnoparseStage
    from emoparse.storage.tecno import TecnoRepository

    discursos, frases = _bootstrap(database)
    frases.upsert_frases([(code, 0, f"Texto #{code.lower()}") for code in ("A", "B", "C")])
    tecno = TecnoRepository(database)
    stage = TechnoparseStage(discursos, frases, tecno)
    stage.set_selector_scope(frozenset({"A", "C"}))

    stage.run_pending()

    rows = database.execute(
        "SELECT DISTINCT codigo FROM tecno_entidades ORDER BY codigo"
    ).fetchall()
    assert [str(row["codigo"]) for row in rows] == ["A", "C"]
