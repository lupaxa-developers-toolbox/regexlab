"""Matching, generation, comparison, and analysis."""

from __future__ import annotations

import time

from lupaxa.regexlab.analyse import analyse_pattern, lint_pattern
from lupaxa.regexlab.cli import main
from lupaxa.regexlab.compare import render_compare
from lupaxa.regexlab.engines import compile_pattern, iter_matches
from lupaxa.regexlab.flagset import parse_flags
from lupaxa.regexlab.generate import generate_samples
from lupaxa.regexlab.isolate import run


def test_modes_and_zero_width() -> None:
    flags = parse_flags("")
    compiled = compile_pattern("python-re", r"a*", flags)
    matches, truncated = iter_matches(compiled, "b", "finditer", max_matches=10)
    assert truncated is False
    assert matches
    assert all(item.end >= item.start for item in matches)
    assert any(item.start == item.end for item in matches)
    full, _ = iter_matches(compiled, "aa", "fullmatch", max_matches=5)
    assert full and full[0].text == "aa"
    head, _ = iter_matches(compile_pattern("python-re", "a", flags), "ba", "match", max_matches=5)
    assert head == []
    found, _ = iter_matches(compile_pattern("python-re", "a", flags), "ba", "search", max_matches=5)
    assert found and found[0].start == 1


def test_generation_is_verified_and_seeded() -> None:
    flags = parse_flags("")
    first = generate_samples(
        r"[ab]{2}",
        engine="python-re",
        flags=flags,
        mode="fullmatch",
        count=4,
        seed=7,
        min_length=2,
        max_length=2,
        unique=True,
        include_invalid=True,
    )
    second = generate_samples(
        r"[ab]{2}",
        engine="python-re",
        flags=flags,
        mode="fullmatch",
        count=4,
        seed=7,
        min_length=2,
        max_length=2,
        unique=True,
        include_invalid=True,
    )
    assert first.positives == second.positives
    assert first.positives
    compiled = compile_pattern("python-re", r"[ab]{2}", flags)
    for sample in first.positives:
        matches, _ = iter_matches(compiled, sample, "fullmatch", max_matches=1)
        assert matches
    assert first.negatives
    for negative in first.negatives:
        assert negative.category
        matches, _ = iter_matches(compiled, negative.text, "fullmatch", max_matches=1)
        assert not matches


def test_generation_reports_backreference(capsys: object) -> None:
    code = main(["generate", r"(a)\1", "--count", "2"])
    err = capsys.readouterr().err  # type: ignore[attr-defined]
    assert code == 7
    assert "backreference" in err.casefold()


def test_compare_categories(capsys: object) -> None:
    code = main(["compare", "a+", "b+", "aaa", "bbb", "--fail-on-difference"])
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert code == 9
    assert "only first" in out.casefold() or "only_first" in out
    assert "does not prove" in out
    assert "Sample comparison only" in out
    rendered = render_compare  # imported so a missing renderer fails collection
    assert rendered is not None


def test_analyse_and_lint(capsys: object) -> None:
    findings = analyse_pattern(r"(a+)+", engine="python-re", flags=parse_flags(""))
    assert any(item.id == "nested-quantifier" and item.heuristic for item in findings)
    assert main(["lint", r"^abc$"]) == 0
    dotted = lint_pattern(r".*.*foo", engine="python-re", flags=parse_flags(""))
    assert any(item.id == "redundant-repetition" for item in dotted)
    assert main(["lint", r"a{1}", "--strict"]) == 10
    err = capsys.readouterr()  # type: ignore[attr-defined]
    assert "redundant-repetition" in err.out
    escaped = lint_pattern(r"\,", engine="python-re", flags=parse_flags(""))
    assert any(item.id == "unnecessary-escape" for item in escaped)


def test_redos_worker_terminates() -> None:
    started = time.monotonic()
    message = run(
        "match",
        {
            "engine": "python-re",
            "pattern": r"(a+)+$",
            "flags": "",
            "mode": "search",
            "timeout": 0.25,
            "max_matches": 10,
            "subjects": [("t", "a" * 30 + "!")],
        },
        timeout=2.0,
        method="fork",
    )
    elapsed = time.monotonic() - started
    assert elapsed < 5
    assert message["exit_code"] == 5
