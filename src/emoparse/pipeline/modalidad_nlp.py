# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.modalidad_nlp
#
#  Pre-pass conservador y link-aware de modalidad referencial.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MODALIDADES = frozenset(
    {
        "designacion",
        "referencia_gramatical",
        "predicacion",
        "identificacion_inferencial",
    }
)

DEFAULT_MODEL = "es_core_news_md"
_FALLBACK_MODELS = ("es_core_news_md", "es_core_news_sm", "es_core_news_lg")

_PRONOUNS = frozenset(
    {
        "yo",
        "mi",
        "me",
        "conmigo",
        "mio",
        "mia",
        "mios",
        "mias",
        "nosotros",
        "nosotras",
        "nos",
        "nuestro",
        "nuestra",
        "nuestros",
        "nuestras",
        "vos",
        "tu",
        "te",
        "ti",
        "usted",
        "ustedes",
        "ud",
        "uds",
        "vosotros",
        "vosotras",
        "os",
        "su",
        "sus",
        "le",
        "les",
        "el",
        "ella",
        "ellos",
        "ellas",
        "esto",
        "eso",
        "aquello",
        "este",
        "ese",
        "aquel",
    }
)

_GRAMMATICAL_LINK_ORIGINS = frozenset({"coref", "deixis", "deixis_llm"})


@dataclass(frozen=True)
class ModalidadGuess:
    """Resultado del pre-pass. Solo `confident=True` se persiste sin LLM."""

    modalidad: str | None
    confident: bool
    method: str = "nlp"


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def _normalize(s: str) -> str:
    s = _strip_accents(s).lower()
    s = re.sub(r"\(.*?\)", "", s)
    return s.strip().strip("'\"").strip()


def _tokens(s: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", _normalize(s)) if t]


def _direct_lexical_match(marca: str, canonical_id: str) -> bool:
    """True solo ante coincidencia léxica clara entre target y superficie."""
    ref = _tokens(canonical_id.replace("_", " "))
    surface = set(_tokens(marca))
    return bool(ref) and all(tok in surface for tok in ref)


class ModalidadNLP:
    """Clasificador NLP conservador de una arista concreta."""

    def __init__(self, model: str | None = None) -> None:
        self._model_name = model or DEFAULT_MODEL
        self._nlp: Any | None = None
        self._loaded = False
        self._ok = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            import spacy  # type: ignore
        except Exception:
            self._ok = False
            return
        candidates = [self._model_name] + [m for m in _FALLBACK_MODELS if m != self._model_name]
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

    def classify(
        self,
        marca: str,
        frase: str = "",
        *,
        canonical_id: str = "",
        link_origin: str = "",
        deixis_tipo: str | None = None,
        funciones: str = "",
    ) -> ModalidadGuess:
        """Clasifica una arista; metadata aislada nunca basta para cerrar un caso."""
        del frase, deixis_tipo, funciones  # contexto reservado para reglas futuras verificadas

        norm = _normalize(marca)
        if not norm:
            return ModalidadGuess(None, confident=False)

        tokens_norm = _tokens(norm)
        direct_match = _direct_lexical_match(marca, canonical_id)
        grammatical_origin = str(link_origin or "") in _GRAMMATICAL_LINK_ORIGINS

        # Pronombre/deíctico puro: solo es seguro si el vínculo ya viene resuelto
        # por coref/deixis, o si la superficie coincide directamente con el target.
        if tokens_norm and all(t in _PRONOUNS for t in tokens_norm):
            if grammatical_origin or direct_match:
                return ModalidadGuess("referencia_gramatical", confident=True)
            return ModalidadGuess("referencia_gramatical", confident=False)

        if not self.available():
            return ModalidadGuess(None, confident=False)

        doc = self._nlp(marca)  # type: ignore[misc]
        toks = [t for t in doc if not t.is_space and not t.is_punct]
        if not toks:
            return ModalidadGuess(None, confident=False)

        pos = {t.pos_ for t in toks}
        has_propn = "PROPN" in pos
        has_noun = "NOUN" in pos
        finite_verbs = [
            t for t in toks if t.pos_ in ("VERB", "AUX") and t.morph.get("VerbForm") != ["Inf"]
        ]
        has_finite_verb = bool(finite_verbs)
        has_personal_finite_verb = any(
            any(person in {"1", "2"} for person in t.morph.get("Person")) for t in finite_verbs
        )
        nominal_subjects = [
            t
            for t in toks
            if getattr(t, "dep_", "") in {"nsubj", "csubj"} and t.pos_ in ("NOUN", "PROPN")
        ]
        only_pron = all(t.pos_ in ("PRON", "DET") for t in toks)

        if only_pron:
            if grammatical_origin or direct_match:
                return ModalidadGuess("referencia_gramatical", confident=True)
            return ModalidadGuess("referencia_gramatical", confident=False)

        # Designación directa: la superficie contiene de manera inequívoca el
        # target lexical. Esto permite, por ejemplo, núcleo nominal ↔ su canónico
        # sin extender la decisión al posesivo o a otros targets de la misma marca.
        if (has_propn or has_noun) and direct_match and not has_finite_verb:
            return ModalidadGuess("designacion", confident=True)

        # Flexión personal: solo se cierra automáticamente cuando el vínculo
        # proviene de una resolución gramatical upstream. Si fue linking LLM,
        # queda ambiguo aunque la forma verbal sea clara.
        if has_personal_finite_verb and not nominal_subjects:
            if grammatical_origin:
                return ModalidadGuess("referencia_gramatical", confident=True)
            return ModalidadGuess("referencia_gramatical", confident=False)

        # Una predicación verbal no se convierte automáticamente en predicacion:
        # la equivalencia evento/proceso/estado ↔ referente requiere decisión LLM.
        if has_finite_verb:
            return ModalidadGuess(None, confident=False)

        # SN sin coincidencia directa con el target: puede designar otro referente
        # o sostener identificación inferencial. Lo decide el LLM.
        if has_noun or has_propn:
            return ModalidadGuess("designacion", confident=False)

        return ModalidadGuess(None, confident=False)
