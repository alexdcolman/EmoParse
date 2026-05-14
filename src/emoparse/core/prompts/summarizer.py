# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.prompts.summarizer
#
#  Wrapper Jinja2. Caso especial: SYSTEMs estáticos como constantes.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.prompts._loader import render


SYSTEM_FRAGMENTO = (
    "Sos un asistente que resume texto. Tu tarea es generar resúmenes "
    "fieles a la fuente, conservando actores, acciones principales y "
    "el tono general. NO inventes información que no esté en el texto. "
    "NO agregues análisis ni interpretación. Devolvé únicamente el "
    "resumen, sin preámbulos como 'Aquí está el resumen:' ni comentarios."
)


SYSTEM_GLOBAL = (
    "Sos un asistente que integra resúmenes parciales en uno global. "
    "Tu objetivo es producir un único resumen coherente del discurso "
    "completo, identificando tema central, subtemas, actores, posiciones "
    "y tono. NO repitas información entre subsecciones. NO agregues "
    "análisis externo. Devolvé únicamente el resumen integrado."
)


def render_user_fragmento(fragmento: str) -> str:
    """USER del primer paso: resumir un fragmento del discurso."""
    return render("summarizer_user_fragmento", fragmento=fragmento)


def render_user_global(
    titulo: str,
    fecha: str,
    resumenes_parciales: str,
) -> str:
    """USER del segundo paso: integrar parciales en un resumen global."""
    return render(
        "summarizer_user_global",
        titulo=titulo,
        fecha=fecha,
        resumenes_parciales=resumenes_parciales,
    )
