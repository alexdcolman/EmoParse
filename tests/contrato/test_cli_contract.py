"""Contratos públicos del parser y del entry point del CLI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

import emoparse.cli.__main__ as cli_main
from emoparse.cli.commands import COMMANDS
from emoparse.cli.commands.run_cmd import (
    _parse_stages,
    _resolve_db_path,
    _resolver_db_existente,
)
from emoparse.pipeline import STAGE_ORDER


def _subcommands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(item for item in parser._actions if isinstance(item, argparse._SubParsersAction))
    return dict(action.choices)


def test_parser_registers_every_command_module_once() -> None:
    parser = cli_main.build_parser()
    registered = tuple(_subcommands(parser))
    expected = tuple(module.__name__.rsplit(".", 1)[-1].removesuffix("_cmd") for module in COMMANDS)

    assert registered == expected
    assert len(registered) == len(set(registered))


def test_each_subcommand_has_callable_handler() -> None:
    for parser in _subcommands(cli_main.build_parser()).values():
        assert callable(parser.get_default("handler"))


def test_help_exits_zero() -> None:
    with pytest.raises(SystemExit) as error:
        cli_main.main(["--help"])

    assert error.value.code == 0


def test_missing_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as error:
        cli_main.main([])

    assert error.value.code != 0


def test_unknown_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as error:
        cli_main.main(["inexistente"])

    assert error.value.code != 0


def test_main_maps_keyboard_interrupt_to_sigint_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        verbose=False,
        quiet=False,
        log_dir=None,
        no_log_file=True,
        command="fake",
        handler=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(cli_main, "build_parser", lambda: _ParserStub(args))
    monkeypatch.setattr(cli_main.logging_setup, "configure", lambda **_: None)

    assert cli_main.main([]) == 130


def test_main_maps_unexpected_error_to_code_2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = argparse.Namespace(
        verbose=False,
        quiet=False,
        log_dir=None,
        no_log_file=True,
        command="fake",
        handler=lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(cli_main, "build_parser", lambda: _ParserStub(args))
    monkeypatch.setattr(cli_main.logging_setup, "configure", lambda **_: None)

    assert cli_main.main([]) == 2


class _ParserStub:
    def __init__(self, args: argparse.Namespace) -> None:
        self._args = args

    def parse_args(self, _: list[str] | None) -> argparse.Namespace:
        return self._args


def test_parse_stages_accepts_canonical_order_without_copying_it() -> None:
    raw = ",".join(STAGE_ORDER)

    assert _parse_stages(raw) == STAGE_ORDER


def test_parse_stages_strips_whitespace_and_preserves_requested_order() -> None:
    selected = (STAGE_ORDER[-1], STAGE_ORDER[0])

    assert _parse_stages(f" {selected[0]} , {selected[1]} ") == selected


def test_parse_stages_rejects_empty_value() -> None:
    with pytest.raises(ValueError, match="vacío"):
        _parse_stages(" , ")


def test_parse_stages_rejects_unknown_value() -> None:
    with pytest.raises(ValueError, match="desconocidas"):
        _parse_stages("stage_inexistente")


def test_resolve_db_path_honors_explicit_path(tmp_path: Path) -> None:
    explicit = tmp_path / "custom.sqlite"

    assert _resolve_db_path(str(explicit), "ignored", "ignored") == explicit.resolve()


def test_resolve_db_path_builds_default_from_run_id(tmp_path: Path) -> None:
    runs = tmp_path / "runs"

    assert _resolve_db_path(None, str(runs), "run_a") == (runs / "run_a.sqlite").resolve()


def test_existing_db_requires_explicit_decision_without_tty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "existing.sqlite"
    db_path.touch()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    args = argparse.Namespace(overwrite_db=False, resume=False)

    assert _resolver_db_existente(db_path, args) == "cancelar"


@pytest.mark.parametrize(
    ("overwrite", "resume", "expected"),
    [(True, False, "sobrescribir"), (False, True, "reanudar")],
)
def test_existing_db_honors_explicit_flags(
    tmp_path: Path,
    overwrite: bool,
    resume: bool,
    expected: str,
) -> None:
    db_path = tmp_path / "existing.sqlite"
    db_path.touch()
    args = argparse.Namespace(overwrite_db=overwrite, resume=resume)

    assert _resolver_db_existente(db_path, args) == expected
