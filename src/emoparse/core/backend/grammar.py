# ══════════════════════════════════════════════════════════════════════════════
#  emoparse.core.backend.grammar
#
#  Alias de compatibilidad del convertidor Pydantic v2 → GBNF.
# ══════════════════════════════════════════════════════════════════════════════

from emoparse.core.grammar import PRIMITIVE_RULES, GrammarError, schema_to_gbnf

__all__ = ["GrammarError", "PRIMITIVE_RULES", "schema_to_gbnf"]
