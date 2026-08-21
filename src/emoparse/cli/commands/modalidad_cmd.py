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

from emoparse.config import ConfigError, load_config


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

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        logger.error(f"[modalidad] Config inválido: {exc}")
        return 1

    db = Database(db_path)
    # Asegura las columnas de modalidad/proveniencia en DBs viejas.
    RunsRepository(db).ensure_migrations()

    d_repo = DiscursosRepository(db)
    m_repo = MencionesRepository(db)

    stage = ModalidadStage(
        d_repo,
        m_repo,
        backend=None,
        use_llm=False,  # este subcomando es NLP-only por diseño
        nlp_model=getattr(args, "nlp_model", None),
        agent_version=cfg.versions.prompt,
    )
    n = stage.run_pending()
    logger.info(f"[modalidad] {n} vínculos resueltos con alta confianza (NLP-only).")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Registra `modalidad` como subcomando en el CLI principal."""
    p = subparsers.add_parser(
        "modalidad",
        help="Clasifica la modalidad referencial de los vínculos (NLP-only).",
        description=(
            "Clasifica, con el pre-pass NLP (spaCy) y sin LLM, únicamente "
            "los vínculos cuya modalidad puede resolverse con alta confianza. "
            "Los casos ambiguos quedan pendientes; no se persiste un fallback "
            "tentativo. Idempotente y respetuoso de ediciones humanas. La "
            "variante con LLM se corre vía "
            "`emoparse run --stages ...,modalidad`."
        ),
    )
    p.add_argument("--db", required=True, help="Path al .sqlite del run.")
    p.add_argument(
        "--config",
        "-c",
        default="config.yaml",
        help="Path al YAML de config. Default: config.yaml.",
    )
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
