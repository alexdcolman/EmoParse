# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.domain.validators.runner
#
#  Orquesta la ejecución de validators sobre una DB de EmoParse.
#
#  Diseño:
#   - Lee emociones caracterizadas de la DB.
#   - Aplica RowValidators sobre cada emoción.
#   - Agrupa por discurso y aplica DiscursoValidators.
#   - Persiste issues en la tabla validation_issues.
#   - Idempotente: borra issues previas del discurso antes de reinsertar.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

from loguru import logger

from emoparse.domain.validators.base import (
    DiscursoValidator,
    RowValidator,
    ValidationIssue,
)
from emoparse.domain.validators.rules import (
    DISCURSO_VALIDATORS,
    ROW_VALIDATORS,
    V11_DesviacionOntologica,
)
from emoparse.storage.db import Database
from emoparse.storage.validation import ValidationRepository


class ValidationRunner:
    """Ejecuta todos los validators sobre las emociones caracterizadas de una DB.

    Args:
        db: base de datos del run a validar.
        row_validators: lista de RowValidators. Default: ROW_VALIDATORS.
        discurso_validators: lista de DiscursoValidators. Default: DISCURSO_VALIDATORS.
        emotion_ontology: dict crudo cargado por
            KnowledgeLoader.load_emotion_ontology(). Si se provee, se
            construye V11_DesviacionOntologica y se agrega al final de
            row_validators. Si es None, V11 no se ejecuta.
    """

    def __init__(
        self,
        db: Database,
        row_validators: list[RowValidator] | None = None,
        discurso_validators: list[DiscursoValidator] | None = None,
        emotion_ontology: dict[str, Any] | None = None,
    ) -> None:
        self._db = db
        self._repo = ValidationRepository(db)

        row = list(row_validators) if row_validators is not None else list(ROW_VALIDATORS)
        if emotion_ontology is not None:
            row.append(V11_DesviacionOntologica(emotion_ontology))
            logger.debug("[ValidationRunner] V11_DesviacionOntologica registrado.")

        self._row_validators = row
        self._discurso_validators = (
            discurso_validators if discurso_validators is not None else DISCURSO_VALIDATORS
        )

    def run(self) -> list[ValidationIssue]:
        """Ejecuta la validación completa.

        Flujo:
          1. Cargar emociones caracterizadas agrupadas por discurso.
          2. Cargar contexto enunciativo.
          3. Aplicar RowValidators.
          4. Aplicar DiscursoValidators.
          5. Persistir issues.

        Returns:
            Lista de ValidationIssue. Vacía si no hay incoherencias.
        """
        all_issues: list[ValidationIssue] = []

        codigos = self._load_codigos_con_emociones_caracterizadas()
        if not codigos:
            logger.info("[ValidationRunner] No hay emociones caracterizadas para validar.")
            return []

        logger.info(f"[ValidationRunner] Validando {len(codigos)} discurso(s).")

        for codigo in codigos:
            issues = self._run_discurso(codigo)
            all_issues.extend(issues)

        if all_issues:
            self._repo.save_issues(all_issues)
            logger.info(f"[ValidationRunner] {len(all_issues)} issue(s) encontradas y persistidas.")
        else:
            logger.info("[ValidationRunner] Sin issues. Discursos coherentes.")

        return all_issues

    # ── Internals ────────────────────────────────────────────────────────────

    def _run_discurso(self, codigo: str) -> list[ValidationIssue]:
        """Valida un discurso completo. Devuelve sus issues."""
        enunciador, enunciatarios = self._load_enunciacion(codigo)
        emociones = self._load_emociones_con_caracterizacion(codigo)
        if not emociones:
            return []

        issues: list[ValidationIssue] = []

        self._repo.delete_issues_for_codigo(codigo)

        for emo in emociones:
            for validator in self._row_validators:
                try:
                    row_issues = validator.validate(
                        codigo=codigo,
                        frase_idx=emo["frase_idx"],
                        emocion_idx=emo["emocion_idx"],
                        experienciador=emo.get("experienciador", ""),
                        tipo_emocion=emo.get("tipo_emocion", ""),
                        modo_existencia=emo.get("modo_existencia", ""),
                        foria=emo.get("foria", ""),
                        dominancia=emo.get("dominancia", ""),
                        intensidad=emo.get("intensidad", ""),
                        tipo_fuente=emo.get("tipo_fuente", ""),
                        fuente=emo.get("fuente", ""),
                        enunciador=enunciador,
                        enunciatarios=enunciatarios,
                    )
                    issues.extend(row_issues)
                except Exception as e:
                    logger.warning(
                        f"[ValidationRunner] {validator.VALIDATOR_ID} falló en "
                        f"{codigo}:{emo['frase_idx']}:{emo['emocion_idx']}: {e}"
                    )

        for validator in self._discurso_validators:
            try:
                disc_issues = validator.validate(
                    codigo=codigo,
                    emociones=emociones,
                    enunciador=enunciador,
                    enunciatarios=enunciatarios,
                )
                issues.extend(disc_issues)
            except Exception as e:
                logger.warning(
                    f"[ValidationRunner] {validator.VALIDATOR_ID} falló en "
                    f"{codigo}: {e}"
                )

        return issues

    def _load_codigos_con_emociones_caracterizadas(self) -> list[str]:
        """Devuelve códigos de discursos con al menos una emoción caracterizada."""
        rows = self._db.execute(
            """
            SELECT DISTINCT codigo
            FROM emociones
            WHERE caracterizacion_payload IS NOT NULL
            ORDER BY codigo
            """
        ).fetchall()
        return [r["codigo"] for r in rows]

    def _load_emociones_con_caracterizacion(
        self, codigo: str
    ) -> list[dict[str, Any]]:
        """Carga emociones con sus caracterizaciones para un discurso."""
        rows = self._db.execute(
            """
            SELECT
                frase_idx,
                emocion_idx,
                experienciador,
                tipo_emocion,
                modo_existencia,
                caracterizacion_payload
            FROM emociones
            WHERE codigo = ?
              AND caracterizacion_payload IS NOT NULL
            ORDER BY frase_idx, emocion_idx
            """,
            (codigo,),
        ).fetchall()

        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                caract = json.loads(row["caracterizacion_payload"])
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    f"[ValidationRunner] {codigo}: caracterizacion_payload "
                    f"no parseable en ({row['frase_idx']}, {row['emocion_idx']})"
                )
                continue

            result.append({
                "frase_idx": row["frase_idx"],
                "emocion_idx": row["emocion_idx"],
                "experienciador": row["experienciador"] or "",
                "tipo_emocion": row["tipo_emocion"] or "",
                "modo_existencia": row["modo_existencia"] or "",
                "foria": caract.get("foria", ""),
                "dominancia": caract.get("dominancia", ""),
                "intensidad": caract.get("intensidad", ""),
                "tipo_fuente": caract.get("tipo_fuente", ""),
                "fuente": caract.get("fuente", ""),
            })

        return result

    def _load_enunciacion(self, codigo: str) -> tuple[str, list[dict[str, Any]]]:
        """Carga el enunciador y enunciatarios del discurso."""
        row = self._db.execute(
            "SELECT enunciation_payload FROM discursos WHERE codigo = ?",
            (codigo,),
        ).fetchone()

        if row is None or row["enunciation_payload"] is None:
            return "no identificado", []

        try:
            payload = json.loads(row["enunciation_payload"])
        except (json.JSONDecodeError, TypeError):
            return "no identificado", []

        enunciador = payload.get("enunciador", "no identificado") or "no identificado"
        enunciatarios = payload.get("enunciatarios", []) or []

        return enunciador, enunciatarios
