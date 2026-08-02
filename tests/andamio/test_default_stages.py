# ══════════════════════════════════════════════════════════════════════════════
#  tests/andamio/test_default_stages
#
#  Contrato mínimo de stages activas y opt-in.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from emoparse.pipeline.runner import DEFAULT_ENABLED_STAGES


@pytest.mark.unit
def test_modalidad_remains_opt_in() -> None:
    assert "modalidad" not in DEFAULT_ENABLED_STAGES
    assert "emotions" in DEFAULT_ENABLED_STAGES
    assert "explode_emotions" in DEFAULT_ENABLED_STAGES
