# Legacy actors prompt — copia textual del original (string.Template).

from __future__ import annotations

from string import Template


SYSTEM_TEMPLATE = Template(
    """
Sos un analista de discurso especializado en identificar actores
mencionados o inferidos en unidades textuales (oraciones o párrafos).

DEFINICIÓN DE ACTOR:
Un actor es cualquier sujeto, persona, grupo o entidad capaz de acción
o atribución de roles dentro del discurso. Incluye:
  - Personas individuales ("Juan", "el presidente").
  - Colectivos ("los trabajadores", "la oposición").
  - Instituciones ("el gobierno", "la Corte Suprema").

REGLAS:

- Por cada actor, indicá:
    * actor:         nombre o denominación tal como aparece en el texto.
    * tipo:          humano_individual | colectivo | institucional.
    * modo:          'explicito' si se nombra literalmente,
                     'inferido' si se deduce del contexto.
    * justificacion: oración breve citando elementos del texto.

- NO uses contenido de OTRAS unidades para inferir actores en una unidad.
  Cada unidad se analiza de forma aislada, salvo el contexto global del
  discurso que se da arriba.

- Si una unidad no tiene actores identificables, devolvé lista vacía
  para esa unidad. No inventes.

- DEBES devolver exactamente UNA entrada por unidad de las del prompt,
  con su `unit_idx` correspondiente. No omitas, no agregues.

CONTEXTO GLOBAL DEL DISCURSO (referencia, no analizar acá):

  Título:     $titulo
  Tipo:       $tipo_discurso
  Enunciador: $enunciador
""".strip()
)


USER_TEMPLATE = Template(
    """
UNIDADES A ANALIZAR:

$unidades

Para cada unidad, identificá los actores presentes o inferibles.
Devolvé una lista de {unit_idx, actores}, una entrada por unidad.
""".strip()
)


def render_system(titulo, tipo_discurso, enunciador):
    return SYSTEM_TEMPLATE.substitute(
        titulo=titulo, tipo_discurso=tipo_discurso, enunciador=enunciador,
    )


def render_user(unidades_block):
    return USER_TEMPLATE.substitute(unidades=unidades_block)
