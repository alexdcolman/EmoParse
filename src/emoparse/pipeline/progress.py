# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.pipeline.progress
#
#  Reporte de avance de una stage sobre la consola.
#
#  Las stages informan cuántas unidades tienen por delante y van avanzando
#  el contador; el reporter decide cuándo emitir. En corpus de discursos el
#  volumen por stage es chico y el detalle por unidad alcanza, pero un corpus
#  de posts procesa cientos o miles de unidades por stage, donde lo que se
#  necesita es el porcentaje y cuánto falta.
#
#  El reporte se emite por tiempo, no por cantidad de unidades: una stage
#  lenta informa aunque avance de a poco, y una rápida no inunda el log. Es
#  thread-safe porque las stages por frase procesan discursos en paralelo.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import threading
import time
from collections.abc import Iterable, Iterator
from typing import TypeVar

from loguru import logger

T = TypeVar("T")

#: Segundos mínimos entre dos reportes de la misma stage.
INTERVALO_SEGUNDOS = 20.0


class ProgressReporter:
    """Contador de avance de una stage, con reporte periódico al log.

    Fuera de un tramo iniciado con `start()` todos los métodos son no-ops,
    así que una stage puede avanzarlo sin condicionar cada llamada.
    """

    def __init__(
        self,
        stage: str,
        intervalo_segundos: float = INTERVALO_SEGUNDOS,
    ) -> None:
        self._stage = stage
        self._intervalo = intervalo_segundos
        self._lock = threading.Lock()
        self._total = 0
        self._hechos = 0
        self._unidad = "items"
        self._inicio = 0.0
        self._ultimo = 0.0

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    def start(self, total: int, unidad: str = "items") -> None:
        """Abre un tramo de `total` unidades y anuncia el trabajo pendiente."""
        with self._lock:
            self._total = max(int(total), 0)
            self._hechos = 0
            self._unidad = unidad
            self._inicio = self._ultimo = time.monotonic()
        if self._total:
            logger.info(f"[Stage:{self._stage}] {self._total} {unidad} por procesar.")

    def advance(self, n: int = 1) -> None:
        """Suma `n` unidades procesadas y reporta si toca."""
        if not self._total:
            return
        with self._lock:
            self._hechos += int(n)
            ahora = time.monotonic()
            if ahora - self._ultimo < self._intervalo or self._hechos >= self._total:
                return
            self._ultimo = ahora
            mensaje = self._mensaje(ahora)
        logger.info(mensaje)

    def finish(self) -> None:
        """Cierra el tramo con el tiempo total y deja de reportar."""
        if not self._total:
            return
        with self._lock:
            transcurrido = time.monotonic() - self._inicio
            hechos, total, unidad = self._hechos, self._total, self._unidad
            self._total = 0
        logger.info(
            f"[Stage:{self._stage}] 100% · {hechos}/{total} {unidad} en {_duracion(transcurrido)}."
        )

    # ── Envoltorio de iteración ──────────────────────────────────────────────

    def track(self, items: Iterable[T], unidad: str = "items") -> Iterator[T]:
        """Itera una colección llevando el avance automáticamente.

        Para los bucles secuenciales de las stages. La colección se
        materializa para conocer el total antes de empezar.
        """
        materializados = list(items)
        self.start(len(materializados), unidad)
        try:
            for item in materializados:
                yield item
                self.advance()
        finally:
            self.finish()

    # ── Interno ──────────────────────────────────────────────────────────────

    def _mensaje(self, ahora: float) -> str:
        """Línea de avance con porcentaje y estimación de lo que falta."""
        pct = int(100 * self._hechos / self._total)
        linea = f"[Stage:{self._stage}] {pct}% · {self._hechos}/{self._total} {self._unidad}"
        transcurrido = ahora - self._inicio
        if self._hechos:
            restante = transcurrido / self._hechos * (self._total - self._hechos)
            linea += f" · faltan ~{_duracion(restante)}"
        return linea


def _duracion(segundos: float) -> str:
    """Formatea una duración en unidades legibles."""
    segundos = max(int(segundos), 0)
    if segundos < 60:
        return f"{segundos}s"
    minutos, seg = divmod(segundos, 60)
    if minutos < 60:
        return f"{minutos}m{seg:02d}s"
    horas, minutos = divmod(minutos, 60)
    return f"{horas}h{minutos:02d}m"
