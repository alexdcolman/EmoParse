# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_v11_desviacion_ontologica
#
#  Cobertura de V11_DesviacionOntologica: emoción cubierta/no cubierta,
#  valores esperado/tolerado/fuera, aliases, y múltiples dimensiones.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.domain.validators.rules import V11_DesviacionOntologica


# ── Ontología mínima de fixture ───────────────────────────────────────────────

ONTOLOGIA_FIXTURE: dict = {
    "version": "v1",
    "emociones": {
        "ira": {
            "aliases": ["enojo", "rabia", "indignacion", "cólera"],
            "foria":           {"esperado": ["disforico"], "tolerado": ["ambiforico"]},
            "intensidad":      {"esperado": ["alta"],      "tolerado": ["neutra_ambivalente"]},
            "dominancia":      {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
            "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]},
        },
        "alegria": {
            "aliases": ["alegría", "felicidad", "júbilo"],
            "foria":           {"esperado": ["euforico"], "tolerado": ["ambiforico"]},
            "intensidad":      {"esperado": ["alta", "neutra_ambivalente"], "tolerado": ["baja"]},
            "dominancia":      {"esperado": ["corporal", "mixta"], "tolerado": ["cognoscitiva"]},
            "modo_existencia": {"esperado": ["realizada", "actual"], "tolerado": ["potencial"]},
        },
    },
}

# ── Kwargs base de una emoción válida (ira bien caracterizada) ────────────────

BASE_IRA_OK = dict(
    codigo="TEST-001",
    frase_idx=0,
    emocion_idx=0,
    experienciador="ciudadanos",
    tipo_emocion="ira",
    modo_existencia="realizada",
    foria="disforico",
    dominancia="corporal",
    intensidad="alta",
    tipo_fuente="actor",
    fuente="el gobierno",
    enunciador="presidente",
    enunciatarios=[],
)


@pytest.fixture()
def v11() -> V11_DesviacionOntologica:
    return V11_DesviacionOntologica(ONTOLOGIA_FIXTURE)


# ── Tests: emoción cubierta, caracterización correcta ────────────────────────

class TestEmocionesCubiertasOk:

    def test_ira_esperado_sin_issues(self, v11: V11_DesviacionOntologica) -> None:
        """Todos los valores en 'esperado' → 0 issues."""
        issues = v11.validate(**BASE_IRA_OK)
        assert issues == []

    def test_ira_tolerado_sin_issues(self, v11: V11_DesviacionOntologica) -> None:
        """Foria en 'tolerado' → 0 issues."""
        kwargs = {**BASE_IRA_OK, "foria": "ambiforico"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_ira_intensidad_tolerado_sin_issues(self, v11: V11_DesviacionOntologica) -> None:
        """Intensidad en 'tolerado' → 0 issues."""
        kwargs = {**BASE_IRA_OK, "intensidad": "neutra_ambivalente"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_alegria_esperado_sin_issues(self, v11: V11_DesviacionOntologica) -> None:
        """Alegría bien caracterizada → 0 issues."""
        kwargs = {
            **BASE_IRA_OK,
            "tipo_emocion": "alegria",
            "foria": "euforico",
            "intensidad": "alta",
            "dominancia": "corporal",
            "modo_existencia": "realizada",
        }
        issues = v11.validate(**kwargs)
        assert issues == []


# ── Tests: emoción cubierta, caracterización fuera de rango ──────────────────

class TestEmocionesCubiertasDesviadas:

    def test_foria_fuera_emite_issue(self, v11: V11_DesviacionOntologica) -> None:
        """Foria euforico en ira (no permitido) → 1 issue."""
        kwargs = {**BASE_IRA_OK, "foria": "euforico"}
        issues = v11.validate(**kwargs)
        assert len(issues) == 1
        assert issues[0].validator_id == "V11_desviacion_ontologica"
        assert "foria" in issues[0].contexto["dim"]
        assert issues[0].contexto["value"] == "euforico"

    def test_intensidad_fuera_emite_issue(self, v11: V11_DesviacionOntologica) -> None:
        """Intensidad baja en ira (no permitido) → 1 issue."""
        kwargs = {**BASE_IRA_OK, "intensidad": "baja"}
        issues = v11.validate(**kwargs)
        assert len(issues) == 1
        assert issues[0].contexto["dim"] == "intensidad"

    def test_dominancia_fuera_emite_issue(self, v11: V11_DesviacionOntologica) -> None:
        """Dominancia cognoscitiva está en 'tolerado' para ira → 0 issues."""
        kwargs = {**BASE_IRA_OK, "dominancia": "cognoscitiva"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_modo_existencia_fuera_emite_issue(self, v11: V11_DesviacionOntologica) -> None:
        """Modo virtual en ira (no en esperado ni tolerado) → 1 issue."""
        kwargs = {**BASE_IRA_OK, "modo_existencia": "virtual"}
        issues = v11.validate(**kwargs)
        assert len(issues) == 1
        assert issues[0].contexto["dim"] == "modo_existencia"

    def test_multiples_dimensiones_desviadas(self, v11: V11_DesviacionOntologica) -> None:
        """Dos dimensiones fuera de rango → 2 issues."""
        kwargs = {**BASE_IRA_OK, "foria": "euforico", "intensidad": "baja"}
        issues = v11.validate(**kwargs)
        assert len(issues) == 2
        dims = {i.contexto["dim"] for i in issues}
        assert dims == {"foria", "intensidad"}

    def test_issue_contiene_esperado_y_tolerado(self, v11: V11_DesviacionOntologica) -> None:
        """El contexto del issue expone esperado y tolerado."""
        kwargs = {**BASE_IRA_OK, "foria": "euforico"}
        issues = v11.validate(**kwargs)
        assert "esperado" in issues[0].contexto
        assert "tolerado" in issues[0].contexto
        assert "disforico" in issues[0].contexto["esperado"]

    def test_issue_codigo_y_coords(self, v11: V11_DesviacionOntologica) -> None:
        """El issue propaga codigo, frase_idx y emocion_idx correctamente."""
        kwargs = {**BASE_IRA_OK, "foria": "euforico", "codigo": "X-99",
                  "frase_idx": 3, "emocion_idx": 7}
        issues = v11.validate(**kwargs)
        assert issues[0].codigo == "X-99"
        assert issues[0].frase_idx == 3
        assert issues[0].emocion_idx == 7


# ── Tests: emoción no cubierta ────────────────────────────────────────────────

class TestEmocioneNoCubierta:

    def test_emocion_desconocida_sin_issues(self, v11: V11_DesviacionOntologica) -> None:
        """Emoción no en la ontología → 0 issues (sin penalizar)."""
        kwargs = {**BASE_IRA_OK, "tipo_emocion": "euforia_existencial"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_cadena_vacia_sin_issues(self, v11: V11_DesviacionOntologica) -> None:
        """tipo_emocion vacío → 0 issues."""
        kwargs = {**BASE_IRA_OK, "tipo_emocion": ""}
        issues = v11.validate(**kwargs)
        assert issues == []


# ── Tests: aliases ────────────────────────────────────────────────────────────

class TestAliases:

    def test_alias_directo_esperado(self, v11: V11_DesviacionOntologica) -> None:
        """Alias 'enojo' mapea a 'ira'; bien caracterizado → 0 issues."""
        kwargs = {**BASE_IRA_OK, "tipo_emocion": "enojo"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_alias_con_tilde_esperado(self, v11: V11_DesviacionOntologica) -> None:
        """Alias 'cólera' (con tilde) mapea a 'ira' → 0 issues."""
        kwargs = {**BASE_IRA_OK, "tipo_emocion": "cólera"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_alias_detecta_desviacion(self, v11: V11_DesviacionOntologica) -> None:
        """Alias 'rabia' con foria euforico → 1 issue (aplica constraints de ira)."""
        kwargs = {**BASE_IRA_OK, "tipo_emocion": "rabia", "foria": "euforico"}
        issues = v11.validate(**kwargs)
        assert len(issues) == 1

    def test_alias_con_mayusculas(self, v11: V11_DesviacionOntologica) -> None:
        """'Enojo' con mayúscula inicial → misma normalización."""
        kwargs = {**BASE_IRA_OK, "tipo_emocion": "Enojo"}
        issues = v11.validate(**kwargs)
        assert issues == []

    def test_alias_alegria_con_tilde(self, v11: V11_DesviacionOntologica) -> None:
        """'alegría' (con tilde) mapea a 'alegria' → 0 issues con valores esperados."""
        kwargs = {
            **BASE_IRA_OK,
            "tipo_emocion": "alegría",
            "foria": "euforico",
            "intensidad": "alta",
            "dominancia": "corporal",
            "modo_existencia": "realizada",
        }
        issues = v11.validate(**kwargs)
        assert issues == []


# ── Tests: construcción con ontología vacía o malformada ─────────────────────

class TestConstruccionOntologia:

    def test_ontologia_vacia_no_emite_issues(self) -> None:
        """Ontología sin entradas → 0 issues para cualquier emoción."""
        v11 = V11_DesviacionOntologica({"version": "v1", "emociones": {}})
        issues = v11.validate(**BASE_IRA_OK)
        assert issues == []

    def test_ontologia_sin_clave_emociones(self) -> None:
        """Dict sin 'emociones' → lookup vacío → 0 issues."""
        v11 = V11_DesviacionOntologica({})
        issues = v11.validate(**BASE_IRA_OK)
        assert issues == []

    def test_entrada_sin_constraints_no_emite_issues(self) -> None:
        """Entrada en ontología sin constraints de dimensión → 0 issues."""
        ont = {"emociones": {"ira": {"aliases": ["enojo"]}}}
        v11 = V11_DesviacionOntologica(ont)
        issues = v11.validate(**BASE_IRA_OK)
        assert issues == []
