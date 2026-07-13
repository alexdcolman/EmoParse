# ══════════════════════════════════════════════════════════════════════════════
#  Tests de emoparse.evaluation (alpha de Krippendorff y matching golden)
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.evaluation.agreement import krippendorff_alpha
from emoparse.evaluation.matching import build_alias_map, match_units

pytestmark = pytest.mark.unit

NA = None


class TestKrippendorffAlpha:
    def test_ejemplo_canonico_publicado(self):
        # Krippendorff (2011), 4 anotadores × 12 unidades con faltantes.
        data = [
            [1, 2, 3, 3, 2, 1, 4, 1, 2, NA, NA, NA],
            [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, NA, 3],
            [NA, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, NA],
            [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, NA],
        ]
        assert abs(krippendorff_alpha(data, "nominal") - 0.743) < 0.002
        assert abs(krippendorff_alpha(data, "interval") - 0.849) < 0.002
        assert abs(krippendorff_alpha(data, "ordinal") - 0.815) < 0.002

    def test_acuerdo_perfecto(self):
        data = [["a", "b", "a"], ["a", "b", "a"], ["a", "b", "a"]]
        assert krippendorff_alpha(data, "nominal") == pytest.approx(1.0)

    def test_categoria_unica_indefinido(self):
        data = [["a", "a"], ["a", "a"]]
        assert krippendorff_alpha(data, "nominal") is None

    def test_datos_insuficientes(self):
        assert krippendorff_alpha([["a", NA], [NA, "b"]], "nominal") is None

    def test_faltantes_como_string(self):
        data = [["si", "no", "NA"], ["si", "no", ""], ["si", "si", "no"]]
        alpha = krippendorff_alpha(data, "nominal")
        assert alpha is not None and 0 < alpha < 1


class TestMatching:
    ONTOLOGIA = {"emociones": {
        "ira": {"aliases": ["bronca", "enojo", "furia"]},
        "alegria": {"aliases": ["felicidad", "euforia"]},
        "miedo": {"aliases": ["temor"]},
    }}

    def _alias(self):
        return build_alias_map(self.ONTOLOGIA)

    def test_deteccion_y_dimensiones(self):
        golden = {
            ("p1", 0): [{"experienciador": "la autora del post",
                         "tipo_emocion": "bronca", "foria": "disforico"}],
            ("p2", 0): [],  # unidad neutra anotada
            ("p3", 0): [{"experienciador": "los jubilados",
                         "tipo_emocion": "miedo"}],
        }
        preds = {
            # tipo alias distinto pero canónico igual; experienciador solapa
            ("p1", 0): [{"experienciador": "autora", "tipo_emocion": "enojo",
                         "foria": "disforico"}],
            # falso positivo sobre la unidad neutra
            ("p2", 0): [{"experienciador": "x", "tipo_emocion": "alegría"}],
            # miss total en p3
            ("p3", 0): [],
        }
        r = match_units(golden, preds, self._alias())
        assert (r.tp, r.fp, r.fn) == (1, 1, 1)
        assert r.precision == pytest.approx(0.5)
        assert r.recall == pytest.approx(0.5)
        assert r.dim_accuracy("tipo") == pytest.approx(1.0)
        assert r.dim_accuracy("foria") == pytest.approx(1.0)

    def test_acentos_no_rompen_canonico(self):
        golden = {("p", 0): [{"experienciador": "el pueblo",
                              "tipo_emocion": "alegría"}]}
        preds = {("p", 0): [{"experienciador": "pueblo",
                             "tipo_emocion_canonico": "alegria"}]}
        r = match_units(golden, preds, self._alias())
        assert r.tp == 1 and r.dim_accuracy("tipo") == 1.0

    def test_unidad_no_procesada_cuenta_fn(self):
        golden = {("p", 0): [{"experienciador": "x", "tipo_emocion": "miedo"}]}
        r = match_units(golden, {}, self._alias())
        assert (r.tp, r.fp, r.fn) == (0, 0, 1)

    def test_emparejamiento_greedy_prefiere_tipo(self):
        golden = {("p", 0): [
            {"experienciador": "el gobierno", "tipo_emocion": "miedo"},
            {"experienciador": "el gobierno", "tipo_emocion": "ira"},
        ]}
        preds = {("p", 0): [
            {"experienciador": "el gobierno", "tipo_emocion": "ira"},
        ]}
        r = match_units(golden, preds, self._alias())
        assert (r.tp, r.fp, r.fn) == (1, 0, 1)
        assert r.dim_accuracy("tipo") == 1.0  # emparejó con la de ira


class TestGenreFilter:
    def test_filtrado_por_genero(self):
        from emoparse.knowledge.genre_filter import filtrar_ontologia_por_genero
        onto = {"version": "v2", "emociones": {
            "ira": {"aliases": []},                       # base compartida
            "burla": {"aliases": [], "generos": ["tuit"]},
        }}
        tuit = filtrar_ontologia_por_genero(onto, "tuit")
        discurso = filtrar_ontologia_por_genero(onto, "discurso_presidencial")
        completa = filtrar_ontologia_por_genero(onto, None)
        assert set(tuit["emociones"]) == {"ira", "burla"}
        assert set(discurso["emociones"]) == {"ira"}
        assert set(completa["emociones"]) == {"ira", "burla"}
        # la original no se muta
        assert set(onto["emociones"]) == {"ira", "burla"}
