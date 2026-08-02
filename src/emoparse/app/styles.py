# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.styles
#
#  Estilos CSS globales del dashboard Streamlit.
#
#  Expone `CSS` (inyectada desde `main.py` con `unsafe_allow_html=True`) y
#  `FORIA_LEGEND`, la leyenda fija de la paleta fórica.
#
#  Define paleta visual, tipografía y estilos comunes para sidebar, tabs,
#  tablas, badges, cards y componentes auxiliares de la UI. Los colores de
#  foria no se escriben acá: se derivan de `viz.foria`, de modo que el
#  marcado de la app y las figuras plotly comparten los mismos valores.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.viz import foria

#: Paleta categorial: matices que distinguen categorías sin ordenarlas (roles
#: del simulacro, tipos de tecnolingüístico, modalidades referenciales). No es
#: la paleta fórica: acá el color identifica, no evalúa.
_HUES: dict[str, str] = {
    "azul": "#7c9ec8",
    "verde": "#6ec89a",
    "violeta": "#b08ad0",
    "oro": "#c8a96e",
    "rosa": "#d28aa8",
    "celeste": "#8ac6d0",
    "terra": "#cf8f6e",
    "rojo": "#c88a8a",
}

#: Tokens semánticos → matiz. Que el experienciador y el hashtag compartan el
#: azul es una decisión de una sola línea, no una coincidencia repetida en
#: tres archivos como estaba antes.
_TOKENS: dict[str, str] = {
    # Roles del simulacro (tabs Simulacros, Búsqueda, Co-ocurrencia).
    "rol-experienciador": "azul",
    "rol-emocion": "violeta",
    "rol-fuente": "verde",
    "rol-mediador": "oro",
    "rol-verif-normativo": "rosa",
    "rol-verif-observacional": "celeste",
    "rol-opmod": "terra",
    # Tipos de tecnolingüístico (chips de la tab Revisión).
    "tecno-hashtag": "azul",
    "tecno-mencion": "verde",
    "tecno-emoji": "oro",
    "tecno-url": "celeste",
    "tecno-tecnografismo": "rosa",
    # Modalidades referenciales (tab Referentes).
    "mod-designacion": "verde",
    "mod-referencia_gramatical": "azul",
    "mod-identificacion_inferencial": "rojo",
}


def var(token: str) -> str:
    """Referencia CSS a un token de la paleta (`var(--rol-emocion)`)."""
    return f"var(--{token})"


def var_soft(token: str) -> str:
    """Versión translúcida de un token, para fondos y bordes de chip."""
    return f"var(--{token}-soft)"


#: Variables CSS de foria, generadas desde la paleta canónica (`--euforico`,
#: `--disforico`, ...) más su versión translúcida para fondos de chip.
_FORIA_VARS = "\n".join(
    f"    --{clave}: {color};\n    --{clave}-soft: {foria.rgba(color, 0.16)};"
    for clave, color in foria.FORIA_COLORS.items()
    if clave is not None
)

#: Matices categoriales y sus tokens semánticos, como variables CSS.
_HUE_VARS = (
    "\n".join(
        f"    --hue-{nombre}: {color};\n    --hue-{nombre}-soft: {foria.rgba(color, 0.15)};"
        for nombre, color in _HUES.items()
    )
    + "\n"
    + "\n".join(
        f"    --{token}: var(--hue-{hue});\n    --{token}-soft: var(--hue-{hue}-soft);"
        for token, hue in _TOKENS.items()
    )
)

#: Chips de la leyenda fija, en el orden de lectura de las forias.
_FORIA_CHIPS = "".join(
    f"<span class='ep-legend-item'>"
    f"<i style='background:{foria.FORIA_COLORS[clave]};'></i>"
    f"{foria.FORIA_LABELS[clave]}</span>"
    for clave in foria.FORIA_ORDEN
)

#: Leyenda fija de la paleta fórica. Vive en el vértice inferior izquierdo,
#: semitransparente y sin capturar el puntero, para no tapar resultados ni
#: interceptar clics; se opaca al pasar por encima.
FORIA_LEGEND = (
    f"<div class='ep-legend'><span class='ep-legend-title'>foria</span>{_FORIA_CHIPS}</div>"
)


_BASE = """
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');

/* ── Variables ── */
:root {
    --bg:        #0e0f13;
    --bg-deep:   #090a0d;
    --surface:   #16181f;
    --surface-2: #1b1e26;
    --border:    #252730;
    --border-2:  #31343f;
    --accent:    #c8a96e;
    --accent2:   #7c9ec8;
    --dim:       #5a5d6e;
    --text:      #e8e4dc;
    --text-dim:  #8a8799;
    --danger:    #c86e6e;
    --ok:        #6ec89a;
    --font-sans: 'DM Sans', sans-serif;
    --font-serif:'DM Serif Display', Georgia, serif;
    --font-mono: 'DM Mono', monospace;
    /* Operaciones de reframing: eje adhesión → distancia → denuncia. No es
       una foria, es otra dimensión, y por eso tiene paleta propia. */
    --op-adhesion:            #6f9ec4;
    --op-neutra_informativa:  #6f8e8a;
    --op-ironia_distancia:    #9a7fc0;
    --op-denuncia:            #c4707f;
    --op-ambigua:             #6b6e7c;
    /* Superficies y textos secundarios que las tabs repetían a mano. */
    --surface-sunken: #15171c;
    --border-soft:    #1a1c22;
    --text-soft:      #c2bdb4;
    --accent-bright:  #f0d890;
    --accent-dark:    #3a3320;
__FORIA_VARS__
__HUE_VARS__
}

/* ── Reset Streamlit ── */
html, body, [class*="css"] {
    font-family: var(--font-sans);
    color: var(--text);
    -webkit-font-smoothing: antialiased;
}
.stApp {
    background:
        radial-gradient(1200px 600px at 12% -10%, #14161d 0%, transparent 60%),
        var(--bg);
}
section[data-testid="stSidebar"] {
    background: var(--bg-deep);
    border-right: 1px solid var(--border);
}
header[data-testid="stHeader"] { display: none; }
.block-container { padding: 2rem 2.5rem 5rem; max-width: 1240px; }
::selection { background: rgba(200,169,110,0.28); color: var(--text); }

/* ── Typography ── */
h1 { font-family: var(--font-serif); font-size: 2.5rem; color: var(--accent); letter-spacing: -0.02em; margin-bottom: 0.2rem; }
h2 { font-family: var(--font-serif); font-size: 1.6rem; color: var(--text); letter-spacing: -0.01em; }
h3 { font-family: var(--font-sans); font-size: 0.95rem; font-weight: 500; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.09em; }
h4 { font-family: var(--font-sans); font-size: 1.05rem; font-weight: 500; color: var(--text); letter-spacing: 0.01em; }
h5, h6 { font-family: var(--font-sans); font-weight: 500; color: var(--text-dim); letter-spacing: 0.04em; }
p, li { font-size: 0.95rem; line-height: 1.7; color: var(--text); }
code, pre { font-family: var(--font-mono); font-size: 0.85rem; }
/* Cifras alineadas en columna: las tablas y métricas dejan de bailar. */
.stat-val, .dataframe, [data-testid="stMetricValue"], code {
    font-variant-numeric: tabular-nums;
}

/* ── Sidebar nav ── */
.nav-btn {
    display: block; width: 100%; padding: 0.65rem 1rem;
    margin-bottom: 0.3rem; border-radius: 6px;
    background: transparent; border: 1px solid transparent;
    color: var(--text-dim); cursor: pointer; text-align: left;
    font-family: var(--font-sans); font-size: 0.9rem;
    transition: all 0.15s ease;
}
.nav-btn:hover { background: var(--border); color: var(--text); border-color: var(--border); }
.nav-btn.active { background: rgba(200,169,110,0.12); border-color: var(--accent); color: var(--accent); }

/* ── Cards ── */
.ep-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1.4rem 1.6rem; margin-bottom: 1rem;
}
.ep-card-accent { border-left: 3px solid var(--accent); }

/* ── Badges ── */
.badge {
    display: inline-block; padding: 0.2rem 0.6rem; border-radius: 4px;
    font-size: 0.75rem; font-family: var(--font-mono); font-weight: 500;
}
.badge-ok     { background: rgba(110,200,154,0.15); color: var(--ok); border: 1px solid rgba(110,200,154,0.3); }
.badge-warn   { background: rgba(200,169,110,0.15); color: var(--accent); border: 1px solid rgba(200,169,110,0.3); }
.badge-err    { background: rgba(200,110,110,0.15); color: var(--danger); border: 1px solid rgba(200,110,110,0.3); }
.badge-dim    { background: var(--border); color: var(--text-dim); border: 1px solid var(--border); }

/* ── Progress ── */
.ep-progress {
    height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; margin: 0.5rem 0;
}
.ep-progress-bar {
    height: 100%; border-radius: 2px;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    transition: width 0.4s ease;
}

/* ── Stat boxes ── */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px,1fr)); gap: 0.8rem; }
.stat-box {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1rem 1.2rem;
}
.stat-val { font-family: var(--font-mono); font-size: 1.8rem; color: var(--accent); font-weight: 500; }
.stat-lbl { font-size: 0.75rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.2rem; }

/* ── Tables ── */
.dataframe { font-family: var(--font-mono); font-size: 0.82rem; }
div[data-testid="stDataFrame"] {
    border-radius: 8px; overflow: hidden; border: 1px solid var(--border);
}

/* ── Emotion chip ── */
.emo-chip {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px;
    font-size: 0.78rem; font-family: var(--font-mono); margin: 0.15rem;
    border: 1px solid;
}

/* ── Tabs ── */
/* Con muchas tabs, Streamlit hace scroll horizontal con flechas < >. Se
   fuerza el wrap en varias filas: todas las tabs quedan visibles sin
   desplazarse. */
div[data-testid="stTabs"] div[role="tablist"] {
    flex-wrap: wrap;
    gap: 0.15rem 0.4rem;
    overflow-x: visible;
    border-bottom: 1px solid var(--border);
}
/* Oculta los botones de scroll (chevrons) que ya no hacen falta. */
div[data-testid="stTabs"] div[role="tablist"] button[aria-label="scroll"],
div[data-testid="stTabs"] div[role="tablist"] > button:not([role="tab"]) {
    display: none !important;
}
div[data-testid="stTabs"] button[role="tab"] {
    white-space: nowrap;
    font-size: 0.86rem;
    color: var(--text-dim);
    padding: 0.35rem 0.7rem;
    border-bottom: 2px solid transparent;
    transition: color 0.15s ease, border-color 0.15s ease;
}
div[data-testid="stTabs"] button[role="tab"]:hover { color: var(--text); }
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {
    color: var(--accent);
    border-bottom-color: var(--accent);
}
div[data-testid="stTabs"] div[data-baseweb="tab-highlight"] { display: none; }

/* ── Dividers ── */
.ep-divider { border: none; border-top: 1px solid var(--border); margin: 1.5rem 0; }

/* ── Upload zone ── */
[data-testid="stFileUploader"] {
    background: var(--surface); border: 1px dashed var(--dim);
    border-radius: 8px;
}
[data-testid="stFileUploader"]:hover { border-color: var(--accent); }

/* ── Inputs ── */
[data-testid="stTextArea"] textarea,
[data-testid="stTextInput"] input {
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); font-family: var(--font-sans); border-radius: 6px;
}
[data-testid="stTextArea"] textarea:focus,
[data-testid="stTextInput"] input:focus {
    border-color: var(--accent); box-shadow: 0 0 0 2px rgba(200,169,110,0.15);
}

/* ── Select ── */
[data-testid="stSelectbox"] > div > div {
    background: var(--surface); border: 1px solid var(--border); color: var(--text);
}

/* ── Buttons ── */
button[kind="primary"] {
    background: var(--accent) !important; color: #0e0f13 !important;
    border: none !important; font-weight: 500 !important;
}
button[kind="secondary"] {
    background: transparent !important; border: 1px solid var(--border) !important;
    color: var(--text) !important;
}
button[kind="primary"]:hover { opacity: 0.9 !important; }
button[kind="secondary"]:hover { border-color: var(--accent) !important; }

/* ── Expander ── */
[data-testid="stExpander"] {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}
[data-testid="stExpander"] summary { font-size: 0.84rem; color: var(--text-dim); }

/* ── Alert ── */
[data-testid="stAlert"] { border-radius: 8px; }

/* ── Caption ── */
[data-testid="stCaptionContainer"] p {
    font-size: 0.78rem; color: var(--text-dim); line-height: 1.55;
}

/* ══ Post conversacional (tab Hilos y citas) ══════════════════════════════ */
/* La barra izquierda es el indicador de foria: 6px, no 3, porque a 3 se
   confunde con un borde decorativo. Su color lo fija cada post inline. */
.ep-post {
    border-left: 6px solid var(--indeterminado);
    background: var(--surface);
    border-radius: 0 8px 8px 0;
    padding: 0.5rem 0.85rem;
    margin-bottom: 0.5rem;
    font-size: 0.88rem;
    line-height: 1.6;
    transition: background 0.15s ease;
}
.ep-post:hover { background: var(--surface-2); }
.ep-post-head {
    display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap;
    font-size: 0.76rem; color: var(--text-dim); margin-bottom: 0.25rem;
}
.ep-post-handle { color: var(--accent2); font-family: var(--font-mono); }
.ep-post-texto { color: var(--text); white-space: pre-wrap; }

/* Bloque citado embebido: se lee como discurso ajeno, no como del citador. */
.ep-quote {
    border: 1px solid var(--border-2);
    border-radius: 6px;
    background: var(--bg-deep);
    padding: 0.4rem 0.7rem;
    margin-top: 0.45rem;
    font-size: 0.82rem;
    color: var(--text-dim);
}
.ep-quote-head { font-family: var(--font-mono); font-size: 0.72rem; color: var(--dim); }
.ep-quote-texto { color: #b6b2ab; }

/* Chip de foria del post: acompaña a la barra con el nombre escrito. */
.ep-foria {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.1rem 0.45rem; border-radius: 999px;
    font-size: 0.7rem; font-family: var(--font-mono);
    border: 1px solid;
}

/* Chip de operación de reframing. */
.ep-op {
    display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px;
    font-size: 0.72rem; font-family: var(--font-mono); font-weight: 500;
    border: 1px solid;
}
.ep-op-adhesion           { color: var(--op-adhesion);           border-color: var(--op-adhesion);           background: rgba(111,158,196,0.13); }
.ep-op-neutra_informativa { color: var(--op-neutra_informativa); border-color: var(--op-neutra_informativa); background: rgba(111,142,138,0.13); }
.ep-op-ironia_distancia   { color: var(--op-ironia_distancia);   border-color: var(--op-ironia_distancia);   background: rgba(154,127,192,0.13); }
.ep-op-denuncia           { color: var(--op-denuncia);           border-color: var(--op-denuncia);           background: rgba(196,112,127,0.13); }
.ep-op-ambigua            { color: var(--op-ambigua);            border-color: var(--op-ambigua);            background: rgba(107,110,124,0.13); }

.ep-media {
    font-size: 0.76rem; color: var(--text-dim);
    border-left: 1px dotted var(--border-2);
    padding-left: 0.6rem; margin-top: 0.35rem;
}
.ep-justif {
    font-size: 0.75rem; color: var(--dim); font-style: italic; margin-top: 0.25rem;
}

/* ══ Header de run ════════════════════════════════════════════════════════ */
/* Barra que acompaña a todas las tabs: mientras mirás un gráfico, decís qué
   corpus estás mirando sin volver al sidebar. */
.ep-runbar {
    display: flex; align-items: baseline; gap: 1.1rem; flex-wrap: wrap;
    padding: 0.5rem 0.9rem; margin-bottom: 1rem;
    background: var(--surface); border: 1px solid var(--border);
    border-left: 3px solid var(--accent); border-radius: 8px;
    font-family: var(--font-mono); font-size: 0.76rem; color: var(--text-dim);
}
.ep-runbar b { color: var(--text); font-weight: 500; }
.ep-runbar-id { color: var(--accent); }
.ep-runbar-sep { color: var(--border-2); }

/* ══ Leyenda fórica fija ══════════════════════════════════════════════════ */
.ep-legend {
    position: fixed; left: 0.9rem; bottom: 0.9rem; z-index: 90;
    display: flex; align-items: center; gap: 0.55rem; flex-wrap: wrap;
    max-width: 15rem;
    padding: 0.4rem 0.7rem; border-radius: 8px;
    background: rgba(14,15,19,0.62);
    border: 1px solid var(--border);
    backdrop-filter: blur(6px);
    font-family: var(--font-mono); font-size: 0.66rem; color: var(--text-dim);
    opacity: 0.4; transition: opacity 0.2s ease;
    pointer-events: none;   /* nunca intercepta un clic del dashboard */
}
.ep-legend:hover { opacity: 1; }
.ep-legend-title {
    text-transform: uppercase; letter-spacing: 0.1em;
    color: var(--dim); font-size: 0.6rem;
}
.ep-legend-item { display: inline-flex; align-items: center; gap: 0.25rem; }
.ep-legend-item i {
    width: 8px; height: 8px; border-radius: 2px; display: inline-block;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--dim); }
"""

CSS = (
    "<style>"
    + _BASE.replace("__FORIA_VARS__", _FORIA_VARS).replace("__HUE_VARS__", _HUE_VARS)
    + "</style>"
)
