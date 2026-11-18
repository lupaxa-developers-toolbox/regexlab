"""Parser coverage: structure, quantifiers, groups, and invalid patterns."""

from __future__ import annotations

import pytest

from lupaxa.regexlab.errors import PatternProblem
from lupaxa.regexlab.parser import parse_pattern, render_tree

EXAMPLE = r"^(?P<name>[a-z]+)-(?P<id>\d+)$"
TREE = """\
Expression
├── Start anchor
├── Named group: name
│   └── Character class: a-z
│       └── Repeat: one or more
├── Literal: -
├── Named group: id
│   └── Digit
│       └── Repeat: one or more
└── End anchor
"""


def test_named_example_tree() -> None:
    assert render_tree(parse_pattern(EXAMPLE)) == TREE.rstrip("\n")


def test_literals_and_class() -> None:
    node = parse_pattern(r"ab[a-z]")
    kinds = [child.type for child in node.children]
    assert "literal" in kinds
    assert "character_class" in kinds
    klass = next(child for child in node.children if child.type == "character_class")
    assert any(part.get("kind") == "range" for part in klass.parts)


def test_quantifiers() -> None:
    greedy = parse_pattern(r"a+")
    lazy = parse_pattern(r"a+?")
    possessive = parse_pattern(r"a++")
    assert greedy.children[0].quantifier is not None
    assert greedy.children[0].quantifier.lazy is False
    assert lazy.children[0].quantifier is not None
    assert lazy.children[0].quantifier.lazy is True
    assert possessive.children[0].quantifier is not None
    assert possessive.children[0].quantifier.possessive is True


def test_groups_and_alternation() -> None:
    node = parse_pattern(r"(a)|(?:b)")
    assert node.children[0].type == "alternation"
    arms = node.children[0].children
    assert arms[0].kind == "capturing"
    assert arms[1].kind == "non_capturing"


def test_lookaround_and_backref() -> None:
    node = parse_pattern(r"(a)(?=b)(?<=a)\1")
    types = [child.type for child in node.children]
    assert "group" in types
    assert "lookahead" in types
    assert "lookbehind" in types
    assert "backref" in types


def test_invalid_reports_position() -> None:
    with pytest.raises(PatternProblem) as caught:
        parse_pattern("(")
    problem = caught.value
    assert problem.position is not None
    assert problem.fragment
    assert problem.explanation
    assert problem.exit_code == 3


def test_nothing_to_repeat() -> None:
    with pytest.raises(PatternProblem) as caught:
        parse_pattern("*")
    assert caught.value.position == 0
