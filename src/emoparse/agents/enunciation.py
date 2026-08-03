# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.agents.enunciation
#
#  Agente de análisis enunciativo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd

from emoparse.agents.base import BaseAgent
from emoparse.core.backend.base import LLMBackend
from emoparse.core.prompts import enunciation as prompts
from emoparse.core.schemas import AuditorioSchema, EnunciacionSchema, EnunciadorSchema
from emoparse.core.text import strip_accents_lower
from emoparse.genres.base import Genre
from emoparse.genres.schema_factory import enunciacion_schema

#: Tope de indicadores lingüísticos por rol inyectados en el prompt. Acota el
#: tamaño del bloque de roles para no comer el margen de completion en el
#: género tuit, donde el prompt de enunciation ya vive cerca del límite.
_MAX_INDICADORES_POR_ROL = 3


class EnunciationAgent(BaseAgent[EnunciacionSchema]):
    """Identifica la estructura enunciativa de un discurso.

    Procesa una unidad completa por llamada y agrega estas columnas:

        - `enunciador`
        - `enunciador_justificacion`
        - `enunciatarios` (JSON serializado)
        - `auditorio` (JSON serializado)
        - `colectivos_identificacion` (JSON serializado)

    Los roles enunciativos válidos dependen del tipo de discurso: el schema
    los acota al universo del género (`enunciation_roles`), y el prompt de
    cada discurso lista solo los del tipo identificado por `metadata` (más los
    transversales del dispositivo), con sus indicadores lingüísticos
    orientativos. Un filtro post-hoc descarta los enunciatarios cuyo rol no
    corresponde a ese tipo.
    """

    NAME = "enunciation"
    # Schema por defecto. Si se pasa genre, la instancia puede
    # reemplazarlo por una versión restringida a los roles válidos
    # de ese género discursivo.
    SCHEMA = EnunciacionSchema
    OUTPUT_COLUMNS = (
        "enunciador",
        "enunciador_justificacion",
        "enunciatarios",
        "auditorio",
        "colectivos_identificacion",
    )

    def __init__(
        self,
        backend: LLMBackend,
        heuristicas: str | None = None,
        colectivos: dict[str, Any] | None = None,
        destinatarios_indicadores: dict[str, Any] | None = None,
        tipos_discurso: dict[str, Any] | None = None,
        retry_config: Any | None = None,
        genre: Genre | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            heuristicas: Reglas heurísticas para identificación de
                estructura enunciativa. Si None, no se inyectan en el
                system prompt.
            colectivos: Ontología de colectivos de identificación por tipo de
                discurso. Si None, no se piden colectivos.
            destinatarios_indicadores: Indicadores lingüísticos de destinatario
                por tipo de discurso para ESTE género (`{"transversales": ...,
                "tipos": {...}}`). Se inyectan en el prompt como pistas
                orientativas del tipo identificado. Si None, el bloque de
                roles se arma solo con las descripciones.
            tipos_discurso: Diccionario canónico de `knowledge/tipos_discurso.json`.
                Sus definiciones de destinatarios tienen prioridad sobre los
                fallbacks declarados por el género.
            retry_config: Política de reintentos ante errores transitorios.
            genre: Configuración de género discursivo. Restringe los roles
                enunciativos válidos del schema y define, por tipo de discurso,
                qué roles se listan en el prompt (`enunciatarios_por_tipo`,
                `roles_transversales`, `roles_descripciones`).
        """
        self._heuristicas = heuristicas
        self._colectivos_str = _format_colectivos(colectivos)
        self._clases_validas = _allowed_colectivo_clases(colectivos)
        self._indicadores = destinatarios_indicadores or {}
        self._tipos_discurso = tipos_discurso or {}
        self._genre = genre

        # Si se define genre, reemplazar el schema antes de llamar a
        # super().__init__, para que la clase base use la versión correcta
        # durante la inicialización.
        if genre is not None:
            self.SCHEMA = enunciacion_schema(genre)  # type: ignore[misc]

        super().__init__(backend, retry_config=retry_config)

    # ── Hooks de BaseAgent ───────────────────────────────────────────────────

    def _build_system(self) -> str:
        template = "enunciation_system"
        if self._genre is not None:
            template = self._genre.prompt_overrides.get("enunciation", template)
        return prompts.render_system(
            heuristicas=self._heuristicas,
            colectivos=self._colectivos_str or None,
            reglas_enunciador=_reglas_enunciador_genero(self._genre),
            reglas_auditorio=_reglas_auditorio_genero(self._genre),
            template=template,
        )

    def _build_user(self, row: pd.Series) -> str:
        codigo = str(row["codigo"])
        resumen = _resolve_resumen(row)
        fragmentos = _extract_fragments(row)
        enunciador = _opt_cell(row, "enunciador_fijado")
        repertorio = _opt_cell(row, "repertorio_kb")
        roles_block = self._roles_block(_opt_cell(row, "tipo_discurso"))
        return prompts.render_user(
            codigo=codigo,
            resumen=resumen,
            fragmentos=fragmentos,
            enunciador=enunciador or None,
            repertorio=repertorio or None,
            bio=_opt_cell(row, "autor_bio") or None,
            adjuntos=_opt_cell(row, "adjuntos") or None,
            roles_block=roles_block or None,
            contexto_hilo=_opt_cell(row, "contexto_hilo") or None,
            contexto_genero=_opt_cell(row, "contexto_genero") or None,
        )

    def _map_to_columns(
        self,
        parsed: EnunciacionSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        # Serialización JSON para mantener compatibilidad tabular.
        # ensure_ascii=False preserva texto en español.
        permitidos = self._roles_permitidos(_opt_cell(row, "tipo_discurso"))
        enunciatarios: list[dict[str, Any]] = []
        auditorio_desde_vocativos: list[dict[str, Any]] = []
        for entrada in parsed.enunciatarios:
            if (
                es_rol_enunciativo(entrada.actor)
                or es_destinacion_sin_posicion(entrada.actor, entrada.tipo)
                or not _rol_admitido(entrada.tipo, permitidos)
            ):
                continue
            if _es_auditorio_situacional(
                entrada.actor,
                entrada.justificacion,
                entrada.tipo,
            ):
                auditorio_desde_vocativos.append(
                    AuditorioSchema(
                        actor=entrada.actor,
                        justificacion=entrada.justificacion,
                    ).model_dump()
                )
                continue
            enunciatarios.append(entrada.model_dump())
        enunciatarios_json = json.dumps(enunciatarios, ensure_ascii=False)

        # Auditorio: predeterminado desde el dispositivo si la fila lo trae;
        # si no, se combina el auditorio inferido con los vocativos que el LLM
        # haya clasificado erróneamente como posiciones de destinación.
        auditorio_fijo = _opt_cell(row, "auditorio_fijo")
        if auditorio_fijo:
            try:
                auditorio = json.loads(auditorio_fijo)
            except json.JSONDecodeError:
                auditorio = []
        else:
            auditorio = [
                a.model_dump() for a in parsed.auditorio if not es_rol_enunciativo(a.actor)
            ]
            auditorio.extend(auditorio_desde_vocativos)
            auditorio = _dedupe_referentes(auditorio)
            if not auditorio and self._genre is not None and self._genre.auditorio_oral:
                auditorio = [_auditorio_oral_fallback(row)]
        auditorio_json = json.dumps(auditorio, ensure_ascii=False)

        # Validación post-hoc de la clase de colectivo contra la ontología:
        # se descartan las clases no reconocidas (el schema deja `clase` libre).
        colectivos = [
            c.model_dump()
            for c in parsed.colectivos
            if not self._clases_validas or c.clase.strip().lower() in self._clases_validas
        ]
        colectivos_json = json.dumps(colectivos, ensure_ascii=False)
        enunciador = _opt_cell(row, "enunciador_fijado") or parsed.enunciador.actor
        enunciador_just = (
            _opt_cell(row, "enunciador_fijado_justificacion") or parsed.enunciador.justificacion
        )
        enunciador_validado = EnunciadorSchema(
            actor=enunciador,
            justificacion=enunciador_just,
        )
        return {
            "enunciador": enunciador_validado.actor,
            "enunciador_justificacion": enunciador_validado.justificacion,
            "enunciatarios": enunciatarios_json,
            "auditorio": auditorio_json,
            "colectivos_identificacion": colectivos_json,
        }

    # ── Roles por tipo de discurso ───────────────────────────────────────────

    def _roles_permitidos(self, tipo_discurso: str) -> set[str]:
        """Roles enunciativos válidos para el tipo, normalizados para comparar.

        Vacío si el género no discrimina roles por tipo: en ese caso no se
        filtra (cualquier rol del schema es válido).
        """
        if self._genre is None or not self._genre.enunciatarios_por_tipo:
            return set()
        return {_norm_rol(r) for r in self._genre.roles_para_tipo(tipo_discurso or None)}

    def _roles_block(self, tipo_discurso: str) -> str:
        """Bloque de roles válidos para este discurso, con indicadores.

        Lista cada rol admisible con su descripción breve y, si el género
        aporta indicadores lingüísticos para el tipo, un puñado de pistas
        orientativas. Vacío si el género no discrimina roles por tipo (el
        system prompt del género ya no enumera roles fijos, pero sin genre
        no hay lista que ofrecer y el bloque se omite)."""
        if self._genre is None or not self._genre.enunciatarios_por_tipo:
            return ""
        roles = self._genre.roles_para_tipo(tipo_discurso or None)
        if not roles:
            return ""
        descripciones = self._descripciones_roles(tipo_discurso, roles)
        indicadores = self._indicadores_por_rol(tipo_discurso)
        lineas = [
            "ROLES ENUNCIATIVOS VÁLIDOS PARA ESTE DISCURSO (asigná a cada "
            "destinatario uno de estos `tipo`). Las definiciones provienen "
            "del diccionario canónico de tipos de discurso; los indicadores "
            "son solo pistas orientativas.",
        ]
        if set(roles) == _ROLES_POLITICOS:
            lineas.extend(
                [
                    "REGLA POLÍTICA CENTRAL:",
                    "- Un vocativo o la presencia física en el acto identifica "
                    "el AUDITORIO, no demuestra por sí sola una posición pro, "
                    "para o contra.",
                    "- prodestinatario exige evidencia de valores, creencias o "
                    "adhesión compartidos.",
                    "- paradestinatario exige una posición neutral o indecisa a "
                    "la que se busca persuadir.",
                    "- contradestinatario exige un adversario u oposición "
                    "construidos explícitamente.",
                ]
            )
        for rol in roles:
            desc = descripciones.get(rol, "")
            lineas.append(f"- {rol}" + (f": {desc}" if desc else ""))
            pistas = (indicadores.get(rol) or [])[:_MAX_INDICADORES_POR_ROL]
            if pistas:
                lineas.append("    Indicadores: " + "; ".join(pistas))
        return "\n".join(lineas)

    def _descripciones_roles(
        self,
        tipo_discurso: str,
        roles: tuple[str, ...],
    ) -> dict[str, str]:
        """Descripciones canónicas desde `tipos_discurso.json`, con fallback."""
        candidatos: list[tuple[str, dict[str, Any]]] = []
        for nombre, info in self._tipos_discurso.items():
            if not isinstance(info, dict):
                continue
            defs = info.get("tipos_de_destinatarios")
            if isinstance(defs, dict):
                candidatos.append((str(nombre), defs))

        tipo_norm = _norm_rol(tipo_discurso)
        clave_genero = self._tipo_key(tipo_discurso)
        clave_norm = _norm_rol(clave_genero or "")
        seleccion: dict[str, Any] | None = None
        for nombre, defs in candidatos:
            nombre_norm = _norm_rol(nombre)
            if nombre_norm == tipo_norm or (clave_norm and clave_norm in nombre_norm):
                seleccion = defs
                break
        if seleccion is None:
            for _, defs in candidatos:
                if all(rol in defs for rol in roles):
                    seleccion = defs
                    break

        fallback = self._genre.roles_descripciones if self._genre else {}
        return {rol: str((seleccion or {}).get(rol) or fallback.get(rol) or "") for rol in roles}

    def _indicadores_por_rol(self, tipo_discurso: str) -> dict[str, list[str]]:
        """Mapea rol → indicadores para el tipo identificado (transversales
        siempre; los del tipo solo si el tipo matchea una entrada del mapa)."""
        out: dict[str, list[str]] = {}
        transversales = self._indicadores.get("transversales")
        if isinstance(transversales, dict):
            for rol, pistas in transversales.items():
                if isinstance(pistas, list):
                    out[rol] = [str(p) for p in pistas]
        clave = self._tipo_key(tipo_discurso)
        tipos = self._indicadores.get("tipos")
        if clave and isinstance(tipos, dict) and isinstance(tipos.get(clave), dict):
            for rol, pistas in tipos[clave].items():
                if isinstance(pistas, list):
                    out[rol] = [str(p) for p in pistas]
        return out

    def _tipo_key(self, tipo_discurso: str) -> str | None:
        """Clave de `enunciatarios_por_tipo` que corresponde al tipo, o None.

        None cuando el tipo no matchea y el género tiene varias entradas (se
        cae a la unión de roles y no se cargan indicadores específicos, para
        no confundir). Con una sola entrada, se usa esa."""
        if self._genre is None:
            return None
        mapa = self._genre.enunciatarios_por_tipo
        if not mapa:
            return None
        norm_keys = {_norm_rol(k): k for k in mapa}
        clave = _norm_rol(tipo_discurso)
        if clave in norm_keys:
            return norm_keys[clave]
        if len(mapa) == 1:
            return next(iter(mapa))
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  Sub-paso de identificación del enunciador
# ══════════════════════════════════════════════════════════════════════════════


class EnunciatorIdAgent(BaseAgent[EnunciadorSchema]):
    """Identifica solo el enunciador de un discurso, normalizado.

    Sub-paso previo a la identificación del resto de la estructura
    enunciativa: devuelve la denominación mínima del enunciador (nombre y
    apellido, o denominación institucional breve) para que la stage la fije
    y la propague al prompt principal y al canónico. Prompt mínimo, apto
    para un modelo chico (configurable vía `pipeline.stages.enunciator_id`).
    Agrega las columnas `enunciador_fijado` y
    `enunciador_fijado_justificacion`.
    """

    NAME = "enunciator_id"
    SCHEMA = EnunciadorSchema
    OUTPUT_COLUMNS = (
        "enunciador_fijado",
        "enunciador_fijado_justificacion",
    )

    def __init__(
        self,
        backend: LLMBackend,
        heuristicas: str | None = None,
        retry_config: Any | None = None,
    ) -> None:
        """
        Args:
            backend: Backend LLM utilizado para generación estructurada.
            heuristicas: Reglas heurísticas de identificación del enunciador.
        """
        self._heuristicas = heuristicas
        super().__init__(backend, retry_config=retry_config)

    def _build_system(self) -> str:
        return prompts.render_enunciator_id_system(heuristicas=self._heuristicas)

    def _build_user(self, row: pd.Series) -> str:
        return prompts.render_user(
            codigo=str(row["codigo"]),
            resumen=_resolve_resumen(row),
            fragmentos=_extract_fragments(row),
            contexto_genero=_opt_cell(row, "contexto_genero") or None,
        )

    def _map_to_columns(
        self,
        parsed: EnunciadorSchema,
        row: pd.Series,
    ) -> dict[str, Any]:
        return {
            "enunciador_fijado": parsed.actor,
            "enunciador_fijado_justificacion": parsed.justificacion,
        }


def _reglas_enunciador_genero(genre: Genre | None) -> str | None:
    """Reglas compuestas desde el descriptor, sin seleccionar por genre_id."""
    if genre is None or not genre.enunciador_from_handle:
        return None
    return (
        "- El enunciador viene ya identificado en el mensaje del usuario. "
        "Devolvelo exactamente como aparece en `enunciador`, sin "
        "reidentificarlo ni reformularlo."
    )


def _reglas_auditorio_genero(genre: Genre | None) -> str | None:
    """Reglas de auditorio derivadas del modo declarado por el género."""
    if genre is None:
        return None
    if genre.auditorio_predeterminado:
        return (
            "- El auditorio se completa de forma determinista desde el "
            "dispositivo. No lo infieras: devolvé una lista vacía en `auditorio`."
        )
    if genre.auditorio_oral:
        return (
            "- Es una situación oral: salvo ausencia total de indicios, devolvé "
            "el público presente (por ejemplo, 'los asistentes al acto'). "
            "Los vocativos y fórmulas como 'estamos reunidos' son evidencia "
            "del auditorio, no de adhesión política."
        )
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de referentes vs. roles enunciativos
# ══════════════════════════════════════════════════════════════════════════════

#: Etiquetas de rol enunciativo que nunca son un referente válido. Los agentes
#: deben devolver referentes concretos; estas etiquetas se filtran post-hoc
#: como defensa. "audiencia ambiente" queda fuera de la lista: es el único rol
#: admisible como actor, por ser un público indeterminado por naturaleza.
_ROL_LABELS = frozenset(
    {
        "enunciador",
        "enunciatario",
        "enunciatarios",
        "autor",
        "autor del post",
        "autor post",
        "autora",
        "la cuenta",
        "prodestinatario",
        "paradestinatario",
        "contradestinatario",
        "destinatario",
        "destinatarios",
        "destinatario mencionado",
        "destinatario directo",
        "actor",
        "auditorio",
        # Roles por tipo de discurso del post (nunca son el referente concreto).
        "lector ciudadano",
        "instancia blanco",
        "fuente referente",
        "ciudadano usuario",
        "comunidad interna",
        "rendicion cuentas",
        "rendicion de cuentas",
        "comunidad sentido",
        "comunidad de sentido",
        "no iniciado",
        "blanco burla",
        "blanco de la burla",
        "circulo afectivo",
        "autodestinatario",
        "testigo indeseado",
        "enunciatario target",
        "comunidad marca",
        "comunidad de marca",
        "prescriptor amplificador",
    }
)


#: Roles cuya destinación se ordena alrededor de creencias y valores: el
#: prodestinatario presupone las compartidas, el contradestinatario las
#: opuestas y el paradestinatario su suspensión. El actor de estos roles
#: tiene que nombrar esa posición, no la audiencia técnica de la cuenta.
_ROLES_DE_CREENCIA = frozenset(
    {
        "prodestinatario",
        "paradestinatario",
        "contradestinatario",
    }
)

#: Núcleos que designan a la audiencia por el dispositivo (los seguidores de
#: una cuenta, el público de la plataforma) y no por lo que cree.
_AUDIENCIA_DISPOSITIVO_RE = re.compile(
    r"^(?:el\s+resto\s+de\s+)?(?:l[oa]s\s+|el\s+|la\s+|todos\s+los\s+)?"
    r"(?:seguidor(?:e?s)?|followers|audiencia|publico|lector(?:e?s|as)?|"
    r"usuari[oa]s?|comunidad|gente|espectador(?:e?s|as)?|argentinos?|"
    r"ciudadania|sociedad|pueblo|nacion|poblacion)\b"
)

#: Marca de que la audiencia viene calificada por una posición ("seguidores
#: que comparten el rechazo al ajuste", "público afín al gobierno").
_CALIFICACION_RE = re.compile(
    r"\b(?:que|quienes|afin(?:es)?|contrari[oa]s|partidari[oa]s|adherentes|"
    r"critic[oa]s|a\s+favor|en\s+contra|opuest[oa]s|convencid[oa]s)\b"
)


_ROLES_POLITICOS = frozenset({"prodestinatario", "paradestinatario", "contradestinatario"})
_AUDITORIO_SITUACIONAL_RE = re.compile(
    r"\b(?:vocativ[oa]s?|presentes?|asistentes?|acto|ceremonia|reunidos?|"
    r"autoridades?|veteranos?|familiares?|señoras y señores)\b",
    re.IGNORECASE,
)
_POSICION_POLITICA_RE = re.compile(
    r"\b(?:comparte[n]? (?:los )?valores|comparte[n]? (?:las )?creencias|"
    r"base electoral|adherentes?|simpatizantes?|indecisos?|neutrales?|"
    r"persuadir|oposici[oó]n|adversari[oa]s?|contraposici[oó]n|"
    r"polarizaci[oó]n)\b",
    re.IGNORECASE,
)


def _es_auditorio_situacional(actor: Any, justificacion: Any, tipo: Any) -> bool:
    """Detecta vocativos/públicos presentes mal puestos como rol político."""
    if _norm_rol(tipo) not in _ROLES_POLITICOS:
        return False
    texto = f"{actor} {justificacion}"
    return bool(_AUDITORIO_SITUACIONAL_RE.search(texto) and not _POSICION_POLITICA_RE.search(texto))


def _dedupe_referentes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplica entradas tabulares por actor normalizado, preservando orden."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = " ".join(strip_accents_lower(item.get("actor", "")).split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _auditorio_oral_fallback(row: pd.Series) -> dict[str, str]:
    """Auditorio mínimo para un género oral cuando el LLM devuelve vacío."""
    contenido = _opt_cell(row, "contenido")
    texto_norm = strip_accents_lower(contenido)
    if "malvinas" in texto_norm and ("veterano" in texto_norm or "caidos" in texto_norm):
        actor = (
            "los presentes en el acto conmemorativo por el Día del Veterano "
            "y de los Caídos en la Guerra de Malvinas"
        )
    elif "conmemor" in texto_norm:
        actor = "los presentes en el acto conmemorativo"
    elif "acto" in texto_norm or "ceremonia" in texto_norm:
        actor = "los presentes en el acto"
    else:
        actor = "los presentes en la situación de enunciación"
    return AuditorioSchema(
        actor=actor,
        justificacion=(
            "Los vocativos y las marcas de reunión identifican al público "
            "presente en la situación oral."
        ),
    ).model_dump()


def _norm_rol(valor: Any) -> str:
    """Normaliza un identificador de rol/tipo para comparar (sin acentos)."""
    return strip_accents_lower(valor).strip().replace("-", "_")


def _rol_admitido(tipo: Any, permitidos: set[str]) -> bool:
    """True si el rol está entre los permitidos del tipo (o no hay filtro)."""
    if not permitidos:
        return True
    return _norm_rol(tipo) in permitidos


def es_rol_enunciativo(actor: Any) -> bool:
    """True si `actor` es una etiqueta de rol y no un referente concreto."""
    norm = str(actor or "").strip().lower().replace("_", " ")
    norm = " ".join(norm.split())
    return norm in _ROL_LABELS


def es_destinacion_sin_posicion(actor: Any, tipo: Any) -> bool:
    """True si un destinatario de creencia se nombra solo por el dispositivo.

    Los tres roles veronianos se ordenan alrededor de creencias y valores,
    así que "seguidores de la cuenta" o "los usuarios" no los identifican:
    esa es la audiencia técnica, que ya se registra en el auditorio y en
    `audiencia_ambiente`. Se admite la audiencia calificada por su posición
    ("seguidores que comparten el rechazo al ajuste"). Los demás roles no
    se filtran por este criterio.
    """
    rol = strip_accents_lower(tipo).strip().replace("-", "_")
    if rol not in _ROLES_DE_CREENCIA:
        return False
    norm = " ".join(strip_accents_lower(actor).split())
    if not _AUDIENCIA_DISPOSITIVO_RE.match(norm):
        return False
    return not _CALIFICACION_RE.search(norm)


def _opt_cell(row: pd.Series, key: str) -> str:
    """String de una celda opcional de la fila: ausente/None/NaN → ''."""
    value = row.get(key)
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def format_repertorio_kb(entry: dict[str, Any] | None) -> str:
    """Formatea la entrada de la KB de enunciación de un enunciador.

    Devuelve texto con los colectivos de identificación conocidos, apto para
    inyectarse en el prompt principal; string vacío si no hay entrada. Los
    enunciatarios no se inyectan: varían demasiado entre discursos para
    servir de contexto (aunque la KB conserve entradas viejas).
    """
    if not isinstance(entry, dict) or not entry:
        return ""
    lines: list[str] = []
    colectivos = entry.get("colectivos") or []
    if isinstance(colectivos, list) and colectivos:
        lines.append("COLECTIVOS DE IDENTIFICACIÓN CONOCIDOS:")
        for c in colectivos:
            if not isinstance(c, dict):
                continue
            nombre = str(c.get("nombre") or "").strip()
            clase = str(c.get("clase") or "").strip()
            if nombre:
                lines.append(f"  - {nombre}" + (f" ({clase})" if clase else ""))
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de colectivos de identificación
# ══════════════════════════════════════════════════════════════════════════════


def _format_colectivos(colectivos: dict[str, Any] | None) -> str:
    """Formatea la ontología de colectivos por tipo de discurso para el prompt."""
    if not colectivos:
        return ""
    lines: list[str] = []
    for tipo, clases in colectivos.items():
        if tipo == "version" or not isinstance(clases, dict):
            continue
        lines.append(f"* {tipo.upper()}:")
        for clase, info in clases.items():
            desc = info.get("descripcion", "") if isinstance(info, dict) else ""
            ejemplo = info.get("ejemplo", "") if isinstance(info, dict) else ""
            linea = f"    - {clase}"
            if desc:
                linea += f": {desc}"
            if ejemplo:
                linea += f" Ej: {ejemplo}"
            lines.append(linea)
    return "\n".join(lines)


def _allowed_colectivo_clases(colectivos: dict[str, Any] | None) -> set[str]:
    """Conjunto de clases de colectivo válidas (unión sobre tipos de discurso)."""
    allowed: set[str] = set()
    if not colectivos:
        return allowed
    for tipo, clases in colectivos.items():
        if tipo == "version" or not isinstance(clases, dict):
            continue
        for clase in clases:
            allowed.add(str(clase).strip().lower())
    return allowed


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers de resolución de contexto textual
# ══════════════════════════════════════════════════════════════════════════════

#: Límite máximo de caracteres usado como fallback cuando no existe
#: un resumen previo disponible.
_CONTENIDO_FALLBACK_CHAR_LIMIT = 4000


def _resolve_resumen(row: pd.Series) -> str:
    """Obtiene el resumen textual principal del discurso.

    Prioriza la columna `resumen_global`. Si no está disponible,
    utiliza una versión truncada de `contenido` como fallback.
    """
    raw = row.get("resumen_global")
    if raw is not None and not (isinstance(raw, float) and pd.isna(raw)):
        text = str(raw).strip()
        if text and text.lower() not in ("none", "nan"):
            return text

    contenido = str(row.get("contenido", ""))
    if len(contenido) > _CONTENIDO_FALLBACK_CHAR_LIMIT:
        return contenido[:_CONTENIDO_FALLBACK_CHAR_LIMIT] + "..."
    return contenido


def _extract_fragments(row: pd.Series) -> str:
    """Obtiene fragmentos representativos del discurso.

    Si `resumen_fragmentos` contiene una lista válida, devuelve una
    selección formateada. En caso contrario, usa un fragmento truncado
    de `contenido` como fallback.
    """
    raw = row.get("resumen_fragmentos", "[]")
    try:
        frags = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        frags = []
    if isinstance(frags, list) and frags:
        return "\n\n".join(f"- {f}" for f in frags[:5])
    contenido = str(row.get("contenido", ""))
    return contenido[:1000] + ("..." if len(contenido) > 1000 else "")
