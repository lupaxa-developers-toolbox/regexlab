"""Version tests check semantic shape only."""

from __future__ import annotations

from lupaxa.regexlab.cli import main
from lupaxa.regexlab.version import __version__, get_version


def test_version_shape() -> None:
    assert isinstance(__version__, str)
    parts = __version__.split(".")
    assert len(parts) >= 2
    assert parts[0].isdigit()
    assert parts[1].isdigit()
    assert get_version() == __version__


def test_version_command(capsys: object) -> None:
    assert main(["version"]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert out.startswith("regex-lab ")
    printed = out.split()[-1].strip()
    parts = printed.split(".")
    assert parts[0].isdigit()
    assert parts[1].isdigit()


def test_version_flag(capsys: object) -> None:
    assert main(["--version"]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert out.startswith("regex-lab ")
    assert get_version() in out
