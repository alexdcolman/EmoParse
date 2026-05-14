# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_cache_keys
#
#  Tests del generador de claves. Verifica:
#  - Determinismo: mismo input = mismo digest.
#  - Sensibilidad: cambios mínimos = digest distinto.
#  - Estabilidad: None y "" se tratan igual (consistencia cross-run).
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from emoparse.core.cache.keys import make_cache_key
from emoparse.storage.models import Versions


def _key(**overrides: object) -> str:
    """Helper: construye una key con defaults razonables. Devuelve el digest."""
    defaults = {
        "model_alias": "test-model",
        "system": "system_default",
        "user": "user_default",
        "schema_qualname": "module.SchemaX",
        "seed": 42,
        "versions": Versions(knowledge="kv1", prompt="pv1", ontology="ov1", schema="sv1"),
    }
    defaults.update(overrides)
    return make_cache_key(**defaults).digest  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════════════
#  Determinismo
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterminism:

    def test_same_inputs_same_digest(self) -> None:
        d1 = _key()
        d2 = _key()
        assert d1 == d2

    def test_digest_is_hex_string(self) -> None:
        d = _key()
        assert isinstance(d, str)
        assert len(d) == 64  # SHA-256
        assert all(c in "0123456789abcdef" for c in d)


# ══════════════════════════════════════════════════════════════════════════════
#  Sensibilidad: cualquier cambio = digest distinto
# ══════════════════════════════════════════════════════════════════════════════


class TestSensitivity:

    def test_model_alias_affects(self) -> None:
        assert _key(model_alias="A") != _key(model_alias="B")

    def test_system_affects(self) -> None:
        assert _key(system="S1") != _key(system="S2")

    def test_user_affects(self) -> None:
        assert _key(user="U1") != _key(user="U2")

    def test_schema_qualname_affects(self) -> None:
        assert _key(schema_qualname="X") != _key(schema_qualname="Y")

    def test_seed_affects(self) -> None:
        assert _key(seed=1) != _key(seed=2)

    def test_each_version_affects_independently(self) -> None:
        """Cambiar una version invalida sin afectar las otras combinaciones."""
        base = Versions(knowledge="kv", prompt="pv", ontology="ov", schema="sv")
        d_base = _key(versions=base)

        # Cada cambio individual genera un digest distinto.
        d_kv = _key(versions=Versions(knowledge="kv2", prompt="pv", ontology="ov", schema="sv"))
        d_pv = _key(versions=Versions(knowledge="kv", prompt="pv2", ontology="ov", schema="sv"))
        d_ov = _key(versions=Versions(knowledge="kv", prompt="pv", ontology="ov2", schema="sv"))
        d_sv = _key(versions=Versions(knowledge="kv", prompt="pv", ontology="ov", schema="sv2"))

        # Todos distintos del base.
        assert {d_base, d_kv, d_pv, d_ov, d_sv} == {d_base, d_kv, d_pv, d_ov, d_sv}
        assert len({d_base, d_kv, d_pv, d_ov, d_sv}) == 5  # los 5 son distintos


# ══════════════════════════════════════════════════════════════════════════════
#  Estabilidad: None y "" deben tratarse igual
# ══════════════════════════════════════════════════════════════════════════════


class TestNoneVsEmpty:

    def test_seed_none_vs_zero_distinct(self) -> None:
        """seed=None y seed=0 son entidades distintas: 0 es una seed válida."""
        assert _key(seed=None) != _key(seed=0)

    def test_schema_qualname_none_vs_empty_string(self) -> None:
        """schema_qualname=None y "" se tratan igual: no hay schema en
        ambos casos. Esto es relevante para evitar dobles entradas
        cuando un caller pasa "" en lugar de None."""
        d_none = _key(schema_qualname=None)
        d_empty = _key(schema_qualname="")
        assert d_none == d_empty

    def test_versions_none_vs_empty_string(self) -> None:
        """Versions(prompt=None) y Versions(prompt="") generan misma key."""
        v1 = Versions(prompt=None)
        v2 = Versions(prompt="")
        assert _key(versions=v1) == _key(versions=v2)


# ══════════════════════════════════════════════════════════════════════════════
#  Metadata del CacheKey
# ══════════════════════════════════════════════════════════════════════════════


class TestKeyMetadata:

    def test_metadata_fields_populated(self) -> None:
        key = make_cache_key(
            model_alias="qwen3-14b",
            system="s",
            user="u",
            schema_qualname="m.S",
            seed=42,
            versions=Versions(knowledge="kv", prompt="pv"),
        )
        assert key.model_alias == "qwen3-14b"
        assert key.schema_qualname == "m.S"
        assert key.knowledge_version == "kv"
        assert key.prompt_version == "pv"
        # Las que no se pasaron quedan None.
        assert key.ontology_version is None
        assert key.schema_version is None
