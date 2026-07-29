# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.discurso_presidencial
#
#  Género built-in: discurso presidencial / discurso político clásico.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import Genre


#: Roles veronianos del discurso político. El género presidencial es siempre
#: político: `enunciatarios_por_tipo` tiene una sola entrada, que se usa
#: cualquiera sea el subtipo concreto que devuelva `metadata`.
_ROLES_POLITICOS: tuple[str, ...] = (
    "prodestinatario",
    "paradestinatario",
    "contradestinatario",
)


def get_genre() -> Genre:
    """Factory expuesta como entry-point en pyproject.toml."""
    return Genre(
        genre_id="discurso_presidencial",
        display_name="Discurso presidencial",
        unit="frase",
        context_unit="discurso",
        technoparse=False,
        enunciation_roles=_ROLES_POLITICOS,
        enunciatarios_por_tipo={"politico": _ROLES_POLITICOS},
        roles_descripciones={
            "prodestinatario": "el ya convencido, base electoral que comparte "
                "la creencia; el discurso refuerza la comunión.",
            "paradestinatario": "el indeciso al que se busca persuadir con "
                "argumentos, sin presuponer adhesión.",
            "contradestinatario": "el adversario excluido del colectivo de "
                "identificación; se lo ataca o refuta.",
        },
        models={},
        batch_size={
            "actors": 1,
            "emotions": 1,
            "emotions_pass2": 1,
            "deixis": 5,
            "semas": 2,
            "characterizer": 1,
            "actants": 1,
            "judge": 1,
        },
        summarizer=True,
        prompt_overrides={},
    )
