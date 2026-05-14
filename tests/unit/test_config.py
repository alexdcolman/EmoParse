# ══════════════════════════════════════════════════════════════════════════════
#  tests.unit.test_config
#
#  Tests de carga + validación del config YAML.
# ══════════════════════════════════════════════════════════════════════════════

from __future__ import annotations

from pathlib import Path

import pytest

from emoparse.config import ConfigError, RunConfig, load_config, save_config


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════


_VALID_YAML = """
models:
  qwen3-14b:
    backend: llama_cpp
    path: models/qwen3.gguf
    temperature: 0.6
    seed: 42
  phi4-mini:
    backend: llama_cpp
    path: models/phi4.gguf
    temperature: 0.0

pipeline:
  stages:
    metadata: phi4-mini
    emotions: qwen3-14b
  cache_enabled: true

versions:
  knowledge: kv1
  prompt: pv1

paths:
  runs_dir: runs/
  models_dir: models/
"""


def _write(tmp_path: Path, content: str, name: str = "config.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════════════════
#  Carga válida
# ══════════════════════════════════════════════════════════════════════════════


class TestValidLoad:

    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        p = _write(tmp_path, _VALID_YAML)
        cfg = load_config(p)

        assert isinstance(cfg, RunConfig)
        assert "qwen3-14b" in cfg.models
        assert "phi4-mini" in cfg.models

    def test_pipeline_stages_loaded(self, tmp_path: Path) -> None:
        cfg = load_config(_write(tmp_path, _VALID_YAML))
        assert cfg.pipeline.stages == {
            "metadata": "phi4-mini",
            "emotions": "qwen3-14b",
        }

    def test_versions_loaded(self, tmp_path: Path) -> None:
        cfg = load_config(_write(tmp_path, _VALID_YAML))
        assert cfg.versions.knowledge == "kv1"
        assert cfg.versions.prompt == "pv1"
        # Las no especificadas quedan None.
        assert cfg.versions.ontology is None

    def test_defaults_applied(self, tmp_path: Path) -> None:
        """Cuando se omiten secciones opcionales, se aplican defaults."""
        minimal = """
models:
  m1:
    backend: llama_cpp
    path: x.gguf
"""
        cfg = load_config(_write(tmp_path, minimal))
        # Defaults del pipeline.
        assert cfg.pipeline.cache_enabled is True
        assert cfg.pipeline.max_retries == 3
        # Defaults del modelo.
        assert cfg.models["m1"].temperature == 0.0
        assert cfg.models["m1"].seed == 42
        assert cfg.models["m1"].n_gpu_layers == -1


class TestModelConfigForAlias:

    def test_returns_dict_with_all_keys(self, tmp_path: Path) -> None:
        cfg = load_config(_write(tmp_path, _VALID_YAML))
        d = cfg.model_config_for_alias("qwen3-14b")

        # Debe contener al menos el backend y el path.
        assert d["backend"] == "llama_cpp"
        assert d["path"] == "models/qwen3.gguf"
        # Y los defaults también.
        assert d["seed"] == 42
        assert d["temperature"] == 0.6

    def test_unknown_alias_raises(self, tmp_path: Path) -> None:
        cfg = load_config(_write(tmp_path, _VALID_YAML))
        with pytest.raises(KeyError, match="no definido"):
            cfg.model_config_for_alias("inexistente")


# ══════════════════════════════════════════════════════════════════════════════
#  Errores de carga
# ══════════════════════════════════════════════════════════════════════════════


class TestLoadErrors:

    def test_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="no encontrado"):
            load_config(tmp_path / "no_existe.yaml")

    def test_invalid_yaml_syntax(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "models:\n  x: [unclosed")
        with pytest.raises(ConfigError, match="YAML inválido"):
            load_config(p)

    def test_top_level_not_dict(self, tmp_path: Path) -> None:
        """Si el YAML es una lista en vez de un dict, error claro."""
        p = _write(tmp_path, "- foo\n- bar")
        with pytest.raises(ConfigError, match="mapping"):
            load_config(p)

    def test_unknown_backend(self, tmp_path: Path) -> None:
        """Backend 'ollama' fue removido — debe fallar la validación."""
        bad = """
models:
  legacy:
    backend: ollama
    path: x.gguf
"""
        p = _write(tmp_path, bad)
        with pytest.raises(ConfigError) as exc:
            load_config(p)
        assert "ollama" in str(exc.value).lower() or "backend" in str(exc.value).lower()

    def test_invalid_field_type(self, tmp_path: Path) -> None:
        """Pasar un str donde se espera int debe fallar."""
        bad = """
models:
  m1:
    backend: llama_cpp
    path: x.gguf
    temperature: "no_es_un_numero"
"""
        with pytest.raises(ConfigError, match="temperature"):
            load_config(_write(tmp_path, bad))

    def test_extra_field_in_pipeline_rejected(self, tmp_path: Path) -> None:
        """`extra='forbid'` en PipelineConfig: detecta typos en YAML."""
        bad = """
models:
  m1:
    backend: llama_cpp
    path: x.gguf
pipeline:
  cach_enabled: true
"""
        with pytest.raises(ConfigError):
            load_config(_write(tmp_path, bad))


# ══════════════════════════════════════════════════════════════════════════════
#  Save round-trip
# ══════════════════════════════════════════════════════════════════════════════


class TestSaveLoad:

    def test_round_trip(self, tmp_path: Path) -> None:
        """Cargar, guardar, cargar de nuevo: el config debe ser equivalente."""
        cfg1 = load_config(_write(tmp_path, _VALID_YAML))
        out_path = tmp_path / "saved.yaml"
        save_config(cfg1, out_path)

        cfg2 = load_config(out_path)
        assert cfg2.models == cfg1.models
        assert cfg2.pipeline.stages == cfg1.pipeline.stages
        assert cfg2.versions.knowledge == cfg1.versions.knowledge

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        cfg = load_config(_write(tmp_path, _VALID_YAML))
        nested = tmp_path / "a" / "b" / "c" / "config.yaml"
        save_config(cfg, nested)
        assert nested.exists()


# ══════════════════════════════════════════════════════════════════════════════
#  Expansión de variables de entorno
# ══════════════════════════════════════════════════════════════════════════════


class TestEnvVarExpansion:

    def test_env_var_with_default_used_when_unset(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EMOPARSE_TEST_VAR", raising=False)
        yaml_text = """
models:
  m1:
    backend: llama_cpp
    path: ${EMOPARSE_TEST_VAR:-default_path/x.gguf}
"""
        cfg = load_config(_write(tmp_path, yaml_text))
        assert cfg.models["m1"].path == "default_path/x.gguf"

    def test_env_var_with_default_overridden(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EMOPARSE_TEST_VAR", "/custom/path/x.gguf")
        yaml_text = """
models:
  m1:
    backend: llama_cpp
    path: ${EMOPARSE_TEST_VAR:-default_path/x.gguf}
"""
        cfg = load_config(_write(tmp_path, yaml_text))
        assert cfg.models["m1"].path == "/custom/path/x.gguf"

    def test_env_var_required_without_default_raises(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("EMOPARSE_REQUIRED_VAR", raising=False)
        yaml_text = """
models:
  m1:
    backend: llama_cpp
    path: ${EMOPARSE_REQUIRED_VAR}
"""
        with pytest.raises(ConfigError, match="EMOPARSE_REQUIRED_VAR"):
            load_config(_write(tmp_path, yaml_text))

    def test_env_var_in_paths(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Funciona en cualquier campo, no solo paths de modelos."""
        monkeypatch.setenv("EMOPARSE_RUNS", "/var/runs")
        yaml_text = """
models:
  m1:
    backend: llama_cpp
    path: x.gguf
paths:
  runs_dir: ${EMOPARSE_RUNS:-runs/}
"""
        cfg = load_config(_write(tmp_path, yaml_text))
        assert cfg.paths.runs_dir == "/var/runs"
