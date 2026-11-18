"""Suite, library, export, and visual output."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from lupaxa.regexlab.cli import main
from lupaxa.regexlab.export import export_suite
from lupaxa.regexlab.parser import parse_pattern
from lupaxa.regexlab.suite import load_suite
from lupaxa.regexlab.visualise import visualise

SUITE = """\
schema_version = "1.0"
name = "ids"
engine = "python-re"
pattern = '^(?P<name>[a-z]+)-(?P<id>\\d+)$'
mode = "fullmatch"
flags = ""

[[tests]]
name = "hit"
input = "ab-12"
should_match = true
span = [0, 5]
groups = ["ab", "12"]

[tests.groupdict]
name = "ab"
id = "12"

[[tests]]
name = "miss"
input = "AB"
should_match = false

[[tests]]
name = "swap"
input = "ab-12"
replacement = '\\g<id>'
expected_replacement = "12"

[[tests]]
name = "parts"
input = "a-b"
pattern = "-"
mode = "split"
expected_split = ["a", "b"]
"""


def test_suite_run_and_pytest_export(tmp_path: Path, capsys: object) -> None:
    path = tmp_path / "suite.toml"
    path.write_text(SUITE, encoding="utf-8")
    assert main(["suite", "validate", str(path)]) == 0
    assert main(["suite", "run", str(path)]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "passed: 4" in out
    exported = tmp_path / "test_generated.py"
    assert main(["export", str(path), "--format", "pytest", "--output", str(exported)]) == 0
    source = exported.read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    assert "test_generated" in names
    assert "exec(" not in source
    assert "parametrize" in source
    suite = load_suite(path)
    assert "ab-12" in export_suite(suite, "json", None, force=False)
    text = export_suite(suite, "text", None, force=False)
    assert "hit" in text


def test_suite_failure_exit(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text(
        "\n".join(
            [
                'schema_version = "1.0"',
                'name = "bad"',
                'pattern = "a"',
                'mode = "fullmatch"',
                "",
                "[[tests]]",
                'name = "no"',
                'input = "b"',
                "should_match = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    assert main(["suite", "run", str(path)]) == 4


def test_library_round_trip(tmp_path: Path, monkeypatch: object, capsys: object) -> None:
    monkeypatch.setenv("REGEXLAB_DATA", str(tmp_path))  # type: ignore[attr-defined]
    assert main(["library", "add", "digits", r"\d+", "--description", "digits"]) == 0
    assert main(["library", "add", "digits", r"\d+"]) == 2
    assert main(["library", "list"]) == 0
    listed = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "digits" in listed
    assert main(["library", "search", "DIG"]) == 0
    assert "digits" in capsys.readouterr().out  # type: ignore[attr-defined]
    assert main(["library", "show", "digits"]) == 0
    dest = tmp_path / "out.toml"
    assert main(["library", "export", "--output", str(dest)]) == 0
    assert "digits" in dest.read_text(encoding="utf-8")
    assert main(["library", "remove", "digits"]) == 0
    assert main(["library", "show", "digits"]) == 2


def test_html_and_svg_escape() -> None:
    pattern = r"(?P<name><script>)"
    node = parse_pattern(pattern)
    html = visualise(node, pattern, "html")
    svg = visualise(node, pattern, "svg")
    assert "<script>" not in html
    assert "<name>" not in html
    assert "&lt;" in html
    assert "<script>" not in svg
    assert "http://" not in html
    mermaid = visualise(node, pattern, "mermaid")
    assert "<script>" not in mermaid


def test_escape_replace_split(tmp_path: Path, capsys: object) -> None:
    assert main(["escape", "a.b"]) == 0
    assert capsys.readouterr().out.strip() == r"a\.b"  # type: ignore[attr-defined]
    assert main(["replace", r"(\w+)", r"\1!", "ab"]) == 0
    assert capsys.readouterr().out.strip().endswith("ab!")  # type: ignore[attr-defined]
    assert main(["replace", r"(\w+)", "$1", "ab"]) == 7
    source = tmp_path / "in.txt"
    source.write_text("ab", encoding="utf-8")
    assert main(["replace", r"a", "A", "--input", str(source), "--in-place"]) == 2
    assert source.read_text(encoding="utf-8") == "ab"
    assert main(["replace", r"a", "A", "--input", str(source), "--in-place", "--yes"]) == 0
    assert source.read_text(encoding="utf-8") == "Ab"
    preview = tmp_path / "keep.txt"
    preview.write_text("ab", encoding="utf-8")
    assert main(["replace", r"a", "Z", "--input", str(preview)]) == 0
    assert preview.read_text(encoding="utf-8") == "ab"
    assert main(["split", "-", "a-b-c", "--count", "1"]) == 0
    split_out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "segment 0: a" in split_out
    assert "separator 0: -" in split_out
    payload = json.loads("null")
    assert payload is None
