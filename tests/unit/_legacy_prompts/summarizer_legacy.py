# Legacy summarizer prompt — copia textual del original (string.Template).
# Se usa solo en tests para asegurar byte-equivalencia con el wrapper Jinja2.

from __future__ import annotations

from string import Template


SYSTEM_FRAGMENTO = (
    "Sos un asistente que resume texto. Tu tarea es generar resúmenes "
    "fieles a la fuente, conservando actores, acciones principales y "
    "el tono general. NO inventes información que no esté en el texto. "
    "NO agregues análisis ni interpretación. Devolvé únicamente el "
    "resumen, sin preámbulos como 'Aquí está el resumen:' ni comentarios."
)


USER_FRAGMENTO_TEMPLATE = Template(
    """
Resumí el siguiente fragmento en 2-3 oraciones.

FRAGMENTO:
$fragmento
""".strip()
)


SYSTEM_GLOBAL = (
    "Sos un asistente que integra resúmenes parciales en uno global. "
    "Tu objetivo es producir un único resumen coherente del discurso "
    "completo, identificando tema central, subtemas, actores, posiciones "
    "y tono. NO repitas información entre subsecciones. NO agregues "
    "análisis externo. Devolvé únicamente el resumen integrado."
)


USER_GLOBAL_TEMPLATE = Template(
    """
TÍTULO DEL DISCURSO: $titulo
FECHA: $fecha

RESÚMENES PARCIALES:
$resumenes_parciales

Generá un resumen global de 4-6 oraciones que:
- Identifique el tema central y los subtemas principales.
- Mencione los actores y posiciones más relevantes.
- Refleje el tono general del discurso.
- No repita información redundante entre los resúmenes parciales.
""".strip()
)


def render_user_fragmento(fragmento):
    return USER_FRAGMENTO_TEMPLATE.substitute(fragmento=fragmento)


def render_user_global(titulo, fecha, resumenes_parciales):
    return USER_GLOBAL_TEMPLATE.substitute(
        titulo=titulo, fecha=fecha, resumenes_parciales=resumenes_parciales,
    )
