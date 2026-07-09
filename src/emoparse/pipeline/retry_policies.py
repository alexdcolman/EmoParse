# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.retry_policies
#
#  Políticas declarativas de reprocesamiento.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from emoparse.config.models import RunConfig
from emoparse.pipeline.dag import EMOPARSE_DAG
from emoparse.storage.db import Database


# ══════════════════════════════════════════════════════════════════════════════
#  Stages soportadas por policies
# ══════════════════════════════════════════════════════════════════════════════

#: Tipo: tabla SQL + clave del prefijo de columna.
#: La clave `error_col` es el nombre completo de la columna de error.
#: La clave `payload_col` el nombre de la columna de payload.
#: Para frases/emociones también se necesita la PK para identificar filas.
_STAGE_REGISTRY: dict[str, dict[str, Any]] = {
    "summarizer": {
        "table": "discursos",
        "payload_col": "summarizer_payload",
        "error_col": "summarizer_error",
        "version_col": "summarizer_version",
        "pk": ("codigo",),
    },
    "metadata": {
        "table": "discursos",
        "payload_col": "metadata_payload",
        "error_col": "metadata_error",
        "version_col": "metadata_version",
        "pk": ("codigo",),
    },
    "enunciation": {
        "table": "discursos",
        "payload_col": "enunciation_payload",
        "error_col": "enunciation_error",
        "version_col": "enunciation_version",
        "pk": ("codigo",),
    },
    "actors": {
        "table": "frases",
        "payload_col": "actores_payload",
        "error_col": "actores_error",
        "version_col": "actores_version",
        "pk": ("codigo", "unit_idx"),
    },
    "emotions": {
        "table": "frases",
        "payload_col": "emociones_payload",
        "error_col": "emociones_error",
        "version_col": "emociones_version",
        "pk": ("codigo", "unit_idx"),
    },
    "emotions_pass2": {
        "table": "frases",
        "payload_col": "emociones_pass2_payload",
        "error_col": "emociones_pass2_error",
        "version_col": "emociones_pass2_version",
        "pk": ("codigo", "unit_idx"),
    },
    "characterizer": {
        "table": "emociones",
        "payload_col": "caracterizacion_payload",
        "error_col": "caracterizacion_error",
        "version_col": "caracterizacion_version",
        "pk": ("codigo", "frase_idx", "emocion_idx"),
    },
    "actants": {
        "table": "emociones",
        "payload_col": "actantes_payload",
        "error_col": "actantes_error",
        "version_col": "actantes_version",
        "pk": ("codigo", "frase_idx", "emocion_idx"),
    },
}


SUPPORTED_STAGES: tuple[str, ...] = tuple(_STAGE_REGISTRY)


# ══════════════════════════════════════════════════════════════════════════════
#  Modelos Pydantic
# ══════════════════════════════════════════════════════════════════════════════

FilterOp = Literal["eq", "ne", "in", "contains", "is_null", "is_not_null"]

_OPS_NEED_VALUE: frozenset[str] = frozenset({"eq", "ne", "in", "contains"})


class RetryPolicyFilter(BaseModel):
    """Filtro declarativo sobre el payload JSON de una stage.

    Ops:
      - eq: igual
      - ne: distinto
      - in: pertenece a value (lista)
      - contains: substring (case-sensitive; el JSON LIKE de SQLite es CS)
      - is_null: el campo está ausente o es JSON null
      - is_not_null: el campo está presente y no es JSON null
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(
        description=(
            "Path con notación punto sobre el payload JSON de la stage."
        ),
    )
    op: FilterOp = Field(default="eq")
    value: Any = Field(
        default=None,
        description="Valor a comparar (no aplica para is_null/is_not_null).",
    )

    @field_validator("field")
    @classmethod
    def _no_leading_dot(cls, v: str) -> str:
        if not v or v.startswith(".") or v.endswith("."):
            raise ValueError(
                f"field inválido: '{v}'. Debe ser un path con notación "
                f"punto sin punto inicial/final."
            )
        return v

    @model_validator(mode="after")
    def _check_value_present(self) -> RetryPolicyFilter:
        if self.op in _OPS_NEED_VALUE and self.value is None:
            raise ValueError(
                f"Op '{self.op}' requiere 'value'. "
                f"Para chequear NULL, usá 'is_null' / 'is_not_null'."
            )
        if self.op == "in" and not isinstance(self.value, list):
            raise ValueError(
                f"Op 'in' requiere 'value' lista, got {type(self.value).__name__}."
            )
        return self


class RetryPolicy(BaseModel):
    """Policy de reprocesamiento para una stage.

    Atributos:
        stage: Nombre de la stage a reprocesar.
        target: Qué filas se ven afectadas:
            "failed" → solo las que tienen error (default).
            "completed" → las completadas.
            "all → ambas.
        filters: Lista de filtros adicionales. Se aplican en AND.
        override_model: Si se pasa, en el RunConfig devuelto por el
            applier, la stage se asigna a este alias en lugar del original.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str
    target: Literal["failed", "completed", "all"] = "failed"
    filters: list[RetryPolicyFilter] = Field(default_factory=list)
    override_model: str | None = None

    @field_validator("stage")
    @classmethod
    def _stage_supported(cls, v: str) -> str:
        if v not in SUPPORTED_STAGES:
            raise ValueError(
                f"Stage '{v}' no soportada por retry policies. "
                f"Soportadas: {SUPPORTED_STAGES}. "
                f"(judge y explode_emotions se excluyen a propósito.)"
            )
        # Defensa adicional: que el nombre exista en el DAG canónico.
        if v not in EMOPARSE_DAG.names():
            raise ValueError(
                f"Stage '{v}' no aparece en EMOPARSE_DAG. "
                f"Esto es un bug interno: SUPPORTED_STAGES y el DAG "
                f"deberían estar sincronizados."
            )
        return v


class RetryPolicyFile(BaseModel):
    """Contenido del archivo YAML de policies."""

    model_config = ConfigDict(extra="forbid")

    policies: list[RetryPolicy] = Field(default_factory=list)


def load_policy_file(path: Path | str) -> RetryPolicyFile:
    """Carga un archivo YAML de policies.

    El archivo debe tener la forma::

        policies:
          - stage: emotions
            target: failed
            override_model: qwen3-30b-moe
          - stage: metadata
            target: completed
            filters:
              - field: tipo_discurso
                op: eq
                value: "no identificado"
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Archivo de policy no encontrado: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"YAML de policies debe ser un mapping top-level con "
            f"clave 'policies'. Got: {type(data).__name__}."
        )
    return RetryPolicyFile.model_validate(data)


# ══════════════════════════════════════════════════════════════════════════════
#  RetryPolicyApplier
# ══════════════════════════════════════════════════════════════════════════════

class PolicyApplicationResult(BaseModel):
    """Resultado de aplicar una policy."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    rows_marked_pending: int
    override_model: str | None = None


class RetryPolicyApplier:
    """Aplica un RetryPolicyFile contra una DB."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def apply(
        self,
        policy_file: RetryPolicyFile,
        base_config: RunConfig | None = None,
    ) -> tuple[list[PolicyApplicationResult], RunConfig | None]:
        """Aplica todas las policies y devuelve resultados + config overrideado."""
        results: list[PolicyApplicationResult] = []
        new_config = (
            base_config.model_copy(deep=True) if base_config is not None else None
        )

        for policy in policy_file.policies:
            result = self._apply_one(policy)
            results.append(result)

            if policy.override_model is not None and new_config is not None:
                self._apply_override(new_config, policy)

        return results, new_config

    # ── Aplicación de una policy ─────────────────────────────────────────────

    def _apply_one(self, policy: RetryPolicy) -> PolicyApplicationResult:
        """Selecciona filas, marca pending y retorna conteo."""
        reg = _STAGE_REGISTRY[policy.stage]
        table: str = reg["table"]
        payload_col: str = reg["payload_col"]
        error_col: str = reg["error_col"]
        version_col: str = reg["version_col"]
        pk_cols: tuple[str, ...] = reg["pk"]

        target_clauses, target_params = self._where_for_target(
            policy.target, payload_col, error_col
        )

        filter_clauses, filter_params = self._where_for_filters(
            policy.filters, payload_col
        )

        if (
            policy.target == "failed"
            and filter_clauses
            and not _filters_only_payload_null(policy.filters)
        ):
            logger.warning(
                "[RetryPolicy] Policy sobre '{}' usa target='failed' + filtros "
                "sobre el payload, pero los failed tienen payload=NULL. "
                "La policy probablemente seleccione 0 filas. "
                "Usá target='all' o target='completed' si querés filtrar "
                "por contenido del payload.",
                policy.stage,
            )

        where_clauses = target_clauses + filter_clauses
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        all_params = target_params + filter_params

        pk_select = ", ".join(pk_cols)
        select_sql = f"SELECT {pk_select} FROM {table} WHERE {where_sql}"
        rows = self._db.execute(select_sql, tuple(all_params)).fetchall()
        n = len(rows)

        if n == 0:
            logger.info(
                "[RetryPolicy] Policy sobre '{}' (target={}): 0 filas afectadas.",
                policy.stage,
                policy.target,
            )
            return PolicyApplicationResult(
                stage=policy.stage,
                rows_marked_pending=0,
                override_model=policy.override_model,
            )

        update_sql = (
            f"UPDATE {table} SET "
            f"{payload_col} = NULL, "
            f"{version_col} = NULL, "
            f"{error_col}   = NULL "
            f"WHERE {where_sql}"
        )
        with self._db.transaction() as cur:
            cur.execute(update_sql, tuple(all_params))
            affected = cur.rowcount

        logger.info(
            "[RetryPolicy] Policy sobre '{}' (target={}): {} fila(s) "
            "marcadas pending.{}",
            policy.stage,
            policy.target,
            affected,
            f" Override: {policy.override_model}." if policy.override_model else "",
        )
        return PolicyApplicationResult(
            stage=policy.stage,
            rows_marked_pending=affected,
            override_model=policy.override_model,
        )

    # ── Construcción de WHERE clauses ────────────────────────────────────────

    @staticmethod
    def _where_for_target(
        target: str,
        payload_col: str,
        error_col: str,
    ) -> tuple[list[str], list[Any]]:
        """WHERE clauses para target."""
        if target == "failed":
            return [f"{error_col} IS NOT NULL"], []
        if target == "completed":
            return [f"{payload_col} IS NOT NULL"], []
        if target == "all":
            return [
                f"({error_col} IS NOT NULL OR {payload_col} IS NOT NULL)"
            ], []
        raise ValueError(f"target inválido: {target}")

    @staticmethod
    def _where_for_filters(
        filters: list[RetryPolicyFilter],
        payload_col: str,
    ) -> tuple[list[str], list[Any]]:
        """Convierte filtros declarativos a WHERE clauses SQL.

        Cada filtro se traduce a un `json_extract(<payload_col>, '$.path')`
        comparado con el value según la op. Las ops se materializan así:
          eq: json_extract(...) = ?
          ne: json_extract(...) != ?
          in: json_extract(...) IN (?, ?, ...)
          contains: json_extract(...) LIKE '%value%' (escape básico)
          is_null: json_extract(...) IS NULL
          is_not_null: json_extract(...) IS NOT NULL
        """
        clauses: list[str] = []
        params: list[Any] = []
        for f in filters:
            json_path = "$." + f.field
            extracted = f"json_extract({payload_col}, '{json_path}')"
            if f.op == "eq":
                clauses.append(f"{extracted} = ?")
                params.append(f.value)
            elif f.op == "ne":
                clauses.append(f"{extracted} != ?")
                params.append(f.value)
            elif f.op == "in":
                placeholders = ", ".join(["?"] * len(f.value))
                clauses.append(f"{extracted} IN ({placeholders})")
                params.extend(f.value)
            elif f.op == "contains":
                # SQLite por default no escapa; se utiliza un ESCAPE clause.
                escaped = (
                    str(f.value)
                    .replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                clauses.append(f"{extracted} LIKE ? ESCAPE '\\'")
                params.append(f"%{escaped}%")
            elif f.op == "is_null":
                clauses.append(f"{extracted} IS NULL")
            elif f.op == "is_not_null":
                clauses.append(f"{extracted} IS NOT NULL")
            else:
                raise ValueError(f"op desconocida: {f.op}")
        return clauses, params

    # ── Override del config ──────────────────────────────────────────────────

    @staticmethod
    def _apply_override(config: RunConfig, policy: RetryPolicy) -> None:
        """Setea override_model en config.pipeline.stages.

        Validaciones:
          - El alias debe existir en `config.models`.
          - La stage debe estar (o se agrega) en `config.pipeline.stages`.

        Si la stage no estaba en pipeline.stages, se agrega.
        """
        alias = policy.override_model
        assert alias is not None
        if alias not in config.models:
            raise ValueError(
                f"override_model='{alias}' para stage '{policy.stage}' "
                f"no está definido en config.models. Disponibles: "
                f"{sorted(config.models)}"
            )
        config.pipeline.stages[policy.stage] = alias
        logger.debug(
            "[RetryPolicy] Override aplicado: pipeline.stages['{}'] = '{}'",
            policy.stage,
            alias,
        )


# ── Helpers privados ────────────────────────────────────────────────────────

def _filters_only_payload_null(filters: list[RetryPolicyFilter]) -> bool:
    """True si todos los filtros usan is_null sobre el payload."""
    return all(f.op == "is_null" for f in filters)
