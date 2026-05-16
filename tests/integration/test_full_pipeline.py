# ══════════════════════════════════════════════════════════════════════════════
#  tests.integration.test_full_pipeline
#
#  Recorrido completo del pipeline sobre un corpus mínimo, con un
#  backend simulado (sin modelos ni GPU). Verifica que todas las
#  etapas — incluidas las opcionales — se ejecuten en orden y dejen
#  las tablas en un estado consistente.
#
#  El backend simulado genera, para cada llamada, una instancia válida
#  del esquema que el agente solicita. Esto permite ejercitar el
#  pipeline entero sin acoplar el test a la salida concreta de cada
#  etapa: lo que se valida es la integración (orden, persistencia,
#  contratos entre etapas), no la calidad semántica de las respuestas.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import sqlite3
import typing
from pathlib import Path
from typing import Any, get_args, get_origin

import pandas as pd
import pytest
from pydantic import BaseModel
from pydantic import RootModel

from emoparse.config import load_config
from emoparse.core.backend.base import LLMBackend, LLMResponse, TokenUsage
from emoparse.knowledge import KnowledgeLoader
from emoparse.pipeline import PipelineRunner


# ── Backend simulado ──────────────────────────────────────────────────────────

def _build_valid(model: type[BaseModel]) -> BaseModel:
    """Construye una instancia válida mínima de un modelo Pydantic.

    Recorre los campos del modelo y asigna a cada uno un valor que
    satisface su anotación de tipo. Soporta los tipos que aparecen en
    los esquemas del proyecto: primitivos, ``Literal``, ``Optional``,
    listas, modelos anidados y ``RootModel`` de lista.
    """
    # RootModel[list[X]]: devolver una lista con un elemento de X.
    if issubclass(model, RootModel):
        inner = model.model_fields["root"].annotation
        origin = get_origin(inner)
        if origin in (list, typing.List):
            (item_type,) = get_args(inner)
            return model(root=[_value_for(item_type)])
        return model(root=_value_for(inner))

    kwargs: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        kwargs[name] = _value_for(field.annotation)
    return model(**kwargs)


def _value_for(annotation: Any) -> Any:
    """Devuelve un valor válido para una anotación de tipo dada."""
    origin = get_origin(annotation)

    # Optional[T] / Union[...]: tomar el primer tipo no-None.
    if origin is typing.Union:
        args = [a for a in get_args(annotation) if a is not type(None)]
        return _value_for(args[0]) if args else None

    # Literal[...]: primer valor admitido.
    if origin is typing.Literal:
        return get_args(annotation)[0]

    # list[T]: lista con un elemento.
    if origin in (list, typing.List):
        (item_type,) = get_args(annotation) or (str,)
        return [_value_for(item_type)]

    # dict: vacío.
    if origin in (dict, typing.Dict):
        return {}

    # Modelo Pydantic anidado.
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _build_valid(annotation)

    # Primitivos.
    if annotation in (str, Any) or annotation is None:
        return "x"
    if annotation is int:
        return 0
    if annotation is float:
        return 0.0
    if annotation is bool:
        return False

    # Fallback razonable.
    return "x"


class _SchemaDrivenBackend(LLMBackend):
    """Backend que responde con una instancia válida del esquema pedido.

    No depende del orden de las llamadas: cada respuesta se deriva del
    parámetro ``schema`` que el agente pasa a ``generate``.
    """

    def __init__(self) -> None:
        self.alias = "fake"
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        system: str,
        user: str,
        *,
        schema: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        seed: int | None = None,
        stop: list[str] | None = None,
        reset_before: bool = False,
    ) -> LLMResponse:
        self.calls.append({"schema": getattr(schema, "__name__", None)})
        if schema is None:
            parsed: Any = None
        else:
            parsed = _build_valid(schema)
        return LLMResponse(
            parsed=parsed,
            raw="(fake)",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1),
            latency_ms=0.1,
            model_alias=self.alias,
            cache_hit=False,
            finish_reason="stop",
        )

    def healthcheck(self) -> bool:
        return True


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def runner(tmp_path: Path):
    """PipelineRunner apuntando a una DB temporal, con todas las etapas.

    Usa el `config.example.yaml` del repo como configuración base y el
    directorio `knowledge/` del repo como knowledge base.
    """
    repo_root = Path(__file__).resolve().parents[2]
    cfg_path = repo_root / "config.example.yaml"
    knowledge_dir = repo_root / "knowledge"

    cfg = load_config(str(cfg_path))
    loader = KnowledgeLoader(knowledge_dir)
    db_path = tmp_path / "test_run.sqlite"

    # Todas las etapas, incluidas las opcionales.
    all_stages = (
        "summarizer", "metadata", "enunciation", "actors",
        "normalize_actors", "emotions", "emotions_pass2",
        "explode_emociones", "normalize_emotions",
        "characterizer", "actants", "judge",
    )

    backend = _SchemaDrivenBackend()
    runner = PipelineRunner(
        run_id="test_run",
        config=cfg,
        knowledge=loader,
        db_path=db_path,
        enabled_stages=all_stages,
    )
    # Inyectar el backend simulado en todas las etapas. El runner
    # resuelve el backend por alias a través de un registry interno;
    # acá lo sustituimos por el simulado para no requerir modelos.
    _patch_backends(runner, backend)
    return runner, backend, db_path


def _patch_backends(runner: PipelineRunner, backend: LLMBackend) -> None:
    """Fuerza a que el runner use el backend simulado para toda etapa.

    Implementado de forma defensiva: si la API interna del runner
    cambiara, el test falla con un mensaje claro en lugar de un error
    opaco.
    """
    patched = False
    for attr in dir(runner):
        if attr.startswith("_get_backend"):
            setattr(runner, attr, lambda *a, **k: backend)
            patched = True
    if not patched:
        # Camino alternativo: registry expuesto como atributo.
        for attr in ("_registry", "_backends", "_backend_registry"):
            if hasattr(runner, attr):
                reg = getattr(runner, attr)
                if hasattr(reg, "get"):
                    reg.get = lambda *a, **k: backend  # type: ignore[assignment]
                    patched = True
    assert patched, (
        "No se pudo inyectar el backend simulado: la API interna del "
        "runner para resolver backends cambió. Revisar _get_backend()."
    )


# ── Test ──────────────────────────────────────────────────────────────────────

def test_full_pipeline_all_stages(runner) -> None:
    """El pipeline completo corre y deja las tablas consistentes."""
    run, backend, db_path = runner

    with run:
        run.ingest(_corpus_df())
        report = run.run()

    # 1. El reporte cubre todas las etapas con LLM habilitadas.
    for stage in (
        "summarizer", "metadata", "enunciation", "actors",
        "normalize_actors", "emotions", "emotions_pass2",
        "normalize_emotions", "characterizer", "actants", "judge",
    ):
        assert stage in report, f"Etapa ausente en el reporte: {stage}"

    # 2. La DB tiene las tablas principales pobladas.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        discursos = conn.execute("SELECT COUNT(*) AS n FROM discursos").fetchone()["n"]
        frases = conn.execute("SELECT COUNT(*) AS n FROM frases").fetchone()["n"]
        emociones = conn.execute("SELECT COUNT(*) AS n FROM emociones").fetchone()["n"]

        assert discursos == 2, f"Esperaba 2 discursos, hay {discursos}"
        assert frases > 0, "No se generaron frases"
        assert emociones > 0, "No se generaron emociones"

        # 3. La etapa de análisis actancial dejó payload en al menos
        #    una emoción (columna agregada por la migración aditiva).
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(emociones)").fetchall()
        }
        assert "actantes_payload" in cols, (
            "La columna actantes_payload no existe: la migración aditiva "
            "no corrió."
        )
        con_actantes = conn.execute(
            "SELECT COUNT(*) AS n FROM emociones "
            "WHERE actantes_payload IS NOT NULL"
        ).fetchone()["n"]
        assert con_actantes > 0, (
            "Ninguna emoción tiene análisis actancial persistido"
        )

        # 4. El run quedó marcado como completado.
        status = conn.execute("SELECT status FROM runs LIMIT 1").fetchone()["status"]
        assert status == "completed", f"Estado del run: {status}"
    finally:
        conn.close()


def test_default_stages_skip_optional(tmp_path: Path) -> None:
    """Con las etapas por defecto, las opcionales no se ejecutan."""
    repo_root = Path(__file__).resolve().parents[2]
    cfg = load_config(str(repo_root / "config.example.yaml"))
    loader = KnowledgeLoader(repo_root / "knowledge")

    backend = _SchemaDrivenBackend()
    run = PipelineRunner(
        run_id="test_default",
        config=cfg,
        knowledge=loader,
        db_path=tmp_path / "default.sqlite",
    )
    _patch_backends(run, backend)

    with run:
        run.ingest(_corpus_df())
        report = run.run()

    # Las opcionales no deben aparecer como ejecutadas.
    for opt in ("normalize_actors", "emotions_pass2", "actants", "judge"):
        assert opt not in report, (
            f"La etapa opcional '{opt}' se ejecutó sin pedirla"
        )
    # Las activas por defecto sí.
    for active in ("summarizer", "emotions", "characterizer"):
        assert active in report


# El corpus se reusa entre tests sin recargar el fixture de DataFrame.
def _corpus_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "codigo": "D1",
                "contenido": (
                    "Hoy celebramos un logro importante. "
                    "El pueblo trabajó con esfuerzo. Nadie debería temer al futuro."
                ),
                "titulo": "Discurso uno",
            },
            {
                "codigo": "D2",
                "contenido": (
                    "Lamentamos lo ocurrido. Hay quienes sienten bronca. "
                    "Pero también hay esperanza en el horizonte."
                ),
                "titulo": "Discurso dos",
            },
        ]
    )
