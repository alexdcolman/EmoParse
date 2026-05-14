# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.app.styles
#
#  Estilos CSS globales del dashboard Streamlit.
#
#  Expone una única constante `CSS`, inyectada desde `main.py`
#  mediante `st.markdown(..., unsafe_allow_html=True)`.
#
#  Define paleta visual, tipografía y estilos comunes para sidebar,
#  tabs, tablas, badges, cards y componentes auxiliares de la UI.
# ══════════════════════════════════════════════════════════════════════════════

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500&display=swap');

/* ── Variables ── */
:root {
    --bg:        #0e0f13;
    --surface:   #16181f;
    --border:    #252730;
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
}

/* ── Reset Streamlit ── */
html, body, [class*="css"] {
    font-family: var(--font-sans);
    color: var(--text);
}
.stApp {
    background: var(--bg);
}
section[data-testid="stSidebar"] {
    background: var(--surface);
    border-right: 1px solid var(--border);
}
header[data-testid="stHeader"] { display: none; }
.block-container { padding: 2rem 2.5rem 4rem; max-width: 1200px; }

/* ── Typography ── */
h1 { font-family: var(--font-serif); font-size: 2.4rem; color: var(--accent); letter-spacing: -0.02em; }
h2 { font-family: var(--font-serif); font-size: 1.6rem; color: var(--text); letter-spacing: -0.01em; }
h3 { font-family: var(--font-sans); font-size: 1rem; font-weight: 500; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.08em; }
p, li { font-size: 0.95rem; line-height: 1.65; color: var(--text); }
code, pre { font-family: var(--font-mono); font-size: 0.85rem; }

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
.ep-card-accent {
    border-left: 3px solid var(--accent);
}

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
div[data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }

/* ── Emotion chip ── */
.emo-chip {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 3px;
    font-size: 0.78rem; font-family: var(--font-mono); margin: 0.15rem;
    border: 1px solid;
}

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

/* ── Expander ── */
[data-testid="stExpander"] {
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
}

/* ── Alert ── */
[data-testid="stAlert"] { border-radius: 8px; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: var(--bg); }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--dim); }
</style>
"""
