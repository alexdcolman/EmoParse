"""Diagnóstico y mapeo determinista de corpus tabulares de terceros."""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from emoparse.genres.base import Genre
from emoparse.pipeline.unit_dispatch import split_for

BASE_FIELDS: tuple[str, ...] = ("codigo", "contenido", "titulo", "fecha", "url", "fuente")
REQUIRED_FIELDS: tuple[str, ...] = ("codigo", "contenido")
_DELIMITERS: tuple[str, ...] = (",", ";", "\t", "|")
_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")

_ALIASES: dict[str, tuple[str, ...]] = {
    "codigo": (
        "codigo",
        "id",
        "identifier",
        "identificador",
        "document_id",
        "doc_id",
        "record_id",
        "uid",
        "key",
    ),
    "contenido": (
        "contenido",
        "texto",
        "text",
        "content",
        "body",
        "cuerpo",
        "cuerpo_texto",
        "discurso",
        "documento",
        "full_text",
        "mensaje",
    ),
    "titulo": ("titulo", "title", "headline", "encabezado"),
    "fecha": (
        "fecha",
        "date",
        "created_at",
        "published_at",
        "publication_date",
        "publish_date",
        "timestamp",
        "publicada",
    ),
    "url": ("url", "link", "href", "permalink"),
    "fuente": ("fuente", "source", "medio", "outlet", "origin", "origen"),
}


class MappingError(ValueError):
    """Error de formato o aplicación de un mapping tabular."""


@dataclass(frozen=True, slots=True)
class CsvFormat:
    """Formato suficiente para leer de forma reproducible un CSV ajeno."""

    encoding: str
    delimiter: str
    header_row: int
    bom: bool = False


@dataclass(frozen=True, slots=True)
class CorpusMapping:
    """Mapping YAML de campos de origen a nombres que entiende EmoParse."""

    csv: CsvFormat
    fields: dict[str, str | None]
    version: int = 1


@dataclass(frozen=True, slots=True)
class FieldProposal:
    """Propuesta auditable para un campo destino."""

    target: str
    source: str | None
    confidence: str
    reason: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Resultado estructurado del diagnóstico de un corpus tabular."""

    path: Path
    csv: CsvFormat
    columns: tuple[str, ...]
    proposals: tuple[FieldProposal, ...]
    rows: int
    individually_viable_rows: int
    viable_ratio: float
    duplicate_codes: int
    empty_codes: int
    empty_content: int
    date_parse_ratio: float | None
    html_rows: int
    genre_id: str
    genre_unit: str
    mean_units_per_record: float
    mean_chars_per_unit: float
    blocking: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return not self.blocking


def load_mapping(path: Path | str) -> CorpusMapping:
    """Carga y valida un mapping YAML."""
    mapping_path = Path(path).expanduser().resolve()
    try:
        raw = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MappingError(f"Mapping inválido en {mapping_path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise MappingError(f"El mapping de {mapping_path} debe ser un objeto YAML.")
    version = raw.get("version", 1)
    if version != 1:
        raise MappingError(f"Versión de mapping no soportada: {version!r}. Esperada: 1.")

    csv_raw = raw.get("csv")
    fields_raw = raw.get("fields")
    if not isinstance(csv_raw, dict) or not isinstance(fields_raw, dict):
        raise MappingError("El mapping debe contener objetos `csv` y `fields`.")

    encoding = str(csv_raw.get("encoding") or "utf-8").strip()
    delimiter = str(csv_raw.get("delimiter") or ",")
    try:
        header_row = int(csv_raw.get("header_row", 1))
    except (TypeError, ValueError) as exc:
        raise MappingError("`csv.header_row` debe ser un entero desde 1.") from exc
    if len(delimiter) != 1:
        raise MappingError("`csv.delimiter` debe contener exactamente un carácter.")
    if header_row < 1:
        raise MappingError("`csv.header_row` debe ser >= 1.")

    fields: dict[str, str | None] = {}
    used_sources: set[str] = set()
    for raw_target, raw_source in fields_raw.items():
        target = str(raw_target).strip()
        if not target:
            raise MappingError("Los nombres destino del mapping no pueden estar vacíos.")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", target) is None:
            raise MappingError(
                f"Nombre destino inválido {target!r}; usar identificadores simples como `codigo` o `autor`."
            )
        source = None if raw_source is None else str(raw_source).strip()
        if source == "":
            source = None
        if source is not None:
            if source in used_sources:
                raise MappingError(f"La columna de origen {source!r} está mapeada más de una vez.")
            used_sources.add(source)
        fields[target] = source

    return CorpusMapping(
        csv=CsvFormat(encoding=encoding, delimiter=delimiter, header_row=header_row),
        fields=fields,
        version=1,
    )


def read_mapped_csv(path: Path | str, mapping: CorpusMapping) -> pd.DataFrame:
    """Lee un CSV según el mapping y conserva metadata no mapeada."""
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise MappingError(f"Archivo input no encontrado: {source_path}")

    try:
        df = pd.read_csv(
            source_path,
            encoding=mapping.csv.encoding,
            sep=mapping.csv.delimiter,
            header=mapping.csv.header_row - 1,
            dtype=str,
            keep_default_na=False,
        )
    except (UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise MappingError(f"CSV ilegible en {source_path}: {exc}") from exc

    present = [str(column) for column in df.columns]
    missing_sources = sorted(
        source for source in mapping.fields.values() if source is not None and source not in present
    )
    if missing_sources:
        raise MappingError(
            f"El mapping refiere columnas que no existen: {missing_sources}. "
            f"Columnas presentes: {present}"
        )

    unresolved = [field for field in REQUIRED_FIELDS if not mapping.fields.get(field)]
    if unresolved:
        raise MappingError(
            f"El mapping debe resolver los campos obligatorios {list(REQUIRED_FIELDS)}; "
            f"faltan: {unresolved}."
        )

    used = {source for source in mapping.fields.values() if source is not None}
    out = pd.DataFrame(index=df.index)
    for target, source in mapping.fields.items():
        if source is not None:
            out[target] = df[source]

    # Las columnas ajenas al mapping siguen disponibles como metadata de input.
    # Si una de ellas colisiona con un destino canónico, se conserva con prefijo.
    for column in present:
        if column in used:
            continue
        target = column if column not in out.columns else f"extra__{column}"
        out[target] = df[column]
    return out


def diagnose_csv(
    path: Path | str,
    *,
    genre: Genre,
    mapping: CorpusMapping | None = None,
) -> DoctorReport:
    """Diagnostica un CSV sin modificarlo."""
    source_path = Path(path).expanduser().resolve()
    if not source_path.is_file():
        raise MappingError(f"Archivo input no encontrado: {source_path}")

    if mapping is None:
        csv_format = detect_csv_format(source_path)
        raw_df = _read_detected(source_path, csv_format)
        proposals = propose_fields(raw_df, genre=genre)
        mapping = CorpusMapping(
            csv=csv_format,
            fields={proposal.target: proposal.source for proposal in proposals},
        )
    else:
        csv_format = mapping.csv
        raw_df = _read_detected(source_path, csv_format)
        proposals = tuple(
            FieldProposal(
                target=target,
                source=source,
                confidence="manual" if source else "revisar",
                reason="definido en mapping" if source else "sin resolver en mapping",
            )
            for target, source in mapping.fields.items()
        )

    proposal_map = {proposal.target: proposal.source for proposal in proposals}
    code_col = proposal_map.get("codigo")
    content_col = proposal_map.get("contenido")
    date_col = proposal_map.get("fecha")

    rows = len(raw_df)
    empty_codes = rows
    empty_content = rows
    duplicate_codes = 0
    viable = 0
    if code_col and code_col in raw_df.columns:
        codes = raw_df[code_col].fillna("").astype(str).str.strip()
        empty_codes = int((codes == "").sum())
        duplicate_codes = int(codes[codes != ""].duplicated().sum())
    else:
        codes = pd.Series([""] * rows, dtype="object")

    if content_col and content_col in raw_df.columns:
        contents = raw_df[content_col].fillna("").astype(str).str.strip()
        empty_content = int((contents == "").sum())
    else:
        contents = pd.Series([""] * rows, dtype="object")

    if rows:
        viable_mask = (codes != "") & (contents != "") & ~codes.duplicated(keep=False)
        viable = int(viable_mask.sum())
    viable_ratio = viable / rows if rows else 0.0

    date_ratio: float | None = None
    if date_col and date_col in raw_df.columns and rows:
        dates = raw_df[date_col].fillna("").astype(str).str.strip()
        nonempty = dates[dates != ""]
        if len(nonempty):
            parsed = pd.to_datetime(nonempty, errors="coerce", format="mixed")
            date_ratio = float(parsed.notna().mean())

    html_rows = 0
    unit_lengths: list[int] = []
    unit_count = 0
    if len(contents):
        html_rows = int(contents.map(lambda text: bool(_HTML_RE.search(text))).sum())
        for text in contents:
            if not text:
                continue
            units = split_for(text, genre.unit)
            unit_count += len(units)
            unit_lengths.extend(len(unit) for unit in units)

    nonempty_records = int((contents != "").sum())
    mean_units = unit_count / nonempty_records if nonempty_records else 0.0
    mean_chars = sum(unit_lengths) / len(unit_lengths) if unit_lengths else 0.0

    blocking: list[str] = []
    warnings: list[str] = []
    if not code_col:
        blocking.append("No se pudo proponer una columna inequívoca para `codigo`.")
    if not content_col:
        blocking.append("No se pudo proponer una columna inequívoca para `contenido`.")
    if empty_codes:
        blocking.append(f"Hay {empty_codes} fila(s) con código vacío.")
    if duplicate_codes:
        blocking.append(f"Hay {duplicate_codes} código(s) duplicado(s).")
    if empty_content:
        blocking.append(f"Hay {empty_content} fila(s) con contenido vacío.")
    if date_ratio is not None and date_ratio < 0.8:
        warnings.append(f"Solo {date_ratio:.0%} de las fechas no vacías se pueden parsear.")
    if html_rows:
        warnings.append(f"Hay {html_rows} fila(s) cuyo contenido conserva etiquetas HTML.")
    if csv_format.encoding not in ("utf-8", "utf-8-sig"):
        warnings.append(
            f"El archivo no es UTF-8; el mapping debe conservar encoding={csv_format.encoding!r}."
        )

    return DoctorReport(
        path=source_path,
        csv=csv_format,
        columns=tuple(str(column) for column in raw_df.columns),
        proposals=proposals,
        rows=rows,
        individually_viable_rows=viable,
        viable_ratio=viable_ratio,
        duplicate_codes=duplicate_codes,
        empty_codes=empty_codes,
        empty_content=empty_content,
        date_parse_ratio=date_ratio,
        html_rows=html_rows,
        genre_id=genre.genre_id,
        genre_unit=genre.unit,
        mean_units_per_record=mean_units,
        mean_chars_per_unit=mean_chars,
        blocking=tuple(blocking),
        warnings=tuple(warnings),
    )


def detect_csv_format(path: Path | str) -> CsvFormat:
    """Detecta encoding, delimitador y fila de encabezado con heurísticas acotadas."""
    source_path = Path(path).expanduser().resolve()
    data = source_path.read_bytes()
    bom = data.startswith(b"\xef\xbb\xbf")
    encoding = _detect_encoding(data)
    text = data.decode(encoding)
    lines = text.splitlines()
    if not lines:
        raise MappingError(f"CSV vacío: {source_path}")

    best: tuple[float, int, int, str] | None = None
    max_header = min(8, max(len(lines) - 1, 1))
    for header_idx in range(max_header):
        for delimiter_index, delimiter in enumerate(_DELIMITERS):
            score = _header_score(lines, header_idx, delimiter)
            candidate = (score, -header_idx, -delimiter_index, delimiter)
            if best is None or candidate > best:
                best = candidate

    assert best is not None
    score, neg_header, _, delimiter = best
    if score < 4:
        raise MappingError("No se pudo detectar de forma confiable el delimitador/encabezado.")
    return CsvFormat(
        encoding=encoding,
        delimiter=delimiter,
        header_row=(-neg_header) + 1,
        bom=bom,
    )


def propose_fields(df: pd.DataFrame, *, genre: Genre) -> tuple[FieldProposal, ...]:
    """Propone un mapping por nombres y rasgos simples de contenido."""
    columns = [str(column) for column in df.columns]
    normalized = {_normalize_name(column): column for column in columns}
    targets = list(BASE_FIELDS)
    if genre.input_metadata_model is not None:
        for field in genre.input_metadata_model.model_fields:
            if field not in targets:
                targets.append(field)

    proposals: list[FieldProposal] = []
    used: set[str] = set()
    for target in targets:
        source = _match_by_name(target, normalized)
        if source is not None and source not in used:
            proposals.append(FieldProposal(target, source, "alta", "nombre de columna reconocido"))
            used.add(source)
        else:
            proposals.append(FieldProposal(target, None, "revisar", "sin coincidencia nominal"))

    by_target = {proposal.target: proposal for proposal in proposals}
    if by_target["contenido"].source is None:
        source, confident = _infer_content(df, used)
        if source is not None:
            _replace_proposal(
                proposals,
                FieldProposal(
                    "contenido",
                    source,
                    "media" if confident else "revisar",
                    "columna con mayor longitud textual media",
                ),
            )
            used.add(source)

    if by_target["fecha"].source is None:
        source, ratio = _infer_date(df, used)
        if source is not None and ratio >= 0.8:
            _replace_proposal(
                proposals,
                FieldProposal(
                    "fecha", source, "media", f"{ratio:.0%} de valores parsean como fecha"
                ),
            )
            used.add(source)

    if by_target["url"].source is None:
        source, ratio = _infer_url(df, used)
        if source is not None and ratio >= 0.8:
            _replace_proposal(
                proposals,
                FieldProposal("url", source, "media", f"{ratio:.0%} de valores parecen URL"),
            )
            used.add(source)

    if by_target["codigo"].source is None:
        source, confident = _infer_code(df, used)
        if source is not None:
            _replace_proposal(
                proposals,
                FieldProposal(
                    "codigo",
                    source,
                    "media" if confident else "revisar",
                    "columna corta, no vacía y casi única",
                ),
            )
            used.add(source)

    return tuple(proposals)


def render_mapping_yaml(report: DoctorReport) -> str:
    """Renderiza una propuesta YAML revisable con comentarios de confianza."""
    lines = [
        "# Mapping propuesto por EmoParse. Revisar antes de usarlo.",
        "# Las columnas no mapeadas se conservan como metadata del input.",
        "version: 1",
        "csv:",
        f"  encoding: {_yaml_scalar(report.csv.encoding)}",
        f"  delimiter: {_yaml_scalar(report.csv.delimiter)}",
        f"  header_row: {report.csv.header_row}",
        "fields:",
    ]
    for proposal in report.proposals:
        lines.append(f"  # {proposal.confidence}: {proposal.reason}")
        value = "null" if proposal.source is None else _yaml_scalar(proposal.source)
        lines.append(f"  {proposal.target}: {value}")
    return "\n".join(lines) + "\n"


def _read_detected(path: Path, csv_format: CsvFormat) -> pd.DataFrame:
    try:
        return pd.read_csv(
            path,
            encoding=csv_format.encoding,
            sep=csv_format.delimiter,
            header=csv_format.header_row - 1,
            dtype=str,
            keep_default_na=False,
        )
    except (UnicodeDecodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        raise MappingError(f"CSV ilegible en {path}: {exc}") from exc


def _detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        if any(0x80 <= byte <= 0x9F for byte in data):
            return "cp1252"
        return "latin-1"


def _header_score(lines: list[str], header_idx: int, delimiter: str) -> float:
    header = _parse_line(lines[header_idx], delimiter)
    if len(header) < 2 or len(set(header)) != len(header):
        return -1.0
    following = [_parse_line(line, delimiter) for line in lines[header_idx + 1 : header_idx + 4]]
    stable = sum(1 for row in following if len(row) == len(header))
    nonempty = sum(1 for cell in header if cell.strip())
    aliases = sum(
        1
        for cell in header
        if any(_normalize_name(cell) in aliases for aliases in _ALIASES.values())
    )
    return len(header) + (stable * 4) + nonempty / max(len(header), 1) + (aliases * 3)


def _parse_line(line: str, delimiter: str) -> list[str]:
    try:
        return next(csv.reader([line], delimiter=delimiter))
    except csv.Error:
        return [line]


def _normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "_", text.casefold()).strip("_")


def _match_by_name(target: str, normalized: dict[str, str]) -> str | None:
    candidates = _ALIASES.get(target, (target,))
    for candidate in candidates:
        found = normalized.get(_normalize_name(candidate))
        if found is not None:
            return found
    return normalized.get(_normalize_name(target))


def _series_text(df: pd.DataFrame, column: str) -> pd.Series:
    return df[column].fillna("").astype(str).str.strip()


def _infer_content(df: pd.DataFrame, used: set[str]) -> tuple[str | None, bool]:
    scored: list[tuple[float, str]] = []
    for column in map(str, df.columns):
        if column in used:
            continue
        values = _series_text(df, column)
        nonempty = values[values != ""]
        if len(nonempty) == 0:
            continue
        mean_len = float(nonempty.str.len().mean())
        nonempty_ratio = len(nonempty) / max(len(values), 1)
        scored.append((mean_len * nonempty_ratio, column))
    scored.sort(reverse=True)
    if not scored:
        return None, False
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    confident = best_score >= 30 and (second == 0 or best_score >= second * 1.35)
    return best, confident


def _infer_date(df: pd.DataFrame, used: set[str]) -> tuple[str | None, float]:
    best: tuple[float, str] | None = None
    for column in map(str, df.columns):
        if column in used:
            continue
        values = _series_text(df, column)
        nonempty = values[values != ""]
        if len(nonempty) < 2:
            continue
        parsed = pd.to_datetime(nonempty, errors="coerce", format="mixed")
        ratio = float(parsed.notna().mean())
        candidate = (ratio, column)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None, 0.0
    return best[1], best[0]


def _infer_url(df: pd.DataFrame, used: set[str]) -> tuple[str | None, float]:
    best: tuple[float, str] | None = None
    for column in map(str, df.columns):
        if column in used:
            continue
        values = _series_text(df, column)
        nonempty = values[values != ""]
        if len(nonempty) < 2:
            continue
        ratio = float(nonempty.str.match(r"https?://", case=False).mean())
        candidate = (ratio, column)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None, 0.0
    return best[1], best[0]


def _infer_code(df: pd.DataFrame, used: set[str]) -> tuple[str | None, bool]:
    scored: list[tuple[float, str]] = []
    for column in map(str, df.columns):
        if column in used:
            continue
        values = _series_text(df, column)
        nonempty = values[values != ""]
        if len(nonempty) == 0:
            continue
        nonempty_ratio = len(nonempty) / max(len(values), 1)
        unique_ratio = float(nonempty.nunique(dropna=True) / len(nonempty))
        mean_len = float(nonempty.str.len().mean())
        if mean_len > 100:
            continue
        short_bonus = max(0.0, 1.0 - mean_len / 100.0)
        score = (unique_ratio * 0.65) + (nonempty_ratio * 0.25) + (short_bonus * 0.10)
        scored.append((score, column))
    scored.sort(reverse=True)
    if not scored:
        return None, False
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    confident = best_score >= 0.92 and (second == 0 or best_score - second >= 0.04)
    return best, confident


def _replace_proposal(proposals: list[FieldProposal], replacement: FieldProposal) -> None:
    for index, proposal in enumerate(proposals):
        if proposal.target == replacement.target:
            proposals[index] = replacement
            return
    proposals.append(replacement)


def _yaml_scalar(value: str) -> str:
    """Scalar YAML en una sola línea, sin el terminador documental de PyYAML."""
    return json.dumps(value, ensure_ascii=False)
