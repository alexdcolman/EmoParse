# ══════════════════════════════════════════════════════════════════════════════
#  tests/unit/test_pipeline_contracts.py
#
#  Tests de Pandera DataFrameModel contracts entre stages.
#
#  Cubre:
#  1. Cada contract acepta DFs válidos.
#  2. Cada contract rechaza DFs con columnas faltantes.
#  3. Cada contract rechaza DFs con nulls en columnas non-nullable.
#  4. validate_contracts=False desactiva la validación en Stage.
#  5. Un test de integración por stage que verifica que el contract
#     está activo (ver sección "contract activo en stage").
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pandera.pandas as pa
import pytest

from emoparse.pipeline.contracts import (
    DiscursoInputContract,
    EmocionExplodedContract,
    FraseConActoresContract,
    FraseConEmocionesContract,
    FraseInputContract,
    validate,
)


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _df_discurso_valido() -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": "D001", "contenido": "Texto del discurso."},
        {"codigo": "D002", "contenido": "Otro texto.", "titulo": "Título opcional"},
    ])


def _df_frase_valido() -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": "D001", "unit_idx": 0, "frase": "Primera frase."},
        {"codigo": "D001", "unit_idx": 1, "frase": "Segunda frase."},
    ])


def _df_frase_actores_valido() -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": "D001", "unit_idx": 0, "frase": "Frase.", "actores": '[{"nombre": "X"}]'},
        {"codigo": "D001", "unit_idx": 1, "frase": "Otra frase.", "actores": None},
    ])


def _df_frase_emociones_valido() -> pd.DataFrame:
    return pd.DataFrame([
        {"codigo": "D001", "unit_idx": 0, "frase": "Frase.", "emociones": '[{"tipo": "alegria"}]'},
        {"codigo": "D001", "unit_idx": 1, "frase": "Otra.", "emociones": None},
    ])


def _df_emocion_valido() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "codigo": "D001",
            "frase_idx": 0,
            "emocion_idx": 0,
            "experienciador": "hablante",
            "tipo_emocion": "alegria",
            "modo_existencia": "actualizado",
        },
    ])


# ──────────────────────────────────────────────────────────────────────────────
#  DiscursoInputContract
# ──────────────────────────────────────────────────────────────────────────────


class TestDiscursoInputContract:
    def test_valido_minimo(self) -> None:
        df = _df_discurso_valido()
        result = validate(DiscursoInputContract, df)
        assert len(result) == 2

    def test_acepta_columnas_extra(self) -> None:
        df = _df_discurso_valido().assign(fecha="2024-01-01")
        result = validate(DiscursoInputContract, df)
        assert "fecha" in result.columns

    def test_falta_codigo(self) -> None:
        df = _df_discurso_valido().drop(columns=["codigo"])
        with pytest.raises(pa.errors.SchemaError):
            validate(DiscursoInputContract, df)

    def test_falta_contenido(self) -> None:
        df = _df_discurso_valido().drop(columns=["contenido"])
        with pytest.raises(pa.errors.SchemaError):
            validate(DiscursoInputContract, df)

    def test_codigo_null(self) -> None:
        df = _df_discurso_valido().copy()
        df.loc[0, "codigo"] = None
        with pytest.raises(pa.errors.SchemaError):
            validate(DiscursoInputContract, df)

    def test_contenido_null(self) -> None:
        df = _df_discurso_valido().copy()
        df.loc[0, "contenido"] = None
        with pytest.raises(pa.errors.SchemaError):
            validate(DiscursoInputContract, df)


# ──────────────────────────────────────────────────────────────────────────────
#  FraseInputContract
# ──────────────────────────────────────────────────────────────────────────────


class TestFraseInputContract:
    def test_valido(self) -> None:
        df = _df_frase_valido()
        result = validate(FraseInputContract, df)
        assert len(result) == 2

    def test_falta_unit_idx(self) -> None:
        df = _df_frase_valido().drop(columns=["unit_idx"])
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseInputContract, df)

    def test_falta_frase(self) -> None:
        df = _df_frase_valido().drop(columns=["frase"])
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseInputContract, df)

    def test_unit_idx_negativo(self) -> None:
        df = _df_frase_valido().copy()
        df.loc[0, "unit_idx"] = -1
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseInputContract, df)

    def test_frase_null(self) -> None:
        df = _df_frase_valido().copy()
        df.loc[0, "frase"] = None
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseInputContract, df)

    def test_acepta_columnas_extra(self) -> None:
        df = _df_frase_valido().assign(extra="x")
        result = validate(FraseInputContract, df)
        assert "extra" in result.columns


# ──────────────────────────────────────────────────────────────────────────────
#  FraseConActoresContract
# ──────────────────────────────────────────────────────────────────────────────


class TestFraseConActoresContract:
    def test_valido_actores_none(self) -> None:
        df = _df_frase_actores_valido()
        result = validate(FraseConActoresContract, df)
        assert len(result) == 2

    def test_falta_actores(self) -> None:
        df = _df_frase_valido()  # sin columna actores
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseConActoresContract, df)

    def test_actores_puede_ser_null(self) -> None:
        df = _df_frase_actores_valido().copy()
        df["actores"] = None
        result = validate(FraseConActoresContract, df)
        assert result is not None

    def test_falta_frase(self) -> None:
        df = _df_frase_actores_valido().drop(columns=["frase"])
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseConActoresContract, df)


# ──────────────────────────────────────────────────────────────────────────────
#  FraseConEmocionesContract
# ──────────────────────────────────────────────────────────────────────────────


class TestFraseConEmocionesContract:
    def test_valido_emociones_none(self) -> None:
        df = _df_frase_emociones_valido()
        result = validate(FraseConEmocionesContract, df)
        assert len(result) == 2

    def test_falta_emociones(self) -> None:
        df = _df_frase_valido()  # sin columna emociones
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseConEmocionesContract, df)

    def test_emociones_puede_ser_null(self) -> None:
        df = _df_frase_emociones_valido().copy()
        df["emociones"] = None
        result = validate(FraseConEmocionesContract, df)
        assert result is not None

    def test_unit_idx_negativo(self) -> None:
        df = _df_frase_emociones_valido().copy()
        df.loc[0, "unit_idx"] = -5
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseConEmocionesContract, df)


# ──────────────────────────────────────────────────────────────────────────────
#  EmocionExplodedContract
# ──────────────────────────────────────────────────────────────────────────────


class TestEmocionExplodedContract:
    def test_valido(self) -> None:
        df = _df_emocion_valido()
        result = validate(EmocionExplodedContract, df)
        assert len(result) == 1

    def test_falta_frase_idx(self) -> None:
        df = _df_emocion_valido().drop(columns=["frase_idx"])
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_falta_emocion_idx(self) -> None:
        df = _df_emocion_valido().drop(columns=["emocion_idx"])
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_falta_experienciador(self) -> None:
        df = _df_emocion_valido().drop(columns=["experienciador"])
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_falta_tipo_emocion(self) -> None:
        df = _df_emocion_valido().drop(columns=["tipo_emocion"])
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_falta_modo_existencia(self) -> None:
        df = _df_emocion_valido().drop(columns=["modo_existencia"])
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_frase_idx_negativo(self) -> None:
        df = _df_emocion_valido().copy()
        df.loc[0, "frase_idx"] = -1
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_emocion_idx_negativo(self) -> None:
        df = _df_emocion_valido().copy()
        df.loc[0, "emocion_idx"] = -1
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_experienciador_null(self) -> None:
        df = _df_emocion_valido().copy()
        df.loc[0, "experienciador"] = None
        with pytest.raises(pa.errors.SchemaError):
            validate(EmocionExplodedContract, df)

    def test_acepta_columnas_extra(self) -> None:
        df = _df_emocion_valido().assign(frase="Texto", foria="euforia")
        result = validate(EmocionExplodedContract, df)
        assert "foria" in result.columns


# ──────────────────────────────────────────────────────────────────────────────
#  validate() helper
# ──────────────────────────────────────────────────────────────────────────────


class TestValidateHelper:
    def test_devuelve_df_original(self) -> None:
        df = _df_frase_valido()
        result = validate(FraseInputContract, df)
        # Misma referencia de datos (no copia transformada)
        assert list(result.columns) == list(df.columns)
        assert len(result) == len(df)

    def test_lazy_false_default(self) -> None:
        """Con lazy=False (default), falla en primer error sin acumular."""
        df = _df_frase_valido().drop(columns=["frase", "unit_idx"])
        with pytest.raises(pa.errors.SchemaError):
            validate(FraseInputContract, df, lazy=False)

    def test_lazy_true_acumula(self) -> None:
        """Con lazy=True, la excepción es SchemaErrors (plural)."""
        df = _df_frase_valido().drop(columns=["frase", "unit_idx"])
        with pytest.raises((pa.errors.SchemaError, pa.errors.SchemaErrors)):
            validate(FraseInputContract, df, lazy=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Contract activo en stages: validate_contracts flag.
# ──────────────────────────────────────────────────────────────────────────────


class _MinimalStage:
    """Stub mínimo para testear Stage._validate sin instanciar pipeline."""

    NAME = "test_stage"

    def __init__(self, validate_contracts: bool = True) -> None:
        self.validate_contracts = validate_contracts

    def _validate(
        self,
        contract: type[pa.DataFrameModel],
        df: pd.DataFrame,
        label: str = "",
    ) -> pd.DataFrame:
        if not self.validate_contracts:
            return df
        try:
            return validate(contract, df, lazy=False)
        except pa.errors.SchemaError as e:
            raise pa.errors.SchemaError(
                schema=e.schema,
                data=e.data,
                message=(
                    f"[Stage:{self.NAME}] Contrato {contract.__name__}"
                    + (f" ({label})" if label else "")
                    + f" violado: {e.args[0]}"
                ),
            ) from e


class TestValidateContractsFlag:
    def test_activo_por_defecto_lanza_en_df_invalido(self) -> None:
        stage = _MinimalStage(validate_contracts=True)
        df_invalido = pd.DataFrame([{"codigo": "D001"}])  # falta contenido
        with pytest.raises(pa.errors.SchemaError):
            stage._validate(DiscursoInputContract, df_invalido)

    def test_activo_no_lanza_en_df_valido(self) -> None:
        stage = _MinimalStage(validate_contracts=True)
        df = _df_discurso_valido()
        result = stage._validate(DiscursoInputContract, df)
        assert len(result) == len(df)

    def test_desactivado_no_lanza_aunque_df_invalido(self) -> None:
        stage = _MinimalStage(validate_contracts=False)
        df_invalido = pd.DataFrame([{"codigo": "D001"}])  # falta contenido
        result = stage._validate(DiscursoInputContract, df_invalido)
        assert result is df_invalido  # devuelve sin tocar

    def test_mensaje_error_incluye_nombre_contrato(self) -> None:
        stage = _MinimalStage(validate_contracts=True)
        df_invalido = pd.DataFrame([{"codigo": "D001"}])
        with pytest.raises(pa.errors.SchemaError, match="DiscursoInputContract"):
            stage._validate(DiscursoInputContract, df_invalido, label="entrada")

    def test_mensaje_error_incluye_label(self) -> None:
        stage = _MinimalStage(validate_contracts=True)
        df_invalido = pd.DataFrame([{"codigo": "D001"}])
        with pytest.raises(pa.errors.SchemaError, match="entrada"):
            stage._validate(DiscursoInputContract, df_invalido, label="entrada")


# ──────────────────────────────────────────────────────────────────────────────
#  Contract activo en Stage.run_pending (per-stage, 1 test cada uno).
# ──────────────────────────────────────────────────────────────────────────────


class TestContractActivoEnStages:
    """Un test por stage verifica que el contrato está activo en run_pending."""

    def test_discurso_stage_contract_activo(self) -> None:
        """_DiscursoStage (SummarizerStage) lanza SchemaError si df_in viola contrato."""
        from emoparse.pipeline.stages import SummarizerStage

        mock_agent = MagicMock()
        mock_repo = MagicMock()

        # list_pending devuelve un discurso pendiente
        mock_repo.list_pending.return_value = ["D001"]
        # get_input devuelve dict sin 'contenido' — violará DiscursoInputContract
        mock_repo.get_input.return_value = {"titulo": "Solo titulo"}

        stage = SummarizerStage(mock_agent, mock_repo)
        stage.validate_contracts = True

        with pytest.raises(pa.errors.SchemaError):
            stage.run_pending()

    def test_actors_stage_contract_activo(self) -> None:
        """ActorsStage lanza SchemaError si el DF de frases viola FraseInputContract."""
        from emoparse.pipeline.stages import ActorsStage

        mock_backend = MagicMock()
        mock_d_repo = MagicMock()
        mock_f_repo = MagicMock()

        # Hay una frase pendiente
        mock_f_repo.list_pending.return_value = [("D001", 0)]
        mock_d_repo.get_input.return_value = {}
        mock_d_repo.get_payload.return_value = {}

        # get_frase devuelve None → el DF resultante estará vacío (rows=[])
        stage = ActorsStage(mock_backend, mock_d_repo, mock_f_repo)
        stage.validate_contracts = True

        def bad_build_input_df(codigo: str, unit_idxs: list) -> pd.DataFrame:
            return pd.DataFrame([{"codigo": "D001", "unit_idx": 0}])  # falta frase

        stage._build_input_df = bad_build_input_df  # type: ignore[method-assign]

        with pytest.raises(pa.errors.SchemaError):
            stage.run_pending()

    def test_emotions_stage_contract_activo(self) -> None:
        """EmotionsStage lanza SchemaError si el DF viola FraseConActoresContract."""
        from emoparse.pipeline.stages import EmotionsStage

        mock_backend = MagicMock()
        mock_d_repo = MagicMock()
        mock_f_repo = MagicMock()

        mock_f_repo.list_pending.return_value = [("D001", 0)]
        mock_d_repo.get_input.return_value = {}
        mock_d_repo.get_payload.return_value = {}

        stage = EmotionsStage(
            mock_backend, mock_d_repo, mock_f_repo,
            ontologia="", heuristicas="",
        )
        stage.validate_contracts = True

        def bad_build_input_df(codigo: str, unit_idxs: list) -> pd.DataFrame:
            # falta columna 'actores' → viola FraseConActoresContract
            return pd.DataFrame([{"codigo": "D001", "unit_idx": 0, "frase": "X"}])

        stage._build_input_df = bad_build_input_df  # type: ignore[method-assign]

        with pytest.raises(pa.errors.SchemaError):
            stage.run_pending()

    def test_explode_emociones_contract_activo(self) -> None:
        """ExplodeEmocionesStage lanza SchemaError si rows viola EmocionExplodedContract."""
        from emoparse.pipeline.stages import ExplodeEmocionesStage

        mock_d_repo = MagicMock()
        mock_f_repo = MagicMock()
        mock_e_repo = MagicMock()

        mock_d_repo.list_codigos.return_value = ["D001"]
        mock_f_repo.list_frases_of_discurso.return_value = [(0, "Frase test.")]

        # emociones_payload con una emoción que le falta 'tipo_emocion'
        mock_f_repo.get_payload.return_value = [
            {
                "experienciador": "hablante",
                # tipo_emocion ausente → se guardará como "" desde .get("tipo_emocion", "")
                # modo_existencia ausente → ""
            }
        ]

        stage = ExplodeEmocionesStage(mock_d_repo, mock_f_repo, mock_e_repo)
        stage.validate_contracts = True

        # El contrato exige que tipo_emocion y modo_existencia sean str no-null.
        # Como get() con default "" los rellena, el DF es válido.
        # Para forzar violación, se testea con un campo null explícito:
        mock_f_repo.get_payload.return_value = [
            {
                "experienciador": None,  # null → viola EmocionExplodedContract
                "tipo_emocion": "alegria",
                "modo_existencia": "actualizado",
            }
        ]

        with pytest.raises(pa.errors.SchemaError):
            stage.run_pending()

    def test_characterizer_stage_contract_activo(self) -> None:
        """CharacterizerStage lanza SchemaError si el DF viola EmocionExplodedContract."""
        from emoparse.pipeline.stages import CharacterizerStage

        mock_backend = MagicMock()
        mock_d_repo = MagicMock()
        mock_f_repo = MagicMock()
        mock_e_repo = MagicMock()

        mock_e_repo.list_pending_caracterizacion.return_value = [("D001", 0, 0)]
        mock_d_repo.get_input.return_value = {}
        mock_d_repo.get_payload.return_value = {}

        stage = CharacterizerStage(
            mock_backend, mock_d_repo, mock_f_repo, mock_e_repo
        )
        stage.validate_contracts = True

        def bad_build_input_df(codigo: str, items: list) -> pd.DataFrame:
            # falta emocion_idx → viola EmocionExplodedContract
            return pd.DataFrame([{
                "codigo": "D001",
                "frase_idx": 0,
                "frase": "X",
                "experienciador": "Y",
                "tipo_emocion": "Z",
                "modo_existencia": "W",
            }])

        stage._build_input_df = bad_build_input_df  # type: ignore[method-assign]

        with pytest.raises(pa.errors.SchemaError):
            stage.run_pending()

    def test_emotions_pass2_contract_activo(self) -> None:
        """EmotionsPass2Stage lanza SchemaError si df_pending viola FraseConEmocionesContract."""
        from emoparse.pipeline.stages import EmotionsPass2Stage

        mock_backend = MagicMock()
        mock_d_repo = MagicMock()
        mock_f_repo = MagicMock()

        mock_f_repo.list_pending.return_value = [("D001", 0)]
        mock_d_repo.get_input.return_value = {}

        stage = EmotionsPass2Stage(
            mock_backend, mock_d_repo, mock_f_repo,
            ontologia="", heuristicas="",
        )
        stage.validate_contracts = True

        # _build_full_df_with_rolling devuelve DF sin columna 'emociones'
        def bad_full_df(codigo: str) -> pd.DataFrame:
            return pd.DataFrame([{
                "codigo": "D001",
                "unit_idx": 0,
                "frase": "X",
                # falta 'emociones' → viola FraseConEmocionesContract
            }])

        stage._build_full_df_with_rolling = bad_full_df  # type: ignore[method-assign]

        with pytest.raises(pa.errors.SchemaError):
            stage.run_pending()

    def test_validate_contracts_false_no_lanza_en_stage(self) -> None:
        """Con validate_contracts=False, stages no lanza SchemaError aunque DF sea inválido."""
        from emoparse.pipeline.stages import SummarizerStage

        mock_agent = MagicMock()
        mock_agent.run.return_value = pd.DataFrame([{
            "codigo": "D001",
            "contenido": "x",
            "resumen_global": None,
            "resumen_fragmentos": None,
        }])
        mock_repo = MagicMock()
        mock_repo.list_pending.return_value = ["D001"]
        # DF sin 'contenido' normalmente violaría el contrato
        mock_repo.get_input.return_value = {"titulo": "Solo titulo"}

        stage = SummarizerStage(mock_agent, mock_repo)
        stage.validate_contracts = False  # desactivado

        try:
            stage.run_pending()
        except pa.errors.SchemaError:
            pytest.fail("SchemaError lanzado aunque validate_contracts=False")
