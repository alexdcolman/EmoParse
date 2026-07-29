# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.genres.tuit
#
#  Género built-in: tuit / post de red social (discurso nativo digital).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.genres.base import Genre


#: Roles del dispositivo, presentes potencialmente en cualquier tipo de post:
#: la cuenta interpelada técnicamente vía @ y el público indeterminado del
#: archivo buscable. Se cruzan con los roles del tipo de discurso.
_ROLES_TRANSVERSALES: tuple[str, ...] = (
    "destinatario_mencionado",
    "audiencia_ambiente",
)

#: Roles de destinación por tipo de discurso del post. La escena enunciativa
#: se construye cruzando estos con los transversales: un post político tiene
#: pro/para/contradestinatario y, además, destinatario mencionado y audiencia
#: ambiente. Las tipologías se apoyan en Verón (político), Charaudeau
#: (periodístico e institucional) y bibliografía específica de audiencias en
#: redes; los identificadores son estables (los consumen el schema y el filtro
#: post-hoc de enunciation).
_ENUNCIATARIOS_POR_TIPO: dict[str, tuple[str, ...]] = {
    "politico": (
        "prodestinatario",
        "paradestinatario",
        "contradestinatario",
    ),
    "periodistico_informativo": (
        "lector_ciudadano",
        "instancia_blanco",
        "fuente_referente",
    ),
    "institucional": (
        "ciudadano_usuario",
        "comunidad_interna",
        "rendicion_cuentas",
    ),
    "humor_meme": (
        "comunidad_sentido",
        "no_iniciado",
        "blanco_burla",
    ),
    "personal_cotidiano": (
        "circulo_afectivo",
        "autodestinatario",
        "testigo_indeseado",
    ),
    "promocional": (
        "enunciatario_target",
        "comunidad_marca",
        "prescriptor_amplificador",
    ),
    # `otro` no aporta roles propios: quedan solo los transversales.
    "otro": (),
}

#: Descripción breve por rol (transversales + por tipo), para el prompt.
_ROLES_DESCRIPCIONES: dict[str, str] = {
    "destinatario_mencionado": "cuenta concreta interpelada técnicamente por el "
        "dispositivo (@mención, respuesta directa); puede superponerse con "
        "cualquier otro rol.",
    "audiencia_ambiente": "público indeterminado del archivo buscable ante el "
        "cual el post también se enuncia (hashtags de alcance amplio, "
        "apelaciones genéricas, sin destinatario individualizado).",
    "prodestinatario": "el ya convencido que comparte la creencia; el post "
        "refuerza la comunión (nosotros inclusivo, consignas, afiliación).",
    "paradestinatario": "el indeciso al que se busca persuadir con argumentos o "
        "datos, sin presuponer adhesión.",
    "contradestinatario": "el adversario excluido del colectivo de "
        "identificación; se lo ataca, ironiza o refuta.",
    "lector_ciudadano": "el público ciudadano amplio al que informa la nota "
        "(instancia-público), sin vocativo, en registro informativo.",
    "instancia_blanco": "el destinatario calculado por la estrategia editorial "
        "del medio; se reconoce por el ángulo de la nota más que por marcas.",
    "fuente_referente": "el actor citado o etiquetado como fuente o protagonista "
        "de la noticia, interpelado o mencionado.",
    "ciudadano_usuario": "el interlocutor válido o beneficiario del servicio o la "
        "información (trámite, cortesía institucional).",
    "comunidad_interna": "miembros, afiliados o funcionarios de la propia "
        "institución (pertenencia interna, áreas, jerarquía).",
    "rendicion_cuentas": "prensa y opinión pública que vigilan la legitimidad "
        "institucional (transparencia, balance de gestión, aclaraciones).",
    "comunidad_sentido": "los iniciados que decodifican la referencia o el "
        "código (jerga, intertextualidad sin glosa, formato de meme).",
    "no_iniciado": "el lector que queda fuera del código y no entiende el "
        "chiste; se infiere por contraste, sin marca positiva.",
    "blanco_burla": "el destinatario-objeto de la ironía cuando el humor es "
        "agresivo (mención, parodia, apodo despectivo).",
    "circulo_afectivo": "el destinatario íntimo imaginado (amigos, conocidos, "
        "seguidores cercanos); registro coloquial, referencias privadas.",
    "autodestinatario": "el propio yo como destinatario (función de "
        "diario/registro), sin interpelar a otro.",
    "testigo_indeseado": "audiencia de riesgo por context collapse (familia, "
        "empleadores, desconocidos) que accede a un enunciado pensado para un "
        "círculo restringido; se infiere por contraste.",
    "enunciatario_target": "el consumidor ideal construido discursivamente "
        "(imperativos de venta, léxico de beneficio).",
    "comunidad_marca": "clientes o seguidores ya fidelizados a quienes se retiene "
        "o refuerza.",
    "prescriptor_amplificador": "el destinatario cuya función es resharear o "
        "viralizar (llamados a compartir, etiquetar, RT, concursos).",
}


def _union_roles() -> tuple[str, ...]:
    """Universo cerrado de roles del género: transversales + todos los tipos.

    Es el `Literal` que restringe el sampler (estable por género); la
    restricción por tipo se aplica en el prompt y en el filtro post-hoc.
    """
    roles = list(_ROLES_TRANSVERSALES)
    for tipo_roles in _ENUNCIATARIOS_POR_TIPO.values():
        roles.extend(tipo_roles)
    return tuple(dict.fromkeys(roles))


def get_genre() -> Genre:
    """Factory expuesta como entry-point en pyproject.toml.

    Los roles enunciativos se ordenan alrededor de creencias y valores y
    dependen del tipo de discurso, más dos posiciones propias del dispositivo
    (destinatario mencionado y audiencia ambiente), transversales a todos los
    tipos. El universo cerrado (`enunciation_roles`) es la unión de ambos: la
    selección por tipo la hace `enunciation` en el prompt y con un filtro
    post-hoc, sin fragmentar la gramática.
    """
    return Genre(
        genre_id="tuit",
        display_name="Tuit / Post de red social",
        unit="documento",
        context_unit="hilo",
        technoparse=True,
        enunciador_from_handle=True,
        auditorio_predeterminado=True,
        enunciation_roles=_union_roles(),
        roles_transversales=_ROLES_TRANSVERSALES,
        enunciatarios_por_tipo=_ENUNCIATARIOS_POR_TIPO,
        roles_descripciones=_ROLES_DESCRIPCIONES,
        tipos_discurso=(
            "politico",
            "periodistico_informativo",
            "institucional",
            "humor_meme",
            "personal_cotidiano",
            "promocional",
            "otro",
        ),
        tipos_discurso_descripciones={
            "politico": "enunciación partidaria, gubernamental o militante, "
                        "incluida la de campaña electoral",
            "periodistico_informativo": "difusión de noticias o información "
                                        "de actualidad (medios, periodistas, "
                                        "cuentas de cobertura)",
            "institucional": "comunicación oficial de organizaciones "
                             "(organismos, empresas, ONG) no reductible a lo "
                             "político-partidario",
            "humor_meme": "función predominantemente humorística, paródica o "
                          "memética",
            "personal_cotidiano": "experiencia personal, opinión no militante "
                                  "o vida cotidiana",
            "promocional": "publicidad, venta o autopromoción de productos, "
                           "servicios o contenidos",
            "otro": "no se ajusta a ninguno de los anteriores",
        },
        models={},
        batch_size={
            "actors": 2,
            "emotions": 1,
            "emotions_pass2": 1,
            "characterizer": 1,
            "actants": 1,
            "judge": 1,
            "reframing": 2,
            "emoji_affect": 6,
            "hashtag_semiotics": 6,
            "tecno_usage": 3,
        },
        summarizer=False,
        # El pase 2 relee cada frase con las anteriores como contexto: en un
        # tuit, que es una sola unidad, no hay contexto previo que aportar.
        stages_invalidas=("emotions_pass2",),
        max_emociones_unidad=5,
        prompt_overrides={
            "emotions": "emotions_system_tuit",
            "emotions_pass2": "emotions_pass2_system_tuit",
            "enunciation": "enunciation_system_tuit",
            "metadata": "metadata_system_tuit",
        },
        heuristics_overrides={
            "emotions": "heuristicas/emotions_tuit.md",
            "emotions_pass2": "heuristicas/emotions_tuit.md",
            "enunciation": "heuristicas/enunciation_tuit.md",
        },
    )
