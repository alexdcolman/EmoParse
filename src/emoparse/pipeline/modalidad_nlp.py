# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.modalidad_nlp
#
#  Clasificación NLP (spaCy) de la modalidad referencial de una marca respecto de
#  su referente, y de la naturaleza del referente. Es el pre-pass barato de la
#  stage `modalidad`: resuelve con alta precisión los casos claros
#  (pronombres/verbos → referencia gramatical; nombres propios → designación) y
#  deja los ambiguos (SN de nombre común, que puede ser designación o epíteto
#  valorativo) para el LLM.
#
#  Ejes:
#    - modalidad:  cómo la marca refiere al referente
#        * designacion               → SN / nombre propio que nombra o categoriza
#        * referencia_gramatical      → deixis/morfología (pronombres, concordancia)
#        * identificacion_inferencial → se identifica por la actitud/valores
#    - naturaleza: qué tipo de referente
#        * persona | colectivo | institucion | objeto_proceso | otro
#
#  spaCy es opcional: si el modelo no está instalado, `available()` devuelve
#  False y la clasificación NLP se omite (la stage puede caer a LLM o dejar NULL).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

#: Etiquetas válidas (deben coincidir con el schema/persistencia).
MODALIDADES = frozenset({
    "designacion",
    "referencia_gramatical",
    "identificacion_inferencial",
})
NATURALEZAS = frozenset({
    "persona", "colectivo", "institucion", "objeto_proceso", "otro",
})

#: Modelo spaCy por defecto (ES). Se puede overridear al construir el clasificador.
DEFAULT_MODEL = "es_core_news_md"
_FALLBACK_MODELS = ("es_core_news_md", "es_core_news_sm", "es_core_news_lg")

#: Pronombres/determinantes deícticos frecuentes (respaldo si el POS falla).
_PRONOUNS = frozenset({
    "yo", "mi", "me", "conmigo", "mio", "mia", "mios", "mias",
    "nosotros", "nosotras", "nos", "nuestro", "nuestra", "nuestros", "nuestras",
    "vos", "tu", "te", "ti", "usted", "ustedes", "ud", "uds",
    "vosotros", "vosotras", "os", "su", "sus", "le", "les", "el", "ella",
    "ellos", "ellas", "esto", "eso", "aquello", "este", "ese", "aquel",
})


@dataclass(frozen=True)
class ModalidadGuess:
    """Resultado de la clasificación NLP de una marca.

    `confident=True` significa que el caso es claro y no necesita LLM.
    `modalidad`/`naturaleza` pueden ser None si no se pudo determinar.
    """
    modalidad: str | None
    naturaleza: str | None
    confident: bool
    method: str = "nlp"


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def _normalize(s: str) -> str:
    s = _strip_accents(s).lower()
    s = re.sub(r"\(.*?\)", "", s)          # quita parentéticos
    return s.strip().strip("'\"").strip()


class ModalidadNLP:
    """Clasificador NLP perezoso basado en spaCy (ES).

    Carga el modelo la primera vez que se usa. Si spaCy o el modelo no están
    disponibles, queda inactivo (`available()` → False) y `classify` devuelve un
    guess vacío no confiable.
    """

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or DEFAULT_MODEL
        self._nlp: Any | None = None
        self._loaded = False
        self._ok = False

    # ── Carga perezosa ───────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            import spacy  # type: ignore
        except Exception:
            self._ok = False
            return
        candidates = [self._model_name] + [
            m for m in _FALLBACK_MODELS if m != self._model_name
        ]
        for name in candidates:
            try:
                self._nlp = spacy.load(name, disable=["lemmatizer"])
                self._model_name = name
                self._ok = True
                return
            except Exception:
                continue
        self._ok = False

    def available(self) -> bool:
        self._load()
        return self._ok

    # ── Clasificación ────────────────────────────────────────────────────────

    def classify(self, marca: str, frase: str = "") -> ModalidadGuess:
        """Clasifica la marca (opcionalmente en el contexto de su frase)."""
        norm = _normalize(marca)
        if not norm:
            return ModalidadGuess(None, None, confident=False)

        # Respaldo léxico barato: marca compuesta solo por pronombres/deícticos.
        tokens_norm = [t for t in re.split(r"[^a-z0-9]+", norm) if t]
        if tokens_norm and all(t in _PRONOUNS for t in tokens_norm):
            return ModalidadGuess("referencia_gramatical", None, confident=True)

        if not self.available():
            # Sin spaCy: solo lo resuelto por el respaldo léxico es confiable.
            return ModalidadGuess(None, None, confident=False)

        doc = self._nlp(marca)  # type: ignore[misc]
        toks = [t for t in doc if not t.is_space and not t.is_punct]
        if not toks:
            return ModalidadGuess(None, None, confident=False)

        pos = {t.pos_ for t in toks}
        has_propn = "PROPN" in pos
        has_noun = "NOUN" in pos
        has_finite_verb = any(
            t.pos_ in ("VERB", "AUX") and t.morph.get("VerbForm") != ["Inf"]
            for t in toks
        )
        only_pron = all(t.pos_ in ("PRON", "DET") for t in toks)

        # Naturaleza vía NER (si el modelo la trae).
        naturaleza = self._naturaleza_ner(doc, toks)

        # 1) Pronombres/determinantes → referencia gramatical (deixis).
        if only_pron:
            return ModalidadGuess("referencia_gramatical", naturaleza, confident=True)

        # 2) Nombre propio como núcleo → designación (caso claro).
        if has_propn and not has_finite_verb:
            return ModalidadGuess(
                "designacion", naturaleza or "persona", confident=True
            )

        # 3) Verbo finito sin núcleo nominal → referencia predicativa/gramatical.
        if has_finite_verb and not has_noun and not has_propn:
            return ModalidadGuess("referencia_gramatical", naturaleza, confident=True)

        # 4) SN de nombre común: AMBIGUO (designación vs epíteto valorativo).
        #    Guess tentativo = designación, pero NO confiable → lo decide el LLM.
        if has_noun:
            nat = naturaleza or self._naturaleza_por_numero(toks)
            return ModalidadGuess("designacion", nat, confident=False)

        return ModalidadGuess(None, naturaleza, confident=False)

    # ── Helpers de naturaleza ────────────────────────────────────────────────

    @staticmethod
    def _naturaleza_ner(doc: Any, toks: list) -> str | None:
        labels = {getattr(e, "label_", "") for e in getattr(doc, "ents", [])}
        if "PER" in labels:
            return "persona"
        if "ORG" in labels:
            return "institucion"
        return None

    @staticmethod
    def _naturaleza_por_numero(toks: list) -> str | None:
        """Heurística débil: SN plural → colectivo; singular → sin decidir."""
        for t in toks:
            if t.pos_ in ("NOUN", "PROPN"):
                if t.morph.get("Number") == ["Plur"]:
                    return "colectivo"
                break
        return None
