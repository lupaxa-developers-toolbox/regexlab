"""CLI contracts: help, JSON, colour, engines, and input guards."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from lupaxa.regexlab.cli import COMMANDS, main


def test_help_for_every_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    err = capsys.readouterr().err
    assert "usage:" in err.casefold()
    for name in COMMANDS:
        assert main([name, "--help"]) == 0
        assert name in capsys.readouterr().out
    for name in ("create", "validate", "run", "list", "show"):
        assert main(["suite", name, "--help"]) == 0
        capsys.readouterr()
    for name in ("add", "list", "show", "search", "remove", "export"):
        assert main(["library", name, "--help"]) == 0
        capsys.readouterr()


def test_json_envelope(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain", r"a+", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "1.0"
    assert payload["ok"] is True
    assert payload["command"] == "explain"
    assert payload["engine"] == "python-re"
    assert payload["pattern"] == "a+"
    assert payload["flags"] == ""
    assert payload["mode"] == "fullmatch"
    assert payload["error"] is None
    assert "\x1b" not in json.dumps(payload)
    assert main(["parse", "(", "--json"]) == 3
    failed = json.loads(capsys.readouterr().out)
    assert failed["ok"] is False
    assert failed["error"]["position"] == 0
    assert isinstance(failed["error"]["position"], int)


def test_no_color(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("NO_COLOR", "")
    assert main(["matches", "ab", "ab"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "«ab»" in out


def test_no_colour_flag(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["matches", "ab", "ab", "--no-colour"]) == 0
    assert "\x1b" not in capsys.readouterr().out


def test_engines(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["engines"]) == 0
    out = capsys.readouterr().out
    assert "Available regex engines:" in out
    assert "python-re" in out
    assert "Available (default)" in out
    assert "Not installed" in out
    missing_regex = importlib.util.find_spec("regex") is None
    code = main(["explain", "a", "--engine", "python-regex"])
    err = capsys.readouterr().err
    if missing_regex:
        assert code == 7
        assert "not installed" in err.casefold()
        assert "substitute" in err.casefold()
    else:
        assert code == 0


def test_binary_and_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    binary = tmp_path / "bin.dat"
    binary.write_bytes(b"a\x00b")
    assert main(["test", "a", "--input", str(binary)]) == 1
    assert "binary" in capsys.readouterr().err.casefold()
    folder = tmp_path / "dir"
    folder.mkdir()
    assert main(["findall", "a", "--input", str(folder)]) == 2


def test_config_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    user = tmp_path / "user.toml"
    user.write_text('engine = "python-re"\nflags = "i"\n', encoding="utf-8")
    chosen = tmp_path / "chosen.toml"
    chosen.write_text('flags = "m"\nunknown = true\n', encoding="utf-8")
    monkeypatch.setenv("REGEXLAB_CONFIG", str(user))
    assert main(["config", "--config", str(chosen)]) == 0
    out = capsys.readouterr().out
    assert "flags: m" in out
    assert main(["config", "--config", str(chosen), "--flags", "s", "--strict"]) == 2


def test_flags_and_benchmark(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["flags"]) == 0
    flags_out = capsys.readouterr().out
    assert "IGNORECASE" in flags_out or "ignorecase" in flags_out.casefold()
    assert main(["benchmark", "a+", "aaa", "--iterations", "3", "--timeout", "1"]) == 0
    out = capsys.readouterr().out
    assert "avg" in out.casefold()


def test_findall_line_and_recursive(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "keep.txt").write_text("a\nb\n", encoding="utf-8")
    (tmp_path / "skip.log").write_text("b\n", encoding="utf-8")
    assert (
        main(
            [
                "findall",
                "b",
                "--input",
                str(tmp_path),
                "--recursive",
                "--include",
                "*.txt",
                "--context",
                "0",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "line: 2" in out
    assert "skip.log" not in out


def test_interactive_guard(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert main(["interactive"]) == 2
    assert "TTY" in capsys.readouterr().err
