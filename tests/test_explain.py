"""Explanations come from the syntax tree."""

from __future__ import annotations

from lupaxa.regexlab.explain import explain_text
from lupaxa.regexlab.flagset import parse_flags
from lupaxa.regexlab.parser import parse_pattern

EXAMPLE = r"^(?P<name>[a-z]+)-(?P<id>\d+)$"


def test_example_mentions_each_part() -> None:
    flags = parse_flags("")
    node = parse_pattern(EXAMPLE, flags=flags)
    text = explain_text(node, engine="python-re", detail="detailed", flags="")
    lowered = text.casefold()
    assert "start of the string" in lowered
    assert 'capture "name"' in lowered
    assert "lowercase letters" in lowered
    assert "hyphen" in lowered
    assert 'capture "id"' in lowered
    assert "end of the string" in lowered


def test_ascii_flag_changes_digit_words() -> None:
    flags = parse_flags("a")
    text = explain_text(
        parse_pattern(r"\d", flags=flags),
        engine="python-re",
        detail="detailed",
        flags=flags.letters(),
    )
    assert "ASCII digit" in text


def test_unicode_digit_and_multiline_anchor() -> None:
    plain = explain_text(parse_pattern(r"\d"), engine="python-re", detail="summary", flags="")
    assert "decimal digits" in plain.casefold()
    flags = parse_flags("m")
    anchored = explain_text(
        parse_pattern("^", flags=flags),
        engine="python-re",
        detail="detailed",
        flags="m",
    )
    assert "Start of a line" in anchored


def test_ignorecase_sentence() -> None:
    flags = parse_flags("i")
    text = explain_text(
        parse_pattern("a", flags=flags),
        engine="python-re",
        detail="technical",
        flags="i",
    )
    assert "case-insensitive" in text
    assert "engine: python-re" in text
