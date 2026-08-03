Reglas heurísticas para la identificación de la estructura enunciativa:

Estas reglas orientan la identificación del enunciador principal y los enunciatarios (destinatarios) de un discurso. No inventes roles enunciativos; inferílos solo si hay indicios claros en el texto.

1. **Identificación del enunciador**
   - Buscá marcas de primera persona (singular o plural: "yo", "nosotros", "mi gestión", "nuestro gobierno") que señalen quién habla.
   - En discursos institucionales o protocolares, el cargo o rol puede sustituir al nombre propio.
   - Si el enunciador es colectivo ("el gobierno", "las fuerzas armadas"), registralo como tal.
   - Si es imposible determinarlo, usá "no identificado".

2. **Identificación de enunciatarios**
   - Buscá vocativos explícitos: "ciudadanos", "compatriotas", "señores diputados", "querida audiencia".
   - Inferí destinatarios implícitos desde el registro del discurso (formal/informal), el canal (cadena nacional, mitin, red social) y el tema.
   - Un discurso puede tener múltiples enunciatarios simultáneos: el destinatario principal y destinatarios secundarios o adversariales.

3. **Roles enunciativos según género discursivo**
   - Discurso político: prodestinatario (simpatizantes), paradestinatario (indecisos), contradestinatario (adversarios).
   - Redes sociales / tuits: prodestinatario, paradestinatario, contradestinatario, destinatario_mencionado (la cuenta interpelada vía @), audiencia_ambiente (el público indeterminado del archivo buscable).
   - Periodismo: lector_ciudadano, instancia_blanco, fuente_referente.
   - Asigná solo los roles válidos para el género identificado.
   - El rol va siempre en el campo `tipo`; el campo `actor` debe ser un referente concreto (persona, colectivo, institución o cuenta identificables), nunca una etiqueta de rol ("enunciador", "autor del post", "prodestinatario", "destinatario"). Única excepción: "audiencia ambiente", indeterminada por naturaleza.

4. **Marcas de polifonía y cita**
   - Si el discurso cita otras voces ("ellos dicen", "según X"), no confundas al citado con el enunciador.
   - El enunciador es siempre quien emite el discurso en el nivel primario de la enunciación.

5. **Contexto institucional y situacional**
   - Usá el tipo de discurso (asunción presidencial, conferencia de prensa, discurso de campaña) para inferir enunciador y enunciatarios típicos cuando no estén explicitados.
   - El lugar de emisión, la fecha y el canal pueden ser indicios para desambiguar.

Instrucciones generales:
- Priorizá las marcas textuales explícitas sobre la inferencia contextual.
- Si hay ambigüedad entre dos enunciatarios posibles, registrá ambos con su respectiva justificación.
- Evitá confundir actores mencionados en el contenido del discurso con el enunciatario.

Reglas adicionales:

- El referente emisor nunca es un identificador técnico (ids, URLs, URIs como "at://…").
- En los campos categoriales de identificación (`actor`, `nombre`, `clase`) no uses "enunciador", "enunciatario" ni otras etiquetas de análisis: nombrá el referente concreto. En las justificaciones sí puede usarse terminología analítica.
- En artículos periodísticos, la autoría declarada en la metadata tiene prioridad sobre el nombre del medio. El medio solo puede usarse si la nota carece de firma.
- Los colectivos de identificación pueden no existir: lista vacía válida. Hashtags temáticos o actores mencionados no son colectivos del enunciador salvo identificación explícita.
- Justificaciones sintéticas: una sola oración de no más de 25 palabras.
