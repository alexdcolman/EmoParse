# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.actants
#
#  Agente batch para el análisis de la configuración actancial de
#  emociones detectadas: mediador, verificadores y operador de
#  modificación.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

import pandas as pd

from emoparse.agents.base import BaseBatchAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import actants as prompts
from emoparse.core.schemas import (
    ActantesBatchItemSchema,
    ActantesEmocionSchema,
    ListaActantesBatchSchema,
    MediadorSchema,
    OperadorModificacionSchema,
    PolaridadSchema,
    VerificadorNormativoSchema,
    VerificadorObservacionalSchema,
)
from emoparse.genres.base import Genre


#: Identificadores canónicos de los cuatro componentes actanciales.
ACTANTS_COMPONENTS: tuple[str, ...] = (
    "mediador",
    "verificador_normativo",
    "verificador_observacional",
    "operador_modificacion",
    "polaridad",
)


#: Mensaje fijo asignado a los componentes deshabilitados por
#: configuración. Permite distinguir, downstream, los componentes
#: marcados como ausentes por el modelo de los que nunca fueron
#: solicitados.
_DISABLED_JUSTIFICATION: str = "componente deshabilitado por configuración"


class ActantsAgent(BaseBatchAgent[ListaActantesBatchSchema]):
    """Agente batch que analiza la configuración actancial de emociones.

    Por cada emoción del batch, el agente devuelve un
    `ActantesEmocionSchema` con los componentes del dispositivo
    analítico:

      - `mediador`: vehículo entre la fuente y el experienciador.
      - `verificador_normativo`: evaluación cultural/normativa.
      - `verificador_observacional`: evaluación de autenticidad o de
        veracidad del desencadenante.
      - `operador_modificacion`: manipulación actancial sobre la
        emoción del experienciador.
      - `polaridad`: afirmación o negación de la emoción y, si está
        negada, la modalidad de la negación.

    El parámetro `enabled_components` controla qué componentes se le
    piden efectivamente al LLM. Los componentes excluidos se completan
    con un placeholder determinístico (`presente=false`, tipo
    `"ausente"`, evaluación `"sin_evaluacion"` cuando aplica). Esto
    permite desactivar componentes ruidosos o costosos sin alterar la
    forma del payload almacenado.
    """

    NAME = "actants"
    SCHEMA = ListaActantesBatchSchema
    OUTPUT_COLUMNS = (
        # Mediador
        "mediador_presente",
        "mediador_descripcion",
        "mediador_tipo",
        "mediador_justificacion",
        # Verificador normativo
        "verificador_normativo_presente",
        "verificador_normativo_descripcion",
        "verificador_normativo_tipo",
        "verificador_normativo_evaluacion",
        "verificador_normativo_justificacion",
        # Verificador observacional
        "verificador_observacional_presente",
        "verificador_observacional_descripcion",
        "verificador_observacional_tipo",
        "verificador_observacional_evaluacion",
        "verificador_observacional_justificacion",
        # Operador de modificación
        "operador_modificacion_presente",
        "operador_modificacion_descripcion",
        "operador_modificacion_funcion",
        "operador_modificacion_justificacion",
        # Polaridad
        "polaridad_negada",
        "polaridad_tipo",
        "polaridad_justificacion",
    )
    BATCH_SIZE = 5

    def __init__(
        self,
        backend: LLMBackend,
        titulo: str = "",
        tipo_discurso: str = "",
        heuristicas: str | None = None,
        enabled_components: tuple[str, ...] = ACTANTS_COMPONENTS,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para la generación estructurada.
            titulo: Título del discurso, usado como contexto.
            tipo_discurso: Tipo o clasificación del discurso.
            heuristicas: Reglas heurísticas para el análisis actancial. Si
                None, no se inyectan heurísticas en el system prompt.
            enabled_components: Subconjunto de componentes actanciales
                solicitados al LLM en este run. Los no incluidos se
                completan con un placeholder determinístico antes de
                persistir.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración opcional de género discursivo. Puede
                ajustar parámetros como `BATCH_SIZE`.
        """
        self._titulo = titulo
        self._tipo_discurso = tipo_discurso
        self._heuristicas = heuristicas
        self._genre = genre

        unknown = set(enabled_components) - set(ACTANTS_COMPONENTS)
        if unknown:
            raise ValueError(
                f"Componentes actanciales desconocidos: {sorted(unknown)}. "
                f"Válidos: {ACTANTS_COMPONENTS}"
            )
        if not enabled_components:
            raise ValueError(
                "Al menos un componente actancial debe estar habilitado."
            )
        self._enabled: tuple[str, ...] = tuple(
            c for c in ACTANTS_COMPONENTS if c in enabled_components
        )

        if genre is not None and "actants" in genre.batch_size:
            self.BATCH_SIZE = genre.batch_size["actants"]  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseBatchAgent ──────────────────────────────────────────────

    def _build_system(self) -> str:
        return prompts.render_system(
            titulo=self._titulo,
            tipo_discurso=self._tipo_discurso,
            enabled_components=self._enabled,
            heuristicas=self._heuristicas,
        )

    def _build_user(self, batch: pd.DataFrame) -> str:
        bloques: list[str] = []
        for i, (_, row) in enumerate(batch.iterrows()):
            codigo = str(row.get("codigo", ""))
            frase = str(row.get("frase", ""))
            experienciador = str(row.get("experienciador", ""))
            tipo_emocion = str(row.get("tipo_emocion", ""))
            modo = str(row.get("modo_existencia", ""))
            tipo_conf = str(row.get("tipo_configuracion", "") or "")

            bloque = (
                f"EMOCIÓN [{i}] (codigo={codigo}):\n"
                f"  Experienciador:    {experienciador}\n"
                f"  Tipo emoción:      {tipo_emocion}\n"
                f"  Modo existencia:   {modo}\n"
            )
            if tipo_conf:
                bloque += f"  Tipo configuración: {tipo_conf}\n"
            bloque += f"  Frase de origen:   {frase}"
            bloques.append(bloque)

        unidades_block = "\n\n".join(bloques)
        return prompts.render_user(unidades_block=unidades_block)

    def _map_item_to_columns(
        self,
        item: ActantesBatchItemSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        a = self._apply_disabled_placeholders(item.actantes)
        return {
            # Mediador
            "mediador_presente": a.mediador.presente,
            "mediador_descripcion": a.mediador.descripcion,
            "mediador_tipo": a.mediador.tipo,
            "mediador_justificacion": a.mediador.justificacion,
            # Verificador normativo
            "verificador_normativo_presente": a.verificador_normativo.presente,
            "verificador_normativo_descripcion": a.verificador_normativo.descripcion,
            "verificador_normativo_tipo": a.verificador_normativo.tipo,
            "verificador_normativo_evaluacion": a.verificador_normativo.evaluacion,
            "verificador_normativo_justificacion": a.verificador_normativo.justificacion,
            # Verificador observacional
            "verificador_observacional_presente": a.verificador_observacional.presente,
            "verificador_observacional_descripcion": a.verificador_observacional.descripcion,
            "verificador_observacional_tipo": a.verificador_observacional.tipo,
            "verificador_observacional_evaluacion": a.verificador_observacional.evaluacion,
            "verificador_observacional_justificacion": a.verificador_observacional.justificacion,
            # Operador de modificación
            "operador_modificacion_presente": a.operador_modificacion.presente,
            "operador_modificacion_descripcion": a.operador_modificacion.descripcion,
            "operador_modificacion_funcion": a.operador_modificacion.funcion,
            "operador_modificacion_justificacion": a.operador_modificacion.justificacion,
            # Polaridad
            "polaridad_negada": a.polaridad.negada,
            "polaridad_tipo": a.polaridad.tipo,
            "polaridad_justificacion": a.polaridad.justificacion,
        }

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _apply_disabled_placeholders(
        self,
        actantes: ActantesEmocionSchema,
    ) -> ActantesEmocionSchema:
        """Sobrescribe los componentes deshabilitados con un placeholder.

        Aun cuando el system prompt instruye al modelo a marcar como
        ausentes los componentes deshabilitados, se fuerza acá el
        valor canónico para garantizar consistencia downstream
        independientemente del comportamiento del backend.
        """
        if set(self._enabled) == set(ACTANTS_COMPONENTS):
            return actantes
        return ActantesEmocionSchema(
            mediador=(
                actantes.mediador
                if "mediador" in self._enabled
                else _disabled_mediador()
            ),
            verificador_normativo=(
                actantes.verificador_normativo
                if "verificador_normativo" in self._enabled
                else _disabled_verificador_normativo()
            ),
            verificador_observacional=(
                actantes.verificador_observacional
                if "verificador_observacional" in self._enabled
                else _disabled_verificador_observacional()
            ),
            operador_modificacion=(
                actantes.operador_modificacion
                if "operador_modificacion" in self._enabled
                else _disabled_operador_modificacion()
            ),
            polaridad=(
                actantes.polaridad
                if "polaridad" in self._enabled
                else _disabled_polaridad()
            ),
        )


# ══════════════════════════════════════════════════════════════════════════════
#  Placeholders determinísticos para componentes deshabilitados
# ══════════════════════════════════════════════════════════════════════════════


def _disabled_mediador() -> MediadorSchema:
    return MediadorSchema(
        presente=False,
        descripcion=None,
        tipo="ausente",
        justificacion=_DISABLED_JUSTIFICATION,
    )


def _disabled_verificador_normativo() -> VerificadorNormativoSchema:
    return VerificadorNormativoSchema(
        presente=False,
        descripcion=None,
        tipo="ausente",
        evaluacion="sin_evaluacion",
        justificacion=_DISABLED_JUSTIFICATION,
    )


def _disabled_verificador_observacional() -> VerificadorObservacionalSchema:
    return VerificadorObservacionalSchema(
        presente=False,
        descripcion=None,
        tipo="ausente",
        evaluacion="sin_evaluacion",
        justificacion=_DISABLED_JUSTIFICATION,
    )


def _disabled_operador_modificacion() -> OperadorModificacionSchema:
    return OperadorModificacionSchema(
        presente=False,
        descripcion=None,
        funcion="ausente",
        justificacion=_DISABLED_JUSTIFICATION,
    )


def _disabled_polaridad() -> PolaridadSchema:
    return PolaridadSchema(
        negada=False,
        tipo="afirmada",
        justificacion=_DISABLED_JUSTIFICATION,
    )
