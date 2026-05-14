# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_inputs
#
#  Tests del loader de discursos input (CSV / JSON).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from emoparse.inputs import InputError, load_discursos


# ══════════════════════════════════════════════════════════════════════════════
#  CSV
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadCSV:

    def test_basic_csv(self, tmp_path: Path) -> None:
        p = tmp_path / "discursos.csv"
        p.write_text(
            "codigo,contenido,titulo\n"
            "DISC_001,\"Texto del primer discurso\",Asunción\n"
            "DISC_002,\"Texto del segundo discurso\",Anuncio\n",
            encoding="utf-8",
        )
        df = load_discursos(p)
        assert len(df) == 2
        assert list(df["codigo"]) == ["DISC_001", "DISC_002"]
        assert df.iloc[0]["titulo"] == "Asunción"

    def test_codigo_preserved_as_string(self, tmp_path: Path) -> None:
        """Códigos numéricos no se deben convertir a int automáticamente."""
        p = tmp_path / "x.csv"
        p.write_text("codigo,contenido\n001,texto\n002,texto2\n", encoding="utf-8")
        df = load_discursos(p)
        # `001` debería preservarse como string, no convertirse a int 1.
        assert df.iloc[0]["codigo"] == "001"
        assert isinstance(df.iloc[0]["codigo"], str)

    def test_extra_columns_preserved(self, tmp_path: Path) -> None:
        """Columnas adicionales pasan al DF tal cual."""
        p = tmp_path / "x.csv"
        p.write_text(
            "codigo,contenido,fecha,autor\n"
            "A,texto,2024-01-01,Pepe\n",
            encoding="utf-8",
        )
        df = load_discursos(p)
        assert "fecha" in df.columns
        assert "autor" in df.columns
        assert df.iloc[0]["autor"] == "Pepe"

    def test_non_utf8_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        # Latin-1 con caracteres no-ASCII.
        p.write_bytes("codigo,contenido\nA,áéí\n".encode("latin-1"))
        with pytest.raises(InputError, match="UTF-8"):
            load_discursos(p)


# ══════════════════════════════════════════════════════════════════════════════
#  JSON formato lista
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadJSONList:

    def test_basic_list(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        p.write_text(json.dumps([
            {"codigo": "A", "contenido": "texto A"},
            {"codigo": "B", "contenido": "texto B"},
        ]), encoding="utf-8")
        df = load_discursos(p)
        assert len(df) == 2
        assert set(df["codigo"]) == {"A", "B"}


# ══════════════════════════════════════════════════════════════════════════════
#  JSON formato dict
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadJSONDict:

    def test_dict_format_uses_key_as_codigo(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        p.write_text(json.dumps({
            "DISC_A": {"contenido": "texto A", "titulo": "T A"},
            "DISC_B": {"contenido": "texto B", "titulo": "T B"},
        }), encoding="utf-8")
        df = load_discursos(p)
        assert set(df["codigo"]) == {"DISC_A", "DISC_B"}
        # Titulo se preserva.
        assert "T A" in df["titulo"].tolist()

    def test_dict_format_with_redundant_codigo_must_match(
        self, tmp_path: Path
    ) -> None:
        """Si el payload incluye `codigo` debe coincidir con la key."""
        p = tmp_path / "x.json"
        # Coincide: ok.
        p.write_text(json.dumps({
            "DISC_A": {"codigo": "DISC_A", "contenido": "x"},
        }), encoding="utf-8")
        df = load_discursos(p)
        assert df.iloc[0]["codigo"] == "DISC_A"

    def test_dict_format_with_mismatched_codigo_raises(
        self, tmp_path: Path
    ) -> None:
        p = tmp_path / "x.json"
        p.write_text(json.dumps({
            "DISC_A": {"codigo": "OTRO", "contenido": "x"},
        }), encoding="utf-8")
        with pytest.raises(InputError, match="no coincide"):
            load_discursos(p)


# ══════════════════════════════════════════════════════════════════════════════
#  Validaciones
# ══════════════════════════════════════════════════════════════════════════════


class TestValidations:

    def test_missing_codigo_column(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        p.write_text("contenido,titulo\ntexto,T\n", encoding="utf-8")
        with pytest.raises(InputError, match="codigo"):
            load_discursos(p)

    def test_missing_contenido_column(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        p.write_text("codigo,titulo\nDISC,T\n", encoding="utf-8")
        with pytest.raises(InputError, match="contenido"):
            load_discursos(p)

    def test_duplicate_codigos_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        p.write_text(
            "codigo,contenido\n"
            "DISC_A,texto1\n"
            "DISC_A,texto2\n",
            encoding="utf-8",
        )
        with pytest.raises(InputError, match="duplicados"):
            load_discursos(p)

    def test_empty_contenido_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        p.write_text(
            "codigo,contenido\n"
            "DISC_A,\n",  # contenido vacío
            encoding="utf-8",
        )
        with pytest.raises(InputError, match="vacío"):
            load_discursos(p)

    def test_whitespace_only_contenido_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        p.write_text(json.dumps([
            {"codigo": "A", "contenido": "   "},
        ]), encoding="utf-8")
        with pytest.raises(InputError, match="vacío"):
            load_discursos(p)


# ══════════════════════════════════════════════════════════════════════════════
#  Errores generales
# ══════════════════════════════════════════════════════════════════════════════


class TestGeneralErrors:

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(InputError, match="no encontrado"):
            load_discursos(tmp_path / "no_existe.csv")

    def test_unknown_extension(self, tmp_path: Path) -> None:
        p = tmp_path / "x.txt"
        p.write_text("foo")
        with pytest.raises(InputError, match="Extensión"):
            load_discursos(p)

    def test_invalid_json(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        p.write_text("{ no es json }", encoding="utf-8")
        with pytest.raises(InputError, match="JSON inválido"):
            load_discursos(p)

    def test_json_top_level_string_raises(self, tmp_path: Path) -> None:
        """JSON debe ser lista o dict, no string."""
        p = tmp_path / "x.json"
        p.write_text('"esto es un string"', encoding="utf-8")
        with pytest.raises(InputError, match="lista o dict"):
            load_discursos(p)

    def test_json_empty_list_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "x.json"
        p.write_text("[]", encoding="utf-8")
        with pytest.raises(InputError, match="no contiene"):
            load_discursos(p)


# ══════════════════════════════════════════════════════════════════════════════
#  Output sanity
# ══════════════════════════════════════════════════════════════════════════════


class TestOutputShape:

    def test_returns_dataframe(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        p.write_text("codigo,contenido\nA,x\n", encoding="utf-8")
        df = load_discursos(p)
        assert isinstance(df, pd.DataFrame)

    def test_row_order_preserved(self, tmp_path: Path) -> None:
        p = tmp_path / "x.csv"
        p.write_text(
            "codigo,contenido\n"
            "C,c\nA,a\nB,b\n",
            encoding="utf-8",
        )
        df = load_discursos(p)
        # Orden del CSV se respeta.
        assert list(df["codigo"]) == ["C", "A", "B"]
