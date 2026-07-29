# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.grammar
#
#  Convertidor de Pydantic v2 → GBNF.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

import string

# ══════════════════════════════════════════════════════════════════════════════
#  Reglas primitivas reutilizables
# ══════════════════════════════════════════════════════════════════════════════

PRIMITIVE_RULES = r"""
boolean ::= "true" | "false"
null ::= "null"

#: Whitespace permitido entre tokens JSON (no dentro de strings). Se admite a
#: lo sumo UN blanco por separador: el JSON de salida no lleva indentación.
#: Con el tope anterior (32) el modelo emitía `,\n      ` entre campos, relleno
#: que no aporta información y consume presupuesto de completion — crítico
#: cuando el prompt deja pocos tokens libres.
ws ::= [ \t\n]{0,1}

#: El escape \uXXXX no se admite: es una vía de codificación redundante (JSON
#: acepta el carácter literal en UTF-8 para todo lo imprimible, y lo que sí
#: exige escape —comillas, barra, controles— ya lo cubre `strchar`), pero
#: cuesta seis caracteres crudos por cada carácter contado. Admitirla rompe la
#: única garantía que importa: que acotar caracteres acote la generación. Sin
#: ella, un carácter contado cuesta a lo sumo dos caracteres crudos.
#:
#: Piezas de un string JSON. `strchar` es un carácter visible o un escape que
#: no produce whitespace; `strsep` es un blanco (espacio literal o escape
#: \n \t \r \b \f). Un string alterna visible/blanco sin permitir blancos
#: consecutivos: con temperatura alta el sampler degeneraba en corridas de
#: espacios o de `\n` escapados hasta agotar el contexto (finish=length con la
#: salida llena de blancos). `strunit` es cualquiera de las dos y equivale a
#: UN carácter del string ya decodificado: es la unidad que cuentan las reglas
#: acotadas por `maxLength`.
strchar ::= [^ "\\\x7F\x00-\x1F] | "\\" ["\\]
strsep ::= " " | "\\" [nrtbf]
strunit ::= strchar | strsep
string ::= "\"" strchar ( strsep? strchar )* "\""

#: Números JSON: enteros, fracciones, exponentes, signo opcional.
integer ::= ("-"? ([0-9] | [1-9] [0-9]*))
number ::= ("-"? ([0-9] | [1-9] [0-9]*)) ("." [0-9]+)? ([eE] [-+]? [0-9]+)?
""".strip()

#: Caracteres válidos en un nombre de regla GBNF. llama.cpp NO admite '_'.
_ALLOWED_RULE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
)


# ══════════════════════════════════════════════════════════════════════════════
#  Errores
# ══════════════════════════════════════════════════════════════════════════════

class GrammarError(ValueError):
    """Schema no traducible a GBNF. Incluye path problemático para debugging."""


# ══════════════════════════════════════════════════════════════════════════════
#  API pública
# ══════════════════════════════════════════════════════════════════════════════

def schema_to_gbnf(
    schema: type[BaseModel],
    *,
    max_items: int | None = None,
) -> str:
    """Convierte un schema Pydantic v2 a GBNF.

    Root de la gramática: regla `root`.

    Args:
        schema: Schema Pydantic v2.
        max_items: Si se pasa y el top-level del schema es un array (p. ej. un
            `RootModel[list[...]]` de batch), acota ese array a EXACTAMENTE
            `max_items` elementos (min == max). Garantiza terminación y evita
            tanto el "runaway" (repetir ítems hasta el tope de tokens) como la
            lista vacía. No afecta schemas cuyo top-level no es array.

    Raises:
        GrammarError: si el schema usa features no soportadas.
    """
    js = schema.model_json_schema()
    if max_items is not None and js.get("type") == "array":
        n = max(1, int(max_items))
        js = dict(js)  # copia superficial: solo se tocan claves top-level
        js["minItems"] = n
        js["maxItems"] = n
    return _build_grammar(js)


# ══════════════════════════════════════════════════════════════════════════════
#  Builder interno
# ══════════════════════════════════════════════════════════════════════════════

class _GrammarBuilder:
    """Construcción de gramática GBNF a partir de JSON Schema.

    Mantiene dict `rules` nombre → cuerpo. Método `_visit` recorre schema y
    emite reglas. Resolución de referencias locales desde `$defs`.
    """

    def __init__(self, root_schema: dict[str, Any]) -> None:
        self._root = root_schema
        self._defs: dict[str, dict[str, Any]] = root_schema.get("$defs", {})
        self._rules: dict[str, str] = {}
        # Al resolver un $ref, la regla creada por _visit_object/_visit_array
        # usa el nombre original para evitar indirecciones tipo `Foo ::= Foo_2`.
        self._reserved_name: str | None = None

    # ── Entry point ──────────────────────────────────────────────────────────

    def build(self) -> str:
        # Se reserva `root` como nombre para que el top-level object/array cree
        # directamente la regla `root` en lugar de derivar otro nombre.
        self._reserved_name = "root"
        root_body = self._visit(self._root, path="#")

        if root_body != "root":
            self._rules["root"] = root_body

        for name, body in list(self._rules.items()):
            if body == "<<resolving>>":
                raise GrammarError(f"Regla '{name}' quedó sin resolver")

        lines: list[str] = []
        # Root primero — convención GBNF.
        lines.append(f"root ::= {self._rules.pop('root')}")
        for name, body in self._rules.items():
            lines.append(f"{name} ::= {body}")
        # Primitivas al final, separadas por una línea en blanco.
        lines.append("")
        lines.append(PRIMITIVE_RULES)
        return "\n".join(lines)

    # ── Visitor principal ────────────────────────────────────────────────────

    def _visit(self, node: dict[str, Any], *, path: str) -> str:
        """Devuelve cuerpo de regla GBNF para `node`.

        Objetos/arrays generan regla nombrada y referencia. Primitivos
        devuelven cuerpo inline.
        """
        # Resolver $ref locales primero.
        if "$ref" in node:
            ref_name = self._resolve_ref(node["$ref"], path=path)
            return ref_name

        # anyOf [T, null] representa campo opcional nullable.
        if "anyOf" in node:
            return self._visit_anyof(node["anyOf"], path=path)

        # enum (típicamente strings).
        if "enum" in node:
            return self._visit_enum(node["enum"], path=path)

        # const: Pydantic serializa así un Literal de un solo valor. Sin este
        # caso, el nodo caería en `type: "string"` y generaría un string libre
        # (sin la restricción de valor y sin cota de longitud).
        if "const" in node:
            return self._visit_enum([node["const"]], path=path)

        node_type = node.get("type")

        if node_type == "object":
            return self._visit_object(node, path=path)
        if node_type == "array":
            return self._visit_array(node, path=path)
        if node_type == "string":
            # Bound opcional por maxLength (Pydantic `Field(max_length=N)` sobre
            # un str). Sin maxLength se conserva la primitiva `string` ilimitada.
            if "maxLength" in node:
                return self._bounded_string_rule(
                    min_len=node.get("minLength", 1),
                    max_len=node["maxLength"],
                )
            return "string"
        if node_type == "integer":
            return "integer"
        if node_type == "number":
            return "number"
        if node_type == "boolean":
            return "boolean"
        if node_type == "null":
            return "null"

        # Caso allOf con único $ref: se desempaqueta.
        if "allOf" in node and len(node["allOf"]) == 1:
            return self._visit(node["allOf"][0], path=path + "/allOf/0")

        raise GrammarError(
            f"Schema no soportado en {path}: keys={list(node.keys())}, type={node_type}"
        )

    # ── object → secuencia de campos ─────────────────────────────────────────

    def _visit_object(self, node: dict[str, Any], *, path: str) -> str:
        """Genera regla GBNF para un objeto JSON.

        Crea regla nombrada con propiedades requeridas; campos opcionales se omiten.
        """
        # Captura y limpia reserved_name al entrar; aplica solo a este nivel.
        reserved = self._reserved_name
        self._reserved_name = None

        properties: dict[str, dict[str, Any]] = node.get("properties", {})
        required: set[str] = set(node.get("required", []))

        if not properties:
            return r'"{" ws "}"'

        prop_names = sorted(
            properties.keys(),
            key=lambda k: (k not in required, k),
        )

        emitted: list[str] = []
        for i, name in enumerate(prop_names):
            if name not in required:
                continue
            prop_schema = properties[name]
            value_rule = self._visit(prop_schema, path=f"{path}/properties/{name}")
            sep = " " if i == 0 else r' "," ws '
            # Nombre escapado como literal JSON.
            key_literal = self._json_string_literal(name)
            emitted.append(f'{sep}{key_literal} ws ":" ws {value_rule}')

        if not emitted:
            return r'"{" ws "}"'

        body = r'"{" ws ' + " ".join(emitted) + r' ws "}"'
        # Si se resuelve un $ref, usar nombre reservado en lugar de generar
        # uno nuevo.
        if reserved is not None:
            rule_name = reserved
        else:
            rule_name = self._make_rule_name(node, path=path, prefix="obj")
        self._rules[rule_name] = body
        return rule_name

    # ── array ────────────────────────────────────────────────────────────────

    def _visit_array(self, node: dict[str, Any], *, path: str) -> str:
        """Genera regla GBNF para un array JSON.

        Crea regla nombrada con patrón estándar de lista separada por comas.
        """
        reserved = self._reserved_name
        self._reserved_name = None

        items = node.get("items")
        if items is None:
            raise GrammarError(f"Array sin `items` en {path}: no soportado")
        if isinstance(items, list):
            raise GrammarError(
                f"Array con `prefixItems`/tuple en {path}: no soportado"
            )

        item_rule = self._visit(items, path=f"{path}/items")
        # Bound opcional: si el schema declara `maxItems` (Pydantic
        # `Field(max_length=N)` sobre una lista), la gramática acota la
        # repetición por construcción, garantizando terminación. Sin
        # `maxItems`, se conserva exactamente el patrón ilimitado original.
        max_items = node.get("maxItems")
        min_items = node.get("minItems", 0)
        if max_items is not None:
            body = self._bounded_array_body(
                item_rule,
                min_items=min_items,
                max_items=max_items,
            )
        elif min_items and min_items > 0:
            body = self._min_array_body(item_rule, min_items)
        else:
            # Lista posiblemente vacía con elementos separados por coma.
            # Patrón GBNF estándar para `[item (, item)*]`:
            #   "[" ws ( item (ws "," ws item)* )? ws "]"
            body = (
                r'"[" ws '
                r'( ' + item_rule + r' (ws "," ws ' + item_rule + r')* )? '
                r'ws "]"'
            )
        if reserved is not None:
            rule_name = reserved
            self._rules[rule_name] = body
            return rule_name
        # Sin reserved name: root_body se asigna a `root`. Arrays siempre
        # generan regla nombrada para consistencia.
        rule_name = self._make_rule_name(node, path=path, prefix="arr")
        self._rules[rule_name] = body
        return rule_name

    # ── array acotado (maxItems) ─────────────────────────────────────────────

    @staticmethod
    def _bounded_array_body(item_rule: str, *, min_items: int, max_items: int) -> str:
        """Cuerpo GBNF para un array con [min_items, max_items] elementos.

        Usa solo `?`, `()` y literales — sin el operador `{m,n}` — para ser
        compatible con cualquier versión de GBNF de llama.cpp. La repetición
        acotada se expande como opcionales anidados (un elemento solo aparece
        si apareció el anterior), lo que además prohíbe coma final.
        """
        lo = max(0, int(min_items))
        hi = int(max_items)
        if hi < lo:
            raise GrammarError(
                f"Array con maxItems ({hi}) < minItems ({lo}): inconsistente"
            )
        if hi == 0:
            return r'"[" ws "]"'

        sep_item = r'ws "," ws ' + item_rule

        def opt_tail(k: int) -> str:
            # k elementos adicionales opcionales, anidados (contiguos).
            if k <= 0:
                return ""
            return r'( ' + sep_item + r' ' + opt_tail(k - 1) + r' )?'

        if lo == 0:
            # Cero-o-más, hasta hi: head opcional + cola opcional.
            inner = item_rule + r' ' + opt_tail(hi - 1)
            return r'"[" ws ( ' + inner + r' )? ws "]"'

        # head requerido de `lo` elementos, luego cola opcional hasta hi.
        head = item_rule
        for _ in range(lo - 1):
            head += r' ' + sep_item
        tail = opt_tail(hi - lo)
        return r'"[" ws ' + head + r' ' + tail + r' ws "]"'

    @staticmethod
    def _min_array_body(item_rule: str, min_items: int) -> str:
        """Cuerpo GBNF para un array con AL MENOS min_items elementos (sin tope).

        Fuerza `min_items` obligatorios y permite más con `*`. Sirve para
        prohibir el array vacío `[]` (con min_items=1) sin acotar por arriba.
        """
        lo = max(1, int(min_items))
        head = item_rule
        for _ in range(lo - 1):
            head += r' ws "," ws ' + item_rule
        return r'"[" ws ' + head + r' (ws "," ws ' + item_rule + r')* ws "]"'

    # ── string acotado (maxLength) ───────────────────────────────────────────

    def _bounded_string_rule(self, *, min_len: int, max_len: int) -> str:
        """Regla GBNF para un string JSON acotado, sin blancos consecutivos.

        Conserva la misma alternancia que `string` —un carácter, a lo sumo un
        separador, otro carácter— y además acota la repetición, de modo que
        garantice las dos cosas a la vez: que el string termine y que no pueda
        degenerar en una tirada de blancos. Contar `strunit` suelto daba lo
        primero pero perdía lo segundo, y una salida como
        `"texto. \\n \\n \\n ..."` quedaba habilitada: son separadores
        consecutivos, que la alternancia prohíbe.

        Cuentas: el cuerpo es un carácter seguido de `grupos` repeticiones de
        (separador opcional + carácter), así que produce entre `1 + minimo` y
        `1 + 2·grupos` caracteres. `grupos` se elige de modo que el máximo
        nunca supere `max_len`: la gramática queda más estricta que
        `maxLength`, nunca más laxa, así que la validación posterior no puede
        rechazar lo que el sampler produjo.

        La contrapartida es que baja la capacidad efectiva: con prosa (un
        blanco cada seis caracteres) un bound de N admite alrededor de 0,57·N
        caracteres. Es el precio de que la cota sea real.
        """
        lo = max(0, int(min_len))
        hi = int(max_len)
        if hi < lo:
            raise GrammarError(
                f"String con maxLength ({hi}) < minLength ({lo}): inconsistente"
            )
        rule_name = f"string-max-{lo}-{hi}"
        if rule_name in self._rules:
            return rule_name
        if hi == 0:
            self._rules[rule_name] = r'"\"" "\""'
            return rule_name
        grupos = (hi - 1) // 2
        minimo = max(lo - 1, 0)
        if minimo > grupos:
            raise GrammarError(
                f"String con minLength ({lo}) incompatible con la cota real de "
                f"maxLength ({hi}): el mínimo exige más caracteres de los que "
                f"la regla puede garantizar sin habilitar blancos "
                f"consecutivos. Bajá minLength o subí maxLength."
            )
        cuerpo = (
            r'strchar ( strsep? strchar ){' + f"{minimo},{grupos}" + r'}'
            if grupos else "strchar"
        )
        self._rules[rule_name] = r'"\"" ' + cuerpo + r' "\""'
        return rule_name

    # ── enum ─────────────────────────────────────────────────────────────────

    def _visit_enum(self, values: list[Any], *, path: str) -> str:
        """Genera regla GBNF para un enum.

        Soporta enums de strings y de enteros; otros tipos lanzan error. Los
        enteros se emiten como literal JSON sin comillas, lo que permite
        vocabularios cerrados cortos (un id en lugar de un identificador
        largo) sin perder la restricción del sampler.
        """
        if not values:
            raise GrammarError(f"Enum vacío en {path}")
        alternatives: list[str] = []
        for v in values:
            if isinstance(v, str):
                alternatives.append(self._json_string_literal(v))
            elif isinstance(v, int) and not isinstance(v, bool):
                alternatives.append(f'"{v}"')
            else:
                raise GrammarError(
                    f"Enum con valor no soportado en {path}: {v!r} "
                    f"({type(v).__name__})"
                )
        return f"({' | '.join(alternatives)})"

    # ── anyOf ────────────────────────────────────────────────────────────────

    def _visit_anyof(self, options: list[dict[str, Any]], *, path: str) -> str:
        """Genera regla GBNF para anyOf.

        Caso especial: [T, null] → campo opcional nullable.  
        Caso general: alternativas entre todas las opciones.
        """
        non_null = [o for o in options if o.get("type") != "null"]
        has_null = any(o.get("type") == "null" for o in options)

        if has_null and len(non_null) == 1:
            inner = self._visit(non_null[0], path=f"{path}/anyOf/0")
            return f"({inner} | null)"

        rules = [self._visit(o, path=f"{path}/anyOf/{i}") for i, o in enumerate(options)]
        return "(" + " | ".join(rules) + ")"

    # ── Resolución de $ref ───────────────────────────────────────────────────

    def _resolve_ref(self, ref: str, *, path: str) -> str:
        """Convierte $ref local en nombre de regla GBNF.

        Soporta solo refs locales `#/$defs/Name`. Refs externos no aplican.
        """
        prefix = "#/$defs/"
        if not ref.startswith(prefix):
            raise GrammarError(f"$ref no-local en {path}: {ref}")

        def_name = ref[len(prefix):]
        if def_name not in self._defs:
            raise GrammarError(f"$ref a definición inexistente en {path}: {ref}")

        rule_name = _sanitize_rule_name(def_name)
        if rule_name in self._rules:
            return rule_name

        # Reserva nombre para evitar recursión infinita en schemas cíclicos; usa
        # placeholder hasta definir.
        self._rules[rule_name] = "<<resolving>>"

        # Asigna reserved_name; _visit_object/_visit_array lo capturan localmente.
        self._reserved_name = rule_name
        body = self._visit(self._defs[def_name], path=f"#/$defs/{def_name}")

        # Si body coincide con nombre reservado, la regla ya se registró durante
        # el visit.
        if body == rule_name:
            return rule_name

        # Si body es distinto, el visit devolvió cuerpo inline; se registra como
        # alias.
        self._rules[rule_name] = body
        return rule_name

    # ── Helpers de naming ────────────────────────────────────────────────────

    def _make_rule_name(self, node: dict[str, Any], *, path: str, prefix: str) -> str:
        """Genera nombre de regla único basado en `title` o `path`.

        Si existe `title`, se usa. En caso contrario, se deriva del path.
        """
        title = node.get("title")
        if title:
            base = _sanitize_rule_name(title)
        else:
            # Path tipo "#/properties/name" → "properties-name".
            base = _sanitize_rule_name(
                path.replace("#/", "").replace("/", "-") or prefix
            )
            base = f"{prefix}-{base}"

        # Garantiza unicidad si ya existe (sufijo con '-', no '_').
        if base in self._rules:
            i = 2
            while f"{base}-{i}" in self._rules:
                i += 1
            base = f"{base}-{i}"
        return base

    @staticmethod
    def _json_string_literal(s: str) -> str:
        """Escapa cadena como literal JSON entre comillas para GBNF."""
        # GBNF permite comillas dobles para literales.
        # Escapa backslash y comillas internas.
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        # Caracteres de control no permitidos en literales GBNF.
        if any(ord(c) < 0x20 for c in escaped):
            raise GrammarError(f"String con caracteres de control: {s!r}")
        return f'"\\"{escaped}\\""'


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _sanitize_rule_name(name: str) -> str:
    """Convierte un nombre arbitrario en un identificador de regla GBNF válido."""
    out = [ch if ch in _ALLOWED_RULE_CHARS else "-" for ch in name]
    sanitized = "".join(out).lstrip("-")
    return sanitized or "rule"


def _build_grammar(schema: dict[str, Any]) -> str:
    """Wrapper que opera sobre dict y devuelve gramática GBNF."""
    return _GrammarBuilder(schema).build()
