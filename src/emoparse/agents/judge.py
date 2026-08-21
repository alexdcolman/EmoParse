# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.judge
#
#  Agente de validación de caracterización emocional.
#
#  Evalúa la coherencia sustantiva de los campos corregibles del simulacro
#  emocional, con alcance deliberadamente acotado por JuicioSchema.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from typing import Any

import pandas as pd
from pydantic import ValidationError

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.backend.exceptions import BackendError
from emoparse.core.prompts import judge as prompts
from emoparse.core.schemas import (
    JuicioBatchItemSchema,
    JuicioLLMBatchItemSchema,
    ListaJuiciosLLMBatchSchema,
)
from emoparse.genres.base import Genre


class JudgeAgent(BaseBatchAgent[ListaJuiciosLLMBatchSchema]):
    """Agente batch para validación de caracterizaciones emocionales.

    Cada fila representa una emoción ya caracterizada. El agente evalúa si
    la caracterización asignada resulta coherente con el contexto textual y
    con la emoción detectada originalmente.
    """

    NAME = "judge"
    SCHEMA = ListaJuiciosLLMBatchSchema
    OUTPUT_COLUMNS = ("coherente", "issues", "confianza", "sugerencias")
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        heuristicas: str | None = None,
        resumen: str | None = None,
        enunciacion: str | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            titulo: Título del discurso, usado como contexto del prompt.
            tipo_discurso: Clasificación o tipo del discurso.
            heuristicas: Reglas heurísticas para evaluación de coherencia.
                Si None, no se inyectan heurísticas en el system prompt.
            resumen: Resumen global del discurso, como contexto.
            enunciacion: Bloque preformateado con enunciador, enunciatarios,
                auditorio y colectivos de identificación.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como `BATCH_SIZE`.
        """
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._heuristicas = heuristicas
        self._resumen = resumen
        self._enunciacion = enunciacion
        self._genre = genre

        if genre is not None and "judge" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["judge"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks ────────────────────────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            heuristicas=self._heuristicas,
            resumen=self._resumen,
            enunciacion=self._enunciacion,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            prev = str(row.get("ventana_previa", "") or "")
            post = str(row.get("ventana_posterior", "") or "")
            actantes = str(row.get("actantes_texto", "") or "")

            bloque = [
                f"UNIDAD [{i}] (codigo={codigo}):",
            ]
            if prev:
                bloque.append(f"  Contexto previo:\n{prev}")
            bloque.append(f"  FRASE OBJETIVO: {frase}")
            if post:
                bloque.append(f"  Contexto posterior:\n{post}")
            bloque.append(
                "  SIMULACRO A REVISAR:\n"
                f"    Experienciador:       {row.get('experienciador', '')}\n"
                f"    Marca experienciador: {row.get('experienciador_marca', '')}\n"
                f"    Emoción:               {row.get('tipo_emocion', '')}\n"
                f"    Modo:                  {row.get('modo_existencia', '')}\n"
                f"    Fuente:                {row.get('fuente_inferencia', '')}\n"
                f"    Marca fuente:          {row.get('fuente_marca', '')}\n"
                f"    Temporalidad:          {row.get('temporalidad', '')}"
            )
            if actantes:
                bloque.append(f"  ACTANTES:\n{actantes}")
            bloques.append("\n".join(bloque))
        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    @staticmethod
    def _payload_dict(row: pd.Series, key: str) -> dict[str, Any]:
        raw = row.get(key)
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str) or not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _current_correctable_value(cls, row: pd.Series, campo: str) -> Any:
        direct = {
            "experienciador": "experienciador",
            "tipo_emocion": "tipo_emocion",
            "fuente_inferencia": "fuente_inferencia",
            "modo_existencia": "modo_existencia",
            "caracterizacion.temporalidad": "temporalidad",
        }
        if campo in direct:
            value = row.get(direct[campo])
            if value is None:
                return None
            try:
                if pd.isna(value):
                    return None
            except (TypeError, ValueError):
                pass
            return value

        actantes = cls._payload_dict(row, "actantes_payload")
        nested = {
            "actantes.mediador.tipo": ("mediador", "tipo"),
            "actantes.verificador_normativo.tipo": ("verificador_normativo", "tipo"),
            "actantes.verificador_normativo.evaluacion": ("verificador_normativo", "evaluacion"),
            "actantes.verificador_observacional.tipo": ("verificador_observacional", "tipo"),
            "actantes.verificador_observacional.evaluacion": (
                "verificador_observacional",
                "evaluacion",
            ),
            "actantes.operador_modificacion.funcion": ("operador_modificacion", "funcion"),
            "actantes.polaridad.tipo": ("polaridad", "tipo"),
        }
        path = nested.get(campo)
        if path is None:
            return None
        node = actantes.get(path[0])
        if not isinstance(node, dict):
            return None
        return node.get(path[1])

    @staticmethod
    def _same_correctable_value(actual: Any, suggested: Any) -> bool:
        if actual is None or suggested is None:
            return False
        if isinstance(actual, str) and isinstance(suggested, str):
            return actual.strip() == suggested.strip()
        return actual == suggested

    def _quality_control_item(
        self,
        item: JuicioLLMBatchItemSchema,
        row: pd.Series,
    ) -> JuicioBatchItemSchema:
        """Canonicaliza la salida bruta sin reinterpretar el juicio del LLM.

        La recepción LLM permite temporalmente repeticiones del mismo campo para
        poder compararlas con el valor upstream. Se eliminan solo no-ops exactos
        y duplicados exactos. Si después quedan dos correcciones materiales
        distintas para un mismo campo, el contrato canónico las rechaza.
        """
        materiales: list[dict[str, Any]] = []
        vistos_exactos: set[tuple[str, str]] = set()

        for sugerencia in item.juicio.sugerencias:
            actual = self._current_correctable_value(row, sugerencia.campo)
            if self._same_correctable_value(actual, sugerencia.valor_sugerido):
                continue

            dumped = sugerencia.model_dump()
            clave = (
                sugerencia.campo,
                json.dumps(
                    sugerencia.valor_sugerido,
                    ensure_ascii=False,
                    sort_keys=True,
                    default=str,
                ),
            )
            if clave in vistos_exactos:
                continue
            vistos_exactos.add(clave)
            materiales.append(dumped)

        coherente = item.juicio.coherente
        issues = item.juicio.issues
        if item.juicio.sugerencias and not materiales:
            # Si había sugerencias pero todas desaparecieron por ser no-ops o
            # duplicados de no-ops, ya no existe ninguna corrección material.
            # Un false+[] originalmente emitido por el LLM NO se repara aquí:
            # el contrato canónico conserva ese caso como error estructural.
            coherente = True
            issues = "no identificado"

        payload = {
            "unit_idx": item.unit_idx,
            "juicio": {
                "coherente": coherente,
                "sugerencias": materiales,
                "issues": issues,
                "confianza": item.juicio.confianza,
            },
        }
        try:
            return JuicioBatchItemSchema.model_validate(payload)
        except ValidationError as exc:
            raise BackendError(
                "judge produjo correcciones materiales incompatibles tras "
                f"normalización determinista: {exc}"
            ) from exc

    def _map_item_to_columns(
        self,
        item: JuicioBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        j = item.juicio
        sugerencias: list[dict[str, Any]] = []
        for sugerencia in j.sugerencias:
            actual = self._current_correctable_value(row, sugerencia.campo)
            if self._same_correctable_value(actual, sugerencia.valor_sugerido):
                continue
            sugerencias.append(sugerencia.model_dump())

        # Una salida incoherente sostenida únicamente por correcciones que no
        # cambian ningún valor no contiene una corrección material. Se normaliza
        # a coherente sin pedir otra inferencia al LLM.
        if not j.coherente and not sugerencias:
            return {
                "coherente": True,
                "issues": "no identificado",
                "confianza": j.confianza,
                "sugerencias": [],
            }

        return {
            "coherente": j.coherente,
            "issues": j.issues,
            "confianza": j.confianza,
            "sugerencias": sugerencias,
        }
