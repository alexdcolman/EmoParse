# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.cli.commands.modalidad_cmd
#
#  Subcomando `modalidad`: clasifica la modalidad referencial de los vínculos
#  marca→referente de una DB existente usando SOLO el pre-pass NLP (spaCy), sin
#  LLM. La variante con LLM se corre vía `emoparse run --stages ...,modalidad`.
#
#  Es idempotente: solo clasifica vínculos aún sin `modalidad` y no pisa lo
#  editado a mano (modalidad_origin='human').
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import argparse
from pathlib import Path

from loguru import logger


def handle(args: argparse.Namespace) -> int:
    """Ejecuta la clasificación NLP-only de modalidad sobre la DB dada."""
    from emoparse.pipeline.stages import ModalidadStage
    from emoparse.storage.db import Database
    from emoparse.storage.discursos import DiscursosRepository
    from emoparse.storage.menciones import MencionesRepository
    from emoparse.storage.runs import RunsRepository

    db_path = Path(args.db)
    if not db_path.exists():
        logger.error(f"[modalidad] No existe la DB: {db_path}")
        return 2

    db = Database(db_path)
    # Asegura las columnas modalidad/naturaleza/modalidad_origin en DBs viejas.
    RunsRepository(db).ensure_migrations()

    d_repo = DiscursosRepository(db)
    m_repo = MencionesRepository(db)

    stage = ModalidadStage(
        d_repo,
        m_repo,
        backend=None,
        use_llm=False,  # este subcomando es NLP-only por diseño
        nlp_model=getattr(args, "nlp_model", None),
    )
    n = stage.run_pending()
    logger.info(f"[modalidad] {n} vínculos clasificados (NLP-only).")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `modalidad` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "modalidad",
        help="Clasifica la modalidad referencial de los vínculos (NLP-only).",
        description=(
            "Clasifica, con el pre-pass NLP (spaCy) y sin LLM, la modalidad "
            "referencial (designacion / referencia_gramatical / "
            "identificacion_inferencial) y la naturaleza del referente de cada "
            "vínculo marca→referente de una DB existente. Idempotente: solo "
            "clasifica lo que aún no tiene modalidad y no pisa lo editado a "
            "mano. La variante con LLM (para los casos ambiguos) se corre vía "
            "`emoparse run --stages ...,modalidad`."
        ),
    )
    p.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p.add_argument(
        "--nlp-model",
        dest="nlp_model",
        default=None,
        help=(
            "Modelo spaCy a usar (ES). Default: es_core_news_md con fallback a "
            "sm/lg. Instalá el modelo con `python -m spacy download <modelo>`."
        ),
    )
    p.set_defaults(handler=handle)
