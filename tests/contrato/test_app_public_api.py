"""Contratos de la API pública de la capa de datos del dashboard."""

from emoparse.app import data as data_layer
from emoparse.app import get_emociones as public_get_emociones
from emoparse.storage.simulacros import get_emociones, get_emociones_enriched


def test_public_get_emociones_reexport_is_preserved() -> None:
    """El formatter/linter no debe eliminar el reexport público histórico."""
    assert public_get_emociones is get_emociones


def test_enriched_data_reexport_is_preserved() -> None:
    """Las tabs siguen accediendo al helper enriquecido desde app.data."""
    assert data_layer.get_emociones_enriched is get_emociones_enriched
