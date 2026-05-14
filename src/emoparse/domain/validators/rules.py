# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.domain.validators.rules
#
#  Validators concretos derivados de las ontologías y heurísticas del proyecto.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.domain.validators.base import (
    DiscursoValidator,
    RowValidator,
    ValidationIssue,
)


# ══════════════════════════════════════════════════════════════════════════════
#  RowValidators (operan sobre una emoción individual)
# ══════════════════════════════════════════════════════════════════════════════

class V01_ModoPotencialVirtualExperienciador(RowValidator):
    """V-01: modo Virtual o Potencial con experienciador que parece ser
    el enunciador.

    Fuente ontológica:
      emociones.json — "Potencial: efecto pretendido sobre un enunciatario"
                       "Virtual: estructura posible o imaginada"
      actores.json   — "Excluir siempre al enunciador y a los enunciatarios"
                       como actores representados.

    Regla: si modo_existencia ∈ {virtual, potencial}, el experienciador
    NO debería coincidir con el enunciador (esos modos están dirigidos
    a enunciatarios o a estructuras hipotéticas, no al enunciador mismo).
    """

    VALIDATOR_ID = "V-01"

    def validate(self, *, codigo, frase_idx, emocion_idx,
                 experienciador, tipo_emocion, modo_existencia,
                 foria, dominancia, intensidad, tipo_fuente, fuente,
                 enunciador, enunciatarios) -> list[ValidationIssue]:
        modos_aplica = {"virtual", "potencial"}
        if modo_existencia.lower() not in modos_aplica:
            return []
        if not enunciador or enunciador.strip().lower() == "no identificado":
            return []

        exp_norm = experienciador.strip().lower()
        enu_norm = enunciador.strip().lower()

        # Coincidencia: el experienciador contiene al enunciador o viceversa.
        # No se utiliza igualdad exacta porque el LLM puede parafrasear.
        if enu_norm in exp_norm or exp_norm in enu_norm:
            return [ValidationIssue(
                validator_id=self.VALIDATOR_ID,
                mensaje=(
                    f"Emoción en modo '{modo_existencia}' tiene como experienciador "
                    f"al enunciador ('{experienciador}'). "
                    f"Los modos virtual/potencial refieren a enunciatarios o "
                    f"estructuras hipotéticas, no al enunciador."
                ),
                codigo=codigo,
                frase_idx=frase_idx,
                emocion_idx=emocion_idx,
                contexto={
                    "modo_existencia": modo_existencia,
                    "experienciador": experienciador,
                    "enunciador": enunciador,
                },
            )]
        return []


class V02_FuenteNoIdentificadaConIntensidadAlta(RowValidator):
    """V-02: fuente no identificada con intensidad alta.

    Fuente ontológica:
      fuente.txt    — "Si no lográs determinar la fuente con exactitud,
                       devolvé: 'no se identifica'"
      intensidad.json — "Alta: emociones intensamente expresadas o inferibles"

    Regla: si tipo_fuente == "no_se_identifica" e intensidad == "alta",
    hay tensión semiótica: una emoción muy intensa debería tener fuente
    identificable (la intensidad presupone un estímulo claro). La
    coexistencia de ambos valores es sospechosa pero no imposible (ej.
    angustia difusa intensa), por eso es warning.

    No dispara si tipo_fuente es "discurso_ajeno" (tiene fuente implícita).
    """

    VALIDATOR_ID = "V-02"

    def validate(self, *, codigo, frase_idx, emocion_idx,
                 experienciador, tipo_emocion, modo_existencia,
                 foria, dominancia, intensidad, tipo_fuente, fuente,
                 enunciador, enunciatarios) -> list[ValidationIssue]:
        if tipo_fuente.lower() != "no_se_identifica":
            return []
        if intensidad.lower() != "alta":
            return []

        return [ValidationIssue(
            validator_id=self.VALIDATOR_ID,
            mensaje=(
                f"Emoción '{tipo_emocion}' tiene intensidad 'alta' pero "
                f"fuente 'no_se_identifica'. Las emociones de alta intensidad "
                f"suelen tener fuente identificable. Revisar si la fuente "
                f"quedó sin detectar."
            ),
            codigo=codigo,
            frase_idx=frase_idx,
            emocion_idx=emocion_idx,
            contexto={
                "tipo_emocion": tipo_emocion,
                "intensidad": intensidad,
                "tipo_fuente": tipo_fuente,
            },
        )]


class V04_AforicoConIntensidadAlta(RowValidator):
    """V-04: foria afórica con intensidad alta.

    Fuente ontológica:
      foria.json    — "Afórico: emoción neutra, sin polaridad positiva ni
                       negativa clara."
      intensidad.json — "Alta: emociones intensamente expresadas o inferibles."

    Regla: lo afórico por definición carece de carga afectiva marcada.
    Una intensidad 'alta' presupone un estado afectivo fuerte, lo que
    contradice la ausencia de polaridad. La coexistencia es internamente
    incoherente según las ontologías del proyecto.
    """

    VALIDATOR_ID = "V-04"

    def validate(self, *, codigo, frase_idx, emocion_idx,
                 experienciador, tipo_emocion, modo_existencia,
                 foria, dominancia, intensidad, tipo_fuente, fuente,
                 enunciador, enunciatarios) -> list[ValidationIssue]:
        if foria.lower() != "aforico":
            return []
        if intensidad.lower() != "alta":
            return []

        return [ValidationIssue(
            validator_id=self.VALIDATOR_ID,
            mensaje=(
                f"Emoción '{tipo_emocion}': foria 'afórico' (neutro, sin polaridad) "
                f"es incompatible con intensidad 'alta'. Lo afórico no admite "
                f"intensidad fuerte según la ontología del proyecto."
            ),
            codigo=codigo,
            frase_idx=frase_idx,
            emocion_idx=emocion_idx,
            contexto={
                "tipo_emocion": tipo_emocion,
                "foria": foria,
                "intensidad": intensidad,
            },
        )]


class V05_AmbiforicaConIntensidadBaja(RowValidator):
    """V-05: foria ambifórica con intensidad baja.

    Fuente ontológica:
      foria.json — "Ambifórico: mezcla de tonalidades positiva y negativa."
      intensidad.json — "Baja: emoción leve o sutil."

    Regla: la ambivalencia (mezcla de polaridades opuestas) implica
    tensión afectiva, incompatible con intensidad baja. Una emoción
    ambifórica débil sería afórica, no ambifórica.
    """

    VALIDATOR_ID = "V-05"

    def validate(self, *, codigo, frase_idx, emocion_idx,
                 experienciador, tipo_emocion, modo_existencia,
                 foria, dominancia, intensidad, tipo_fuente, fuente,
                 enunciador, enunciatarios) -> list[ValidationIssue]:
        if foria.lower() != "ambiforico":
            return []
        if intensidad.lower() != "baja":
            return []

        return [ValidationIssue(
            validator_id=self.VALIDATOR_ID,
            mensaje=(
                f"Emoción '{tipo_emocion}': foria 'ambifórico' implica tensión "
                f"entre polaridades opuestas, incompatible con intensidad 'baja'. "
                f"Una emoción ambivalente débil sería afórica, no ambifórica."
            ),
            codigo=codigo,
            frase_idx=frase_idx,
            emocion_idx=emocion_idx,
            contexto={
                "tipo_emocion": tipo_emocion,
                "foria": foria,
                "intensidad": intensidad,
            },
        )]


class V06_VirtualConForiaAforica(RowValidator):
    """V-06: modo existencia Virtual con foria afórica.

    Fuente ontológica:
      emociones.json — "Virtual: estructura posible o imaginada, como
                        competencia emocional o potencial conceptual."
      foria.json     — "Afórico: sin polaridad positiva ni negativa clara."

    Regla: lo virtual en la semiótica de las pasiones (Greimas/Fontanille)
    es una emoción imaginada o presupuesta, que implica siempre alguna
    coloración afectiva (de lo contrario no sería una emoción, sino
    un estado neutro). Lo afórico en modo virtual es ontológicamente
    contradictorio: si no hay polaridad, no hay emoción virtual.
    """

    VALIDATOR_ID = "V-06"

    def validate(self, *, codigo, frase_idx, emocion_idx,
                 experienciador, tipo_emocion, modo_existencia,
                 foria, dominancia, intensidad, tipo_fuente, fuente,
                 enunciador, enunciatarios) -> list[ValidationIssue]:
        if modo_existencia.lower() != "virtual":
            return []
        if foria.lower() != "aforico":
            return []

        return [ValidationIssue(
            validator_id=self.VALIDATOR_ID,
            mensaje=(
                f"Emoción '{tipo_emocion}' en modo 'virtual' con foria 'afórico'. "
                f"Lo virtual presupone una emoción imaginada con alguna coloración "
                f"afectiva; sin polaridad (afórico) no es emoción virtual sino "
                f"estado neutro."
            ),
            codigo=codigo,
            frase_idx=frase_idx,
            emocion_idx=emocion_idx,
            contexto={
                "tipo_emocion": tipo_emocion,
                "modo_existencia": modo_existencia,
                "foria": foria,
            },
        )]


class V07_TipoFuenteActorSinFuenteNombrada(RowValidator):
    """V-07: tipo_fuente == 'actor' pero fuente no nombra a ningún actor.

    Fuente ontológica:
      fuente.json — "Actor: persona o grupo que provoca la emoción."
                    Ejemplo: 'Juan la hizo enojar' → actor.

    Regla: si el tipo de fuente es 'actor', el campo `fuente` debería
    contener un nombre o denominación concreta. Las señales de ausencia
    son strings genéricos o el sentinel "no identificado".
    """

    VALIDATOR_ID = "V-07"

    #: Valores que indican fuente no nombrada aunque tipo_fuente sea "actor".
    _SENTINELAS = frozenset({
        "no identificado",
        "no_se_identifica",
        "no se identifica",
        "no identificada",
        "",
    })

    def validate(self, *, codigo, frase_idx, emocion_idx,
                 experienciador, tipo_emocion, modo_existencia,
                 foria, dominancia, intensidad, tipo_fuente, fuente,
                 enunciador, enunciatarios) -> list[ValidationIssue]:
        if tipo_fuente.lower() != "actor":
            return []

        fuente_norm = fuente.strip().lower()
        if fuente_norm not in self._SENTINELAS:
            return []

        return [ValidationIssue(
            validator_id=self.VALIDATOR_ID,
            mensaje=(
                f"Emoción '{tipo_emocion}': tipo_fuente es 'actor' pero el campo "
                f"fuente contiene '{fuente}' (sin actor nombrado). "
                f"Si el tipo es 'actor', debe identificarse quién provoca la emoción."
            ),
            codigo=codigo,
            frase_idx=frase_idx,
            emocion_idx=emocion_idx,
            contexto={
                "tipo_emocion": tipo_emocion,
                "tipo_fuente": tipo_fuente,
                "fuente": fuente,
            },
        )]


# ══════════════════════════════════════════════════════════════════════════════
#  DiscursoValidators (operan sobre todas las emociones de un discurso)
# ══════════════════════════════════════════════════════════════════════════════


class V08_ActorCoincideConEnunciador(DiscursoValidator):
    """V-08: experienciador coincide con el enunciador del discurso.

    Fuente ontológica:
      actores.json — "Excluir siempre al enunciador y a los enunciatarios,
                      incluso si son referidos indirectamente."
      inferencia_actores.txt — idem.

    Regla: ningún `experienciador` en la tabla emociones debería
    coincidir con el enunciador identificado en la etapa de enunciación,
    porque el enunciador está excluido del conjunto de actores representados.

    No dispara si enunciador == "no identificado".
    """

    VALIDATOR_ID = "V-08"

    def validate(self, *, codigo, emociones, enunciador,
                 enunciatarios) -> list[ValidationIssue]:
        if not enunciador or enunciador.strip().lower() == "no identificado":
            return []

        enu_norm = enunciador.strip().lower()
        issues: list[ValidationIssue] = []

        for emo in emociones:
            exp = emo.get("experienciador", "") or ""
            exp_norm = exp.strip().lower()
            if not exp_norm:
                continue
            if enu_norm in exp_norm or exp_norm in enu_norm:
                issues.append(ValidationIssue(
                    validator_id=self.VALIDATOR_ID,
                    mensaje=(
                        f"El experienciador '{exp}' coincide con el enunciador "
                        f"'{enunciador}'. Según la ontología de actores, el "
                        f"enunciador debe excluirse de los actores representados."
                    ),
                    codigo=codigo,
                    frase_idx=emo.get("frase_idx"),
                    emocion_idx=emo.get("emocion_idx"),
                    contexto={
                        "experienciador": exp,
                        "enunciador": enunciador,
                        "tipo_emocion": emo.get("tipo_emocion", ""),
                    },
                ))

        return issues


class V09_EmocionDuplicadaMismoActorMismaFrase(DiscursoValidator):
    """V-09: misma emoción + mismo experienciador en la misma frase.

    Fuente ontológica:
      inferencia_emociones.txt — "Evitá repetir emociones ya registradas
                                  para el mismo actor en la misma frase."

    Regla: si dos entradas de la tabla `emociones` tienen el mismo
    (frase_idx, tipo_emocion normalizado, experienciador normalizado),
    hay duplicado. La normalización es lowercase + strip para tolerancia
    de variantes menores del LLM.
    """

    VALIDATOR_ID = "V-09"

    def validate(self, *, codigo, emociones, enunciador,
                 enunciatarios) -> list[ValidationIssue]:
        # clave → lista de (frase_idx, emocion_idx)
        seen: dict[tuple[int, str, str], list[tuple[int, int]]] = {}

        for emo in emociones:
            fi = emo.get("frase_idx")
            ei = emo.get("emocion_idx")
            if fi is None or ei is None:
                continue
            tipo = (emo.get("tipo_emocion") or "").strip().lower()
            exp = (emo.get("experienciador") or "").strip().lower()
            key = (fi, tipo, exp)
            seen.setdefault(key, []).append((fi, ei))

        issues: list[ValidationIssue] = []
        for (fi, tipo, exp), ocurrencias in seen.items():
            if len(ocurrencias) < 2:
                continue
            # Reportar usando los índices de la primera ocurrencia duplicada.
            _, first_ei = ocurrencias[0]
            issues.append(ValidationIssue(
                validator_id=self.VALIDATOR_ID,
                mensaje=(
                    f"Emoción '{tipo}' del experienciador '{exp}' aparece "
                    f"{len(ocurrencias)} veces en la frase {fi}. "
                    f"La ontología prohíbe repetir emociones del mismo actor "
                    f"en la misma frase."
                ),
                codigo=codigo,
                frase_idx=fi,
                emocion_idx=first_ei,
                contexto={
                    "tipo_emocion": tipo,
                    "experienciador": exp,
                    "frase_idx": fi,
                    "ocurrencias": len(ocurrencias),
                    "emocion_idxs": [ei for _, ei in ocurrencias],
                },
            ))

        return issues


class V10_ModoPotencialConExperienciadorNoEnunciatario(DiscursoValidator):
    """V-10: modo Potencial con experienciador que no es enunciatario.

    Fuente ontológica:
      emociones.json — "Potencial: la emoción se plantea como posibilidad
                        futura o como efecto pretendido sobre un enunciatario."
      Ejemplo canónico: "Quiero que se sientan orgullosos" → orgullo
      potencial de los enunciatarios.

    Regla: si modo_existencia == "potencial", el experienciador debería
    ser un enunciatario del discurso (prodestinatario, paradestinatario,
    contradestinatario, o equivalente). Si es un actor externo
    (humano_individual o institucional sin rol enunciativo), es sospechoso.
    """

    VALIDATOR_ID = "V-10"

    def validate(self, *, codigo, emociones, enunciador,
                 enunciatarios) -> list[ValidationIssue]:
        if not enunciatarios:
            # Sin enunciatarios identificados, no es posible comparar.
            return []

        # Normalizar enunciatarios para comparación.
        enun_actores_norm = [
            (e.get("actor") or "").strip().lower()
            for e in enunciatarios
            if e.get("actor")
        ]
        if not enun_actores_norm:
            return []

        issues: list[ValidationIssue] = []
        for emo in emociones:
            if (emo.get("modo_existencia") or "").lower() != "potencial":
                continue

            exp = (emo.get("experienciador") or "").strip()
            if not exp:
                continue
            exp_norm = exp.lower()

            # Búsqueda de coincidencias con algún enunciatario.
            coincide = any(
                ea in exp_norm or exp_norm in ea
                for ea in enun_actores_norm
                if ea
            )

            if not coincide:
                issues.append(ValidationIssue(
                    validator_id=self.VALIDATOR_ID,
                    mensaje=(
                        f"Emoción '{emo.get('tipo_emocion', '')}' en modo 'potencial' "
                        f"tiene como experienciador '{exp}', que no coincide con "
                        f"ningún enunciatario del discurso. El modo potencial refiere "
                        f"a efectos pretendidos sobre enunciatarios."
                    ),
                    codigo=codigo,
                    frase_idx=emo.get("frase_idx"),
                    emocion_idx=emo.get("emocion_idx"),
                    contexto={
                        "tipo_emocion": emo.get("tipo_emocion", ""),
                        "modo_existencia": "potencial",
                        "experienciador": exp,
                        "enunciatarios": [e.get("actor") for e in enunciatarios],
                    },
                ))

        return issues


# ══════════════════════════════════════════════════════════════════════════════
#  Registro canónico
# ══════════════════════════════════════════════════════════════════════════════

#: Lista de RowValidators activos. El runner los aplica en orden.
ROW_VALIDATORS: list[RowValidator] = [
    V01_ModoPotencialVirtualExperienciador(),
    V02_FuenteNoIdentificadaConIntensidadAlta(),
    V04_AforicoConIntensidadAlta(),
    V05_AmbiforicaConIntensidadBaja(),
    V06_VirtualConForiaAforica(),
    V07_TipoFuenteActorSinFuenteNombrada(),
]

#: Lista de DiscursoValidators activos.
DISCURSO_VALIDATORS: list[DiscursoValidator] = [
    V08_ActorCoincideConEnunciador(),
    V09_EmocionDuplicadaMismoActorMismaFrase(),
    V10_ModoPotencialConExperienciadorNoEnunciatario(),
]
