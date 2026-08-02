# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.viz.theme
#
#  Tema visual compartido por todas las figuras plotly.
#
#  Antes cada módulo resolvía su propio aspecto: `charts` armaba un layout a
#  mano y `network_charts` usaba `plotly_dark`, de modo que dos gráficos del
#  mismo dashboard se veían de sistemas distintos. Acá viven los colores de
#  chrome (fondo, borde, texto, acentos) y el layout base; los colores de
#  dato salen de `viz.foria`, que es otra responsabilidad.
#
#  `base_layout()` devuelve el dict para `update_layout(**...)`; para las
#  figuras que prefieran declararlo, el mismo tema queda registrado en
#  plotly como `emoparse` y se usa con `template="emoparse"`.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

#: Colores de chrome. Espejan las variables CSS de `app.styles`: los gráficos
#: tienen que apoyarse sobre el mismo fondo que el marcado que los rodea.
BG = "#0e0f13"
SURFACE = "#16181f"
BORDER = "#252730"
ACCENT = "#c8a96e"
ACCENT2 = "#7c9ec8"
TEXT_DIM = "#8a8799"
TEXT = "#e8e4dc"
DIM = "#5a5d6e"
FONT = "DM Mono, monospace"

#: Nombre del template registrado en plotly.
TEMPLATE = "emoparse"


def base_layout(**kwargs) -> dict:
    """Layout base compartido por todas las figuras.

    Los `kwargs` pisan lo que definen las claves de este dict, así que una
    figura puede ajustar ejes, alto o leyenda sin repetir el resto.
    """
    base = dict(
        template=TEMPLATE,
        paper_bgcolor=BG,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT, color=TEXT_DIM, size=11),
        xaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        yaxis=dict(gridcolor=BORDER, zerolinecolor=BORDER),
        legend=dict(
            bgcolor=SURFACE,
            bordercolor=BORDER,
            borderwidth=1,
            font=dict(size=10),
        ),
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(
            bgcolor=SURFACE,
            bordercolor=BORDER,
            font=dict(family=FONT, size=11),
        ),
    )
    base.update(kwargs)
    return base


def titulo(texto: str) -> dict:
    """Título de figura con el tratamiento tipográfico del dashboard."""
    return dict(text=texto, font=dict(color=ACCENT, size=13))


def _registrar() -> None:
    """Registra el template `emoparse` en plotly (idempotente)."""
    if TEMPLATE in pio.templates:
        return
    pio.templates[TEMPLATE] = go.layout.Template(
        layout=dict(
            paper_bgcolor=BG,
            plot_bgcolor=SURFACE,
            font=dict(family=FONT, color=TEXT_DIM, size=11),
            xaxis=dict(
                gridcolor=BORDER,
                zerolinecolor=BORDER,
                linecolor=BORDER,
                tickfont=dict(family=FONT, size=10),
            ),
            yaxis=dict(
                gridcolor=BORDER,
                zerolinecolor=BORDER,
                linecolor=BORDER,
                tickfont=dict(family=FONT, size=10),
            ),
            legend=dict(
                bgcolor=SURFACE,
                bordercolor=BORDER,
                borderwidth=1,
                font=dict(family=FONT, size=10),
            ),
            hoverlabel=dict(
                bgcolor=SURFACE,
                bordercolor=BORDER,
                font=dict(family=FONT, size=11),
            ),
            colorway=[ACCENT, ACCENT2, TEXT_DIM, DIM],
        )
    )


_registrar()
