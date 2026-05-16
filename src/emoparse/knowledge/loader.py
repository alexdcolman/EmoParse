# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.knowledge.loader
#
#  Carga ontologías y heurísticas del proyecto.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from loguru import logger


class KnowledgeError(ValueError):
    """Error al cargar archivos de knowledge."""


class KnowledgeLoader:
    """Carga ontologías, diccionarios y heurísticas desde filesystem."""

    def __init__(self, knowledge_dir: Path | str) -> None:
        self._dir = Path(knowledge_dir).expanduser().resolve()
        self._cache: dict[Path, str] = {}

    # ── API pública ──────────────────────────────────────────────────────────

    def load_ontology(self, filename: str) -> str:
        """Carga una ontología semiótica JSON y la formatea como string."""
        path = self._resolve(filename)
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        data = self._read_json(path)
        defs = self._extract_definitions(data, path)
        formatted = self._format_definitions(defs)

        self._cache[path] = formatted
        logger.debug(f"[Knowledge] Cargada ontología: {path.name} ({len(defs)} entradas)")
        return formatted

    def load_diccionario_tipos(self, filename: str) -> dict[str, Any]:
        """Carga el diccionario de tipos de discurso como dict."""
        path = self._resolve(filename)
        return self._read_json(path)

    def load_heuristics(self, filename: str) -> str:
        """Carga heurísticas desde un archivo de texto plano."""
        path = self._resolve(filename)
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as e:
            raise KnowledgeError(f"No pude leer {path}: {e}") from e

        if not content:
            raise KnowledgeError(f"Archivo de heurísticas vacío: {path}")

        self._cache[path] = content
        logger.debug(f"[Knowledge] Cargadas heurísticas: {path.name} ({len(content)} chars)")
        return content

    def load_emotion_ontology(self, filename: str = "emociones_ontologia.json") -> dict[str, Any]:
        """Devuelve el dict crudo de la ontología de emociones, sin formateo."""
        path = self._resolve(filename)
        data = self._read_json(path)
        logger.debug(
            f"[Knowledge] Cargada ontología de emociones: {path.name} "
            f"({len(data.get('emociones', {}))} entradas)"
        )
        return data

    def load_actors_kb(self, filename: str = "actors_kb.json") -> dict[str, Any]:
        """Devuelve el dict crudo de la KB de actores, sin formateo.

        Estructura esperada: `{"version": "...", "actors": {<canonical_id>: {...}}}`.
        """
        path = self._resolve(filename)
        data = self._read_json(path)
        logger.debug(
            f"[Knowledge] Cargada KB de actores: {path.name} "
            f"({len(data.get('actors', {}))} entradas)"
        )
        return data

    def load_emotion_configurations(
        self,
        filename: str = "configuraciones_emocion.json",
    ) -> str:
        """Carga los ocho tipos de configuraciones de simulacro emocional.

        Devuelve un string formateado para inyectar directamente en el
        system prompt del agente de emociones. Cada configuración aparece
        con su nombre canónico (la clave del Literal `TipoConfiguracion`),
        su definición operativa, la heurística de detección y 1-N ejemplos.
        """
        path = self._resolve(filename)
        cached = self._cache.get(path)
        if cached is not None:
            return cached

        data = self._read_json(path)
        configs = data.get("configuraciones") or {}
        if not isinstance(configs, dict) or not configs:
            raise KnowledgeError(
                f"El JSON de {path} no contiene una clave 'configuraciones' "
                f"con entradas válidas."
            )

        lines: list[str] = []
        for key, entry in configs.items():
            if not isinstance(entry, dict):
                continue
            id_ = entry.get("id", "?")
            definicion = entry.get("definicion", "")
            heuristica = entry.get("heuristica_deteccion", "")
            ejemplos = entry.get("ejemplos") or []

            lines.append(f"- {key} (id {id_}): {definicion}")
            if heuristica:
                lines.append(f"  Detección: {heuristica}")
            if ejemplos:
                ejemplos_str = "; ".join(str(e) for e in ejemplos)
                lines.append(f"  Ejemplos: {ejemplos_str}")

        formatted = "\n".join(lines)
        self._cache[path] = formatted
        logger.debug(
            f"[Knowledge] Cargadas configuraciones de emoción: "
            f"{path.name} ({len(configs)} entradas)"
        )
        return formatted

    def clear_cache(self) -> None:
        """Limpia el cache."""
        self._cache.clear()
        logger.debug("[Knowledge] Cache limpiada")

    # ── Helpers internos ─────────────────────────────────────────────────────

    def _resolve(self, filename: str) -> Path:
        """Resuelve filename relativo a knowledge_dir."""
        p = Path(filename)
        if p.is_absolute():
            return p
        return (self._dir / filename).resolve()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        """Lee y parsea JSON desde path."""
        if not path.is_file():
            raise KnowledgeError(f"Archivo no encontrado: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as e:
            raise KnowledgeError(f"No pude leer {path}: {e}") from e
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise KnowledgeError(f"JSON inválido en {path}: {e}") from e
        if not isinstance(data, dict):
            raise KnowledgeError(
                f"El JSON de {path} debe ser un mapping, recibí: {type(data).__name__}"
            )
        return data

    @staticmethod
    def _extract_definitions(data: dict[str, Any], path: Path) -> dict[str, Any]:
        """Extrae dict de definiciones desde JSON cargado."""
        if not data:
            raise KnowledgeError(f"JSON vacío en {path}")

        if len(data) == 1:
            only_key = next(iter(data))
            value = data[only_key]
            if isinstance(value, dict) and all(
                isinstance(v, dict) for v in value.values()
            ):
                return value

        if all(isinstance(v, dict) for v in data.values()):
            return data

        raise KnowledgeError(
            f"No pude inferir la estructura de definiciones en {path}. "
            f"Esperaba uno de estos formatos:\n"
            f"  {{<clave_top>: {{<id>: {{...}}}}}} o\n"
            f"  {{<id>: {{...}}}}"
        )

    @staticmethod
    def _format_definitions(defs: dict[str, Any]) -> str:
        """Formatea definiciones como string legible."""
        lines: list[str] = []
        for key, entry in defs.items():
            if not isinstance(entry, dict):
                continue
            nombre = entry.get("nombre", key)
            descripcion = entry.get("descripcion", "")
            ejemplo = entry.get("ejemplo", "")

            line = f"- {nombre}"
            if descripcion:
                line += f": {descripcion}"
            if ejemplo:
                line += f' Ej: {ejemplo}'
            lines.append(line)
        return "\n".join(lines)
