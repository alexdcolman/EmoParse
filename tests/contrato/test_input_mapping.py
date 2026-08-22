"""Contratos de diagnóstico y mapeo de corpus tabulares de terceros."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from emoparse.cli.commands.doctor_cmd import handle as doctor_handle
from emoparse.cli.commands.ingest_map_cmd import handle as ingest_map_handle
from emoparse.genres.discurso_presidencial import get_genre
from emoparse.inputs.loader import InputError, load_discursos
from emoparse.inputs.tabular_mapping import (
    CorpusMapping,
    CsvFormat,
    diagnose_csv,
    load_mapping,
    render_mapping_yaml,
)

LATIN1_CSV = """Informe exportado por sistema externo
Generado 2026-08-21
doc_id;cuerpo_texto;publicada;origen;nota
A-01;<p>Texto largo con emoción y contexto suficiente para ser contenido principal.</p>;21/08/2026;archivo X;primera
A-02;Segundo texto bastante más largo que un identificador y con suficiente contenido para el análisis.;2026-08-20;archivo X;segunda
A-03;Tercer texto con otro formato de fecha y una palabra con acento: emoción.;Aug 19 2026;archivo X;tercera
"""


def _latin1_csv(tmp_path: Path) -> Path:
    path = tmp_path / "semicolon_latin1_header3.csv"
    path.write_bytes(LATIN1_CSV.encode("latin-1"))
    return path


def test_doctor_detects_latin1_semicolon_and_header_row_three(tmp_path: Path) -> None:
    fixture = _latin1_csv(tmp_path)
    report = diagnose_csv(fixture, genre=get_genre())

    assert report.csv.encoding == "latin-1"
    assert report.csv.delimiter == ";"
    assert report.csv.header_row == 3
    assert report.rows == 3
    assert report.html_rows == 1
    assert report.date_parse_ratio == 1.0

    proposals = {item.target: item.source for item in report.proposals}
    assert proposals["codigo"] == "doc_id"
    assert proposals["contenido"] == "cuerpo_texto"
    assert proposals["fecha"] == "publicada"
    assert report.ready


def test_mapping_roundtrip_loads_required_fields_and_preserves_unmapped_metadata(
    tmp_path: Path,
) -> None:
    fixture = _latin1_csv(tmp_path)
    report = diagnose_csv(fixture, genre=get_genre())
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(render_mapping_yaml(report), encoding="utf-8")

    loaded = load_mapping(mapping_path)
    frame = load_discursos(fixture, genre=get_genre(), mapping=mapping_path)

    assert loaded.csv.header_row == 3
    assert frame["codigo"].tolist() == ["A-01", "A-02", "A-03"]
    assert frame["contenido"].tolist() == [
        "<p>Texto largo con emoción y contexto suficiente para ser contenido principal.</p>",
        "Segundo texto bastante más largo que un identificador y con suficiente contenido para el análisis.",
        "Tercer texto con otro formato de fecha y una palabra con acento: emoción.",
    ]
    assert frame["fuente"].tolist() == ["archivo X"] * 3
    assert frame["nota"].tolist() == ["primera", "segunda", "tercera"]
    assert "doc_id" not in frame.columns
    assert "cuerpo_texto" not in frame.columns


def test_mapping_yaml_is_explicitly_revisable(tmp_path: Path) -> None:
    fixture = _latin1_csv(tmp_path)
    report = diagnose_csv(fixture, genre=get_genre())
    rendered = render_mapping_yaml(report)
    parsed = yaml.safe_load(rendered)

    assert "Revisar antes de usarlo" in rendered
    assert parsed["version"] == 1
    assert parsed["csv"]["encoding"] == "latin-1"
    assert parsed["fields"]["codigo"] == "doc_id"
    assert parsed["fields"]["contenido"] == "cuerpo_texto"


def test_doctor_reports_duplicates_empty_content_and_viable_ratio(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame(
        [
            {"id": "1", "text": "texto uno"},
            {"id": "1", "text": "texto dos"},
            {"id": "3", "text": ""},
        ]
    ).to_csv(path, index=False)

    report = diagnose_csv(path, genre=get_genre())

    assert report.duplicate_codes == 1
    assert report.empty_content == 1
    assert not report.ready
    assert report.individually_viable_rows == 0


def test_manual_mapping_can_resolve_ambiguous_column_names(tmp_path: Path) -> None:
    path = tmp_path / "ambiguous.csv"
    path.write_text(
        "a;b;c\nx1;uno;texto largo de prueba\nx2;dos;otro texto largo\n", encoding="utf-8"
    )
    mapping_path = tmp_path / "manual.yaml"
    mapping_path.write_text(
        """version: 1
csv:
  encoding: utf-8
  delimiter: ";"
  header_row: 1
fields:
  codigo: a
  contenido: c
  titulo: null
  fecha: null
  url: null
  fuente: null
""",
        encoding="utf-8",
    )

    frame = load_discursos(path, genre=get_genre(), mapping=mapping_path)

    assert frame["codigo"].tolist() == ["x1", "x2"]
    assert frame["contenido"].tolist() == ["texto largo de prueba", "otro texto largo"]
    assert frame["b"].tolist() == ["uno", "dos"]


def test_doctor_handler_is_read_only(tmp_path: Path) -> None:
    fixture = _latin1_csv(tmp_path)
    before = fixture.read_bytes()

    class Args:
        genre = None
        mapping = None

    args = Args()
    args.input = str(fixture)

    assert doctor_handle(args) == 0
    assert fixture.read_bytes() == before


def test_ingest_map_refuses_silent_overwrite(tmp_path: Path) -> None:
    fixture = _latin1_csv(tmp_path)
    out = tmp_path / "mapping.yaml"
    out.write_text("original\n", encoding="utf-8")

    class Args:
        genre = None
        overwrite = False

    args = Args()
    args.input = str(fixture)
    args.out = str(out)

    assert ingest_map_handle(args) == 2
    assert out.read_text(encoding="utf-8") == "original\n"


def test_mapping_object_rejects_no_required_fields_through_loader(tmp_path: Path) -> None:
    path = tmp_path / "simple.csv"
    path.write_text("id,text\n1,hola\n", encoding="utf-8")
    mapping = CorpusMapping(
        csv=CsvFormat(encoding="utf-8", delimiter=",", header_row=1),
        fields={"codigo": None, "contenido": "text"},
    )
    mapping_path = tmp_path / "mapping.yaml"
    mapping_path.write_text(
        """version: 1
csv:
  encoding: utf-8
  delimiter: ","
  header_row: 1
fields:
  codigo: null
  contenido: text
""",
        encoding="utf-8",
    )

    assert mapping.fields["codigo"] is None
    with pytest.raises(InputError, match="campos obligatorios"):
        load_discursos(path, genre=get_genre(), mapping=mapping_path)
