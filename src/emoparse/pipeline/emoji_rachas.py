# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.emoji_rachas
#
#  Agrupación de usos de emoji en rachas contiguas.
#
#  `technoparse` extrae un emoji por span (regla un-span-una-entidad), de modo
#  que 🤣🤣🤣 deja tres entidades con sus offsets. Pero tres risas seguidas no
#  son tres gestos: son uno intensificado. Este módulo agrupa las ocurrencias
#  contiguas de un mismo emoji dentro de una unidad para que la stage las
#  resuelva de una sola vez, y deriva de la longitud de la racha su marca de
#  intensidad, sin gastar una inferencia en contarla.
#
#  Dos rachas del mismo emoji en la misma unidad son usos distintos (blancos
#  distintos, contextos locales distintos) y no se agrupan entre sí.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Delimitadores con los que se señala la racha analizada dentro del texto.
#: Se eligen fuera del repertorio tipográfico del corpus para que no se
#: confundan con comillas o corchetes del propio post.
MARCA_INICIO = "⟦"
MARCA_FIN = "⟧"


@dataclass(frozen=True)
class Racha:
    """Ocurrencias contiguas de un mismo emoji dentro de una unidad."""

    emoji: str
    codigo: str
    unit_idx: int
    frase: str
    inicio: int  # offset inicial de la racha en `frase`
    fin: int  # offset final de la racha (exclusive)
    usos: tuple[Mapping[str, Any], ...]

    @property
    def n(self) -> int:
        """Cantidad de ocurrencias de la racha."""
        return len(self.usos)

    @property
    def intensidad(self) -> str:
        """Marca de intensidad derivada de la longitud de la racha."""
        return intensidad_de(self.n)


def intensidad_de(n: int) -> str:
    """Traduce la longitud de una racha a su marca de intensidad.

    El vocabulario acompaña al de `tecno_usage` (`saturacion_expresiva`): la
    repetición no cambia qué emoción aporta el emoji, cambia con qué énfasis.
    """
    if n >= 3:
        return "saturado"
    if n == 2:
        return "intensificado"
    return "simple"


def agrupar_rachas(usos: Iterable[Mapping[str, Any]]) -> list[Racha]:
    """Agrupa usos de emoji en rachas contiguas.

    Cada uso debe traer `codigo`, `unit_idx`, `valor`, `inicio`, `fin` y la
    `frase` de su unidad (lo que devuelve
    `TecnoRepository.list_emojis_sin_afecto`). Dos ocurrencias entran en la
    misma racha si comparten unidad y emoji y entre sus spans no hay más que
    blancos: `🤣 🤣` es el mismo gesto, `🤣, 🤣` son dos.
    """
    ordenados = sorted(
        usos,
        key=lambda u: (str(u["codigo"]), int(u["unit_idx"]), int(u["inicio"])),
    )
    rachas: list[Racha] = []
    grupo: list[Mapping[str, Any]] = []
    for uso in ordenados:
        if grupo and _continua(grupo[-1], uso):
            grupo.append(uso)
            continue
        if grupo:
            rachas.append(_construir(grupo))
        grupo = [uso]
    if grupo:
        rachas.append(_construir(grupo))
    return rachas


def marcar_racha(frase: str, inicio: int, fin: int) -> str:
    """Devuelve el texto con la racha delimitada.

    Sin esta marca, un post con dos rachas del mismo emoji le llega al agente
    como dos unidades idénticas y no hay forma de saber cuál analiza.
    """
    texto = str(frase or "")
    if not texto or not 0 <= inicio < fin <= len(texto):
        return texto
    return f"{texto[:inicio]}{MARCA_INICIO}{texto[inicio:fin]}{MARCA_FIN}{texto[fin:]}"


def payload_repeticion(racha: Racha, orden: int) -> dict[str, Any]:
    """Bloque `repeticion` que acompaña al afecto de cada ocurrencia.

    `primario` marca la ocurrencia que representa a la racha: las lecturas
    (dashboard, export) filtran por ella para no listar el mismo gesto tantas
    veces como veces se lo tecleó.
    """
    return {
        "n": racha.n,
        "orden": orden,
        "primario": orden == 0,
        "intensidad": racha.intensidad,
        "inicio": racha.inicio,
        "fin": racha.fin,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers internos
# ══════════════════════════════════════════════════════════════════════════════


def _continua(previo: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    """True si `actual` prolonga la racha que viene de `previo`."""
    if (
        str(previo["codigo"]) != str(actual["codigo"])
        or int(previo["unit_idx"]) != int(actual["unit_idx"])
        or str(previo["valor"]) != str(actual["valor"])
    ):
        return False
    hueco_inicio, hueco_fin = int(previo["fin"]), int(actual["inicio"])
    if hueco_fin < hueco_inicio:
        return False
    if hueco_fin == hueco_inicio:
        return True
    frase = str(actual.get("frase") or "")
    if hueco_fin > len(frase):
        # Offsets fuera del texto disponible: se corta la racha antes que
        # agrupar por conjetura.
        return False
    return frase[hueco_inicio:hueco_fin].strip() == ""


def _construir(grupo: Sequence[Mapping[str, Any]]) -> Racha:
    """Arma la racha a partir de sus ocurrencias en orden de aparición."""
    primero, ultimo = grupo[0], grupo[-1]
    return Racha(
        emoji=str(primero["valor"]),
        codigo=str(primero["codigo"]),
        unit_idx=int(primero["unit_idx"]),
        frase=str(primero.get("frase") or ""),
        inicio=int(primero["inicio"]),
        fin=int(ultimo["fin"]),
        usos=tuple(grupo),
    )
