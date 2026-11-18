"""Structured recursive-descent parser for regular expressions.

Parsing does not compile or execute the pattern. The tree is the input to
explanations, lint, generation, and visualisation.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal, NoReturn, overload

from lupaxa.regexlab.engines import require_engine
from lupaxa.regexlab.errors import EXIT_INVALID, EXIT_UNSUPPORTED, PatternProblem
from lupaxa.regexlab.flagset import FlagSet

_HEX = frozenset("0123456789abcdefABCDEF")
_OCT = frozenset("01234567")
_DIGITS = frozenset("0123456789")
_WHITESPACE = frozenset(" \t\n\r\v\f")
_CHAR_ESCAPES = {
    "a": "\a",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
}
_CHAR_KINDS = {
    "\a": "bell",
    "\f": "formfeed",
    "\n": "newline",
    "\r": "return",
    "\t": "tab",
    "\v": "vtab",
}
_CATEGORIES = {
    "d": "digit",
    "D": "nondigit",
    "s": "space",
    "S": "nonspace",
    "w": "word",
    "W": "nonword",
}


@dataclass(frozen=True)
class Features:
    possessive: bool = True
    atomic: bool = True
    recursion: bool = False
    properties: bool = False
    pattern_g: bool = False
    variable_lookbehind: bool = False


_FEATURES = {
    "python-re": Features(),
    "python-regex": Features(
        recursion=True,
        properties=True,
        pattern_g=True,
        variable_lookbehind=True,
    ),
    "pcre2": Features(
        recursion=True,
        properties=True,
        pattern_g=True,
        variable_lookbehind=True,
    ),
}


@dataclass
class Quantifier:
    min: int
    max: int | None
    lazy: bool
    possessive: bool
    fragment: str
    start: int
    end: int

    def label(self) -> str:
        if self.min == 0 and self.max is None:
            base = "zero or more"
        elif self.min == 1 and self.max is None:
            base = "one or more"
        elif self.min == 0 and self.max == 1:
            base = "optional"
        elif self.max is None:
            base = f"{self.min} or more"
        elif self.min == self.max:
            base = f"exactly {self.min}"
        else:
            base = f"{self.min} to {self.max}"
        if self.possessive:
            base += ", possessive"
        elif self.lazy:
            base += ", lazy"
        return f"Repeat: {base}"


@dataclass
class Node:
    type: str
    fragment: str
    start: int
    end: int
    children: list[Node] = field(default_factory=list)
    quantifier: Quantifier | None = None
    name: str | None = None
    number: int | None = None
    text: str | None = None
    negate: bool = False
    kind: str | None = None
    parts: list[dict[str, Any]] = field(default_factory=list)
    ignorecase: bool = False
    multiline: bool = False
    dotall: bool = False
    ascii: bool = False

    def to_dict(self) -> dict[str, Any]:
        quant = None
        if self.quantifier is not None:
            quant = {
                "min": self.quantifier.min,
                "max": self.quantifier.max,
                "lazy": self.quantifier.lazy,
                "possessive": self.quantifier.possessive,
                "start": self.quantifier.start,
                "end": self.quantifier.end,
            }
        return {
            "type": self.type,
            "fragment": self.fragment,
            "start": self.start,
            "end": self.end,
            "quantifier": quant,
            "name": self.name,
            "number": self.number,
            "text": self.text,
            "negate": self.negate,
            "kind": self.kind,
            "parts": self.parts or None,
            "children": [child.to_dict() for child in self.children],
        }


def parse_pattern(pattern: str, engine: str = "python-re", flags: FlagSet | None = None) -> Node:
    """Parse ``pattern`` for ``engine`` without executing it."""

    require_engine(engine)
    if engine not in _FEATURES:
        from lupaxa.regexlab.errors import UsageError

        raise UsageError(f"unknown engine {engine}")
    return Parser(pattern, engine, flags or FlagSet()).parse()


def render_tree(node: Node) -> str:
    """Box-drawing tree. Quantifiers are shown as children of the atom."""

    lines: list[str] = []

    def walk(current: Node, prefix: str, last: bool, root: bool) -> None:
        label = node_label(current)
        if root:
            lines.append(label)
            child_prefix = ""
        else:
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + label)
            child_prefix = prefix + ("    " if last else "│   ")
        kids = _display_children(current)
        for index, child in enumerate(kids):
            walk(child, child_prefix, index == len(kids) - 1, False)

    walk(node, "", True, True)
    return "\n".join(lines)


def node_label(node: Node) -> str:
    if node.type == "expression":
        return "Expression"
    if node.type == "anchor":
        return _anchor_label(node)
    if node.type == "group":
        if node.kind == "named":
            return f"Named group: {node.name}"
        if node.kind == "non_capturing":
            return "Non-capturing group"
        return "Capturing group"
    if node.type == "character_class":
        body = _class_body(node)
        if node.negate:
            return f"Character class: not {body}"
        return f"Character class: {body}"
    if node.type == "literal":
        return f"Literal: {visible(node.text or '')}"
    if node.type == "category":
        return _category_label(node)
    if node.type == "any":
        if node.dotall:
            return "Any character, including newline"
        return "Any character"
    if node.type == "repeat":
        return node.kind or "Repeat"
    if node.type == "char":
        names = {
            "newline": "Newline",
            "tab": "Tab",
            "return": "Carriage return",
            "formfeed": "Form feed",
            "vtab": "Vertical tab",
            "bell": "Bell",
        }
        return names.get(node.kind or "", f"Literal: {visible(node.text or '')}")
    if node.type == "backref":
        target = node.name if node.name else str(node.number)
        return f"Backreference: {target}"
    if node.type == "lookahead":
        return "Negative lookahead" if node.negate else "Lookahead"
    if node.type == "lookbehind":
        return "Negative lookbehind" if node.negate else "Lookbehind"
    if node.type == "alternation":
        return "Alternation"
    if node.type == "atomic":
        return "Atomic group"
    if node.type == "conditional":
        target = node.name if node.name else str(node.number)
        return f"Conditional group: {target}"
    if node.type == "inline_flags":
        return f"Inline flags: {node.text or node.kind or ''}"
    if node.type == "comment":
        return "Comment"
    if node.type == "recursion":
        return "Recursion"
    if node.type == "property":
        return f"Unicode property: {node.text or ''}"
    if node.type == "empty":
        return "Empty"
    if node.type == "sequence":
        return "Sequence"
    return node.type.replace("_", " ").capitalize()


def fixed_width(node: Node) -> int | None:
    """Return the fixed consume width, or None when it can vary."""

    base = _base_width(node)
    quant = node.quantifier
    if quant is None:
        return base
    if base is None or quant.max is None or quant.min != quant.max:
        return None
    return base * quant.min


def body_width(node: Node) -> int | None:
    return _sum_width(node.children)


def visible(text: str) -> str:
    parts: list[str] = []
    for char in text:
        if char == "\n":
            parts.append("\\n")
        elif char == "\t":
            parts.append("\\t")
        elif char == "\r":
            parts.append("\\r")
        elif char.isprintable():
            parts.append(char)
        else:
            parts.append(char.encode("unicode_escape").decode("ascii"))
    return "".join(parts)


class Parser:
    def __init__(self, pattern: str, engine: str, flags: FlagSet) -> None:
        self.s = pattern
        self.n = len(pattern)
        self.i = 0
        self.engine = engine
        self.flags = flags
        self.features = _FEATURES[engine]
        self.group_count = 0
        self.open_groups: list[int] = []
        self.closed: set[int] = set()
        self.names: dict[str, int] = {}
        self.last_quantified = False
        self.past_start = False
        self.global_ascii = flags.ascii
        self.global_unicode = flags.unicode_explicit

    def parse(self) -> Node:
        self.skip_ws()
        node = self.parse_alt()
        self.skip_ws()
        if self.i < self.n:
            if self.peek() == ")":
                self.fail("unbalanced", self.i, "Unbalanced ')'. There is no open group here.")
            self.fail("trailing", self.i, "Unexpected text after the expression.")
        children = self._top_children(node)
        return self.make(
            "expression",
            0,
            end=self.n,
            fragment=self.s,
            children=children,
        )

    def parse_alt(self) -> Node:
        start = self.i
        branches = [self.parse_sequence()]
        while self.peek() == "|":
            self.i += 1
            branches.append(self.parse_sequence())
        if len(branches) == 1:
            return branches[0]
        return self.make(
            "alternation",
            start,
            end=self.i,
            fragment=self.s[start : self.i],
            children=branches,
        )

    def parse_sequence(self) -> Node:
        self.last_quantified = False
        start = self.i
        items: list[Node] = []
        while self.i < self.n:
            self.skip_ws()
            if self.i >= self.n or self.peek() in ")|":
                break
            before = self.i
            items.append(self.parse_quantified())
            if self.i == before:
                self.fail("internal", self.i, "The parser did not consume input.")
        items = self.coalesce(items)
        if not items:
            return self.make("empty", start, end=self.i, fragment="")
        if len(items) == 1:
            return items[0]
        return self.make(
            "sequence",
            start,
            end=items[-1].end,
            fragment=self.s[start : items[-1].end],
            children=items,
        )

    def parse_quantified(self) -> Node:
        self.skip_ws()
        node = self.parse_atom()
        self.skip_ws()
        quant = self.try_quantifier()
        if quant is not None:
            node.quantifier = quant
            node.end = quant.end
            node.fragment = self.s[node.start : quant.end]
            self.last_quantified = True
        else:
            self.last_quantified = False
        if node.type not in {"comment"} and not (node.type == "inline_flags" and not node.children):
            self.past_start = True
        return node

    def parse_atom(self) -> Node:
        self.skip_ws()
        if self.i >= self.n:
            self.fail(
                "unexpected_end",
                self.n,
                "The pattern ended where an expression was required.",
            )
        if self.looks_like_quantifier(self.i):
            if self.last_quantified:
                self.fail(
                    "multiple_repeat",
                    self.i,
                    "A quantifier cannot repeat another quantifier.",
                )
            self.fail("nothing_to_repeat", self.i, "A quantifier needs an expression before it.")
        char = self.peek()
        if char == "(":
            return self.parse_group()
        if char == "[":
            return self.parse_class()
        if char == ".":
            start = self.i
            self.i += 1
            return self.make("any", start, kind="any")
        if char == "^":
            start = self.i
            self.i += 1
            return self.make("anchor", start, kind="start")
        if char == "$":
            start = self.i
            self.i += 1
            return self.make("anchor", start, kind="end")
        if char == "\\":
            result = self.parse_escape(in_class=False)
            if isinstance(result, dict):
                self.fail("bad_escape", self.i, "Invalid escape.")
            return result
        if char in ")|":
            self.fail("empty", self.i, "Expected an expression.")
        start = self.i
        self.i += 1
        return self.make("literal", start, text=char)

    def try_quantifier(self) -> Quantifier | None:
        if self.i >= self.n or not self.looks_like_quantifier(self.i):
            return None
        start = self.i
        char = self.peek()
        if char == "*":
            self.i += 1
            low, high = 0, None
        elif char == "+":
            self.i += 1
            low, high = 1, None
        elif char == "?":
            self.i += 1
            low, high = 0, 1
        else:
            low, high = self.read_brace()
        lazy = False
        possessive = False
        if self.peek() == "?":
            lazy = True
            self.i += 1
        elif self.peek() == "+":
            possessive = True
            self.i += 1
            if not self.features.possessive:
                self.fail(
                    "unsupported",
                    start,
                    f"Possessive quantifiers are not supported by {self.engine}.",
                    exit_code=EXIT_UNSUPPORTED,
                )
        return Quantifier(low, high, lazy, possessive, self.s[start : self.i], start, self.i)

    def read_brace(self) -> tuple[int, int | None]:
        brace = self.i
        self.i += 1
        low_at = self.i
        while self.peek().isdigit():
            self.i += 1
        low = int(self.s[low_at : self.i])
        high: int | None = low
        if self.peek() == ",":
            self.i += 1
            if self.peek().isdigit():
                high_at = self.i
                while self.peek().isdigit():
                    self.i += 1
                high = int(self.s[high_at : self.i])
            else:
                high = None
        if self.peek() != "}":
            self.fail("bad_quantifier", brace, "Unclosed quantifier.")
        self.i += 1
        if high is not None and low > high:
            self.fail(
                "bad_quantifier",
                brace,
                "The minimum repeat is greater than the maximum.",
            )
        return low, high

    def looks_like_quantifier(self, index: int) -> bool:
        if index >= self.n:
            return False
        char = self.s[index]
        if char in "*+?":
            return True
        if char != "{":
            return False
        cursor = index + 1
        if cursor >= self.n or not self.s[cursor].isdigit():
            return False
        while cursor < self.n and self.s[cursor].isdigit():
            cursor += 1
        if cursor < self.n and self.s[cursor] == ",":
            cursor += 1
            while cursor < self.n and self.s[cursor].isdigit():
                cursor += 1
        return cursor < self.n and self.s[cursor] == "}"

    def parse_group(self) -> Node:
        start = self.i
        self.i += 1
        if self.peek() != "?":
            number = self.open_capture(None, start)
            inner = self.parse_alt()
            self.expect_close(start)
            self.close_capture(number)
            return self.make(
                "group",
                start,
                kind="capturing",
                number=number,
                children=self.children_of(inner),
            )
        self.i += 1
        char = self.peek()
        if char == ":":
            self.i += 1
            inner = self.parse_alt()
            self.expect_close(start)
            return self.make(
                "group",
                start,
                kind="non_capturing",
                children=self.children_of(inner),
            )
        if char == "P":
            return self.parse_p(start)
        if char == "#":
            return self.parse_comment(start)
        if char == "=":
            return self.parse_lookahead(start, False)
        if char == "!":
            return self.parse_lookahead(start, True)
        if char == "<":
            return self.parse_lookbehind(start)
        if char == ">":
            return self.parse_atomic(start)
        if char == "(":
            return self.parse_conditional(start)
        if char in "R0":
            return self.parse_recursion(start)
        return self.parse_inline_flags(start)

    def parse_p(self, start: int) -> Node:
        self.i += 1
        nxt = self.peek()
        if nxt == "<":
            self.i += 1
            name = self.read_name(start)
            if self.peek() != ">":
                self.fail("bad_name", start, "Named groups look like (?P<name>...).")
            self.i += 1
            if name in self.names:
                self.fail("redefinition", start, f"Group name {name!r} is already used.")
            number = self.open_capture(name, start)
            inner = self.parse_alt()
            self.expect_close(start)
            self.close_capture(number)
            return self.make(
                "group",
                start,
                kind="named",
                name=name,
                number=number,
                children=self.children_of(inner),
            )
        if nxt == "=":
            self.i += 1
            name = self.read_name(start)
            if self.peek() != ")":
                self.fail("bad_name", start, "A named backreference looks like (?P=name).")
            self.i += 1
            self._known_closed_name(name, start)
            return self.make(
                "backref",
                start,
                kind="name",
                name=name,
                number=self.names[name],
            )
        if nxt == ">":
            self.i += 1
            name = self.read_name(start)
            if self.peek() != ")":
                self.fail("unknown_extension", start, "A subroutine call looks like (?P>name).")
            self.i += 1
            if not self.features.recursion:
                self.fail(
                    "unsupported",
                    start,
                    f"Subroutine (?P>{name}) is not supported by {self.engine}.",
                    exit_code=EXIT_UNSUPPORTED,
                )
            return self.make("recursion", start, kind="subroutine", name=name)
        self.fail("unknown_extension", start, "Unknown (?P...) extension.")
        return self.make("empty", start)  # pragma: no cover

    def parse_comment(self, start: int) -> Node:
        self.i += 1
        while self.i < self.n and self.s[self.i] != ")":
            self.i += 1
        if self.peek() != ")":
            self.fail("unclosed_group", start, "Unclosed (?#...) comment.")
        self.i += 1
        return self.make("comment", start, text=self.s[start : self.i])

    def parse_lookahead(self, start: int, negate: bool) -> Node:
        self.i += 1
        inner = self.parse_alt()
        self.expect_close(start)
        return self.make(
            "lookahead",
            start,
            negate=negate,
            children=self.children_of(inner),
        )

    def parse_lookbehind(self, start: int) -> Node:
        self.i += 1
        if self.peek() == "=":
            negate = False
        elif self.peek() == "!":
            negate = True
        else:
            self.fail(
                "unknown_extension",
                start,
                "Unknown group extension. Lookbehind is (?<=...) or (?<!...).",
            )
        self.i += 1
        inner = self.parse_alt()
        self.expect_close(start)
        node = self.make(
            "lookbehind",
            start,
            negate=negate,
            children=self.children_of(inner),
        )
        if body_width(node) is None and not self.features.variable_lookbehind:
            self.fail(
                "variable_lookbehind",
                start,
                "This lookbehind is not fixed-width. "
                f"{self.engine} only allows fixed-width lookbehinds.",
            )
        return node

    def parse_atomic(self, start: int) -> Node:
        self.i += 1
        if not self.features.atomic:
            self.fail(
                "unsupported",
                start,
                f"Atomic groups are not supported by {self.engine}.",
                exit_code=EXIT_UNSUPPORTED,
            )
        inner = self.parse_alt()
        self.expect_close(start)
        return self.make("atomic", start, children=self.children_of(inner))

    def parse_recursion(self, start: int) -> Node:
        kind = self.peek()
        self.i += 1
        if self.peek() != ")":
            self.fail("unknown_extension", start, "Unknown group extension.")
        self.i += 1
        if not self.features.recursion:
            self.fail(
                "unsupported",
                start,
                f"Recursion (?{kind}) is not supported by {self.engine}.",
                exit_code=EXIT_UNSUPPORTED,
            )
        return self.make("recursion", start, kind=kind)

    def parse_conditional(self, start: int) -> Node:
        self.i += 1
        begin = self.i
        while self.i < self.n and self.s[self.i] != ")":
            self.i += 1
        if self.peek() != ")":
            self.fail("unclosed_group", start, "Unclosed conditional group.")
        ref = self.s[begin : self.i]
        self.i += 1
        number, ref_name = self._condition_ref(ref, start)
        yes = self.parse_sequence()
        no: Node | None = None
        if self.peek() == "|":
            self.i += 1
            no = self.parse_sequence()
            if self.peek() == "|":
                self.fail(
                    "bad_conditional",
                    self.i,
                    "A conditional group allows only one '|' separator.",
                )
        self.expect_close(start)
        children = [yes]
        if no is not None:
            children.append(no)
        return self.make(
            "conditional",
            start,
            number=number,
            name=ref_name,
            children=children,
        )

    def parse_inline_flags(self, start: int) -> Node:
        on: list[str] = []
        off: list[str] = []
        bucket = on
        while self.i < self.n and self.s[self.i] in "iLmsxau-":
            char = self.s[self.i]
            self.i += 1
            if char == "-":
                bucket = off
                continue
            bucket.append(char)
        if not on and not off:
            self.fail("unknown_extension", start, "Unknown group extension.")
        on_text = "".join(on)
        off_text = "".join(off)
        if self.peek() == ":":
            self.i += 1
            saved = self.flags
            self.past_start = True
            self.apply_flag_chars(on_text, off_text, start)
            inner = self.parse_alt()
            self.expect_close(start)
            self.flags = saved
            label = on_text if not off_text else f"{on_text}-{off_text}"
            return self.make(
                "inline_flags",
                start,
                kind=label,
                text=label,
                children=self.children_of(inner),
            )
        if self.peek() == ")":
            if off:
                self.fail(
                    "bad_flags",
                    start,
                    "Turning flags off requires a colon, as in (?-i:...).",
                )
            if self.past_start:
                self.fail(
                    "bad_flags",
                    start,
                    "Global flags are not at the start of the expression.",
                )
            if "a" in on_text and (self.global_unicode or "u" in on_text):
                self.fail("bad_flags", start, "ASCII and UNICODE flags are incompatible.")
            if "u" in on_text and (self.global_ascii or "a" in on_text):
                self.fail("bad_flags", start, "ASCII and UNICODE flags are incompatible.")
            if "a" in on_text:
                self.global_ascii = True
            if "u" in on_text:
                self.global_unicode = True
            self.i += 1
            self.apply_flag_chars(on_text, off_text, start)
            return self.make("inline_flags", start, kind=on_text, text=on_text)
        self.fail("unknown_extension", start, "Unknown group extension.")
        return self.make("empty", start)  # pragma: no cover

    def parse_class(self) -> Node:
        start = self.i
        self.i += 1
        negate = False
        if self.peek() == "^":
            negate = True
            self.i += 1
        parts: list[dict[str, Any]] = []
        first = True
        closed = False
        while self.i < self.n:
            if self.s[self.i] == "]" and not first:
                self.i += 1
                closed = True
                break
            first = False
            item = self.parse_class_item()
            if (
                self.i < self.n
                and self.s[self.i] == "-"
                and self.i + 1 < self.n
                and self.s[self.i + 1] != "]"
            ):
                dash = self.i
                self.i += 1
                end_item = self.parse_class_item()
                if item.get("kind") == "char" and end_item.get("kind") == "char":
                    left = str(item["value"])
                    right = str(end_item["value"])
                    if ord(left) > ord(right):
                        self.fail("bad_range", dash, f"Bad character range {left}-{right}.")
                    parts.append({"kind": "range", "start": left, "end": right})
                else:
                    self.fail("bad_range", dash, "Bad character range.")
            else:
                parts.append(item)
        if not closed:
            self.fail("unclosed_class", start, "Unclosed character class. Expected ']'.")
        return self.make("character_class", start, negate=negate, parts=parts)

    def parse_class_item(self) -> dict[str, Any]:
        if self.i >= self.n:
            self.fail("unclosed_class", self.n, "Unclosed character class.")
        if self.peek() == "\\":
            result = self.parse_escape(in_class=True)
            if not isinstance(result, dict):
                self.fail("bad_escape", self.i, "Invalid escape in a character class.")
            return result
        char = self.s[self.i]
        self.i += 1
        return {"kind": "char", "value": char, "start": self.i - 1, "end": self.i}

    def parse_escape(self, *, in_class: bool) -> Node | dict[str, Any]:
        start = self.i
        if self.i + 1 >= self.n:
            self.fail("bad_escape", self.i, "A trailing backslash is not an escape.")
        self.i += 1
        char = self.s[self.i]
        self.i += 1
        if not in_class:
            simple = self._outside_simple(char, start)
            if simple is not None:
                return simple
        else:
            simple_class = self._class_simple(char, start)
            if simple_class is not None:
                return simple_class
        if char == "x":
            return self._hex(start, 2, in_class)
        if char == "u":
            return self._hex(start, 4, in_class)
        if char == "U":
            return self._hex(start, 8, in_class)
        if char == "N":
            return self._named_unicode(start, in_class)
        if char in "pP":
            return self._property(start, char, in_class)
        if char == "g" and not in_class:
            return self._g_backref(start)
        if char in _DIGITS:
            return self._numeric(start, char, in_class)
        if char.isascii() and char.isalpha():
            self.fail("bad_escape", start, f"Unknown escape \\{char}.")
        return self._char_result(start, char, in_class)

    def _outside_simple(self, char: str, start: int) -> Node | None:
        if char in {"A", "Z", "b", "B"}:
            kind = {
                "A": "absolute_start",
                "Z": "absolute_end",
                "b": "boundary",
                "B": "non_boundary",
            }[char]
            return self.make("anchor", start, kind=kind)
        if char in _CATEGORIES:
            return self.make("category", start, kind=_CATEGORIES[char])
        if char in _CHAR_ESCAPES:
            return self._char_result(start, _CHAR_ESCAPES[char], False)
        return None

    def _class_simple(self, char: str, start: int) -> dict[str, Any] | None:
        if char == "b":
            return {"kind": "char", "value": "\b", "start": start, "end": self.i}
        if char in _CHAR_ESCAPES or char == "\\":
            value = "\\" if char == "\\" else _CHAR_ESCAPES[char]
            return {"kind": "char", "value": value, "start": start, "end": self.i}
        if char in _CATEGORIES:
            return {
                "kind": "category",
                "name": _CATEGORIES[char],
                "source": "\\" + char,
                "start": start,
                "end": self.i,
            }
        return None

    def _hex(self, start: int, count: int, in_class: bool) -> Node | dict[str, Any]:
        digits: list[str] = []
        for _ in range(count):
            if self.i >= self.n or self.s[self.i] not in _HEX:
                self.fail(
                    "bad_escape",
                    start,
                    f"Incomplete hex escape. Expected {count} hex digits.",
                )
            digits.append(self.s[self.i])
            self.i += 1
        value = int("".join(digits), 16)
        try:
            char = chr(value)
        except ValueError:
            self.fail("bad_escape", start, "The hex escape is not a valid code point.")
        return self._char_result(start, char, in_class)

    def _named_unicode(self, start: int, in_class: bool) -> Node | dict[str, Any]:
        if self.peek() != "{":
            self.fail("bad_escape", start, "\\N must be followed by {character name}.")
        self.i += 1
        begin = self.i
        while self.i < self.n and self.s[self.i] != "}":
            self.i += 1
        if self.peek() != "}":
            self.fail("bad_escape", start, "Unclosed \\N{...} name.")
        name = self.s[begin : self.i]
        self.i += 1
        if not name:
            self.fail("bad_escape", start, "Empty character name.")
        try:
            char = unicodedata.lookup(name)
        except KeyError:
            self.fail("bad_escape", start, f"Undefined character name {name!r}.")
        return self._char_result(start, char, in_class)

    def _property(self, start: int, letter: str, in_class: bool) -> Node | dict[str, Any]:
        if self.peek() != "{":
            self.fail("bad_escape", start, f"Unknown escape \\{letter}.")
        self.i += 1
        begin = self.i
        while self.i < self.n and self.s[self.i] != "}":
            self.i += 1
        if self.peek() != "}":
            self.fail("bad_escape", start, "Unclosed Unicode property.")
        name = self.s[begin : self.i]
        self.i += 1
        if not self.features.properties:
            self.fail(
                "unsupported",
                start,
                f"Unicode property \\{letter}{{{name}}} is not supported by {self.engine}.",
                exit_code=EXIT_UNSUPPORTED,
            )
        if in_class:
            return {
                "kind": "property",
                "name": name,
                "source": f"\\{letter}{{{name}}}",
                "start": start,
                "end": self.i,
            }
        return self.make("property", start, text=name, kind=letter)

    def _g_backref(self, start: int) -> Node:
        if self.peek() != "<":
            self.fail(
                "unsupported" if not self.features.pattern_g else "bad_escape",
                start,
                f"\\g<> pattern backreferences are not supported by {self.engine}."
                if not self.features.pattern_g
                else "\\g must be followed by <name> or <number>.",
                exit_code=EXIT_UNSUPPORTED if not self.features.pattern_g else EXIT_INVALID,
            )
        self.i += 1
        begin = self.i
        while self.i < self.n and self.s[self.i] != ">":
            self.i += 1
        if self.peek() != ">":
            self.fail("bad_escape", start, "Unclosed \\g<...>.")
        token = self.s[begin : self.i]
        self.i += 1
        if not self.features.pattern_g:
            self.fail(
                "unsupported",
                start,
                f"\\g<{token}> in a pattern is not supported by {self.engine}. "
                "Use \\\\1 or (?P=name).",
                exit_code=EXIT_UNSUPPORTED,
            )
        if token.isdigit():
            number = int(token)
            self._known_closed_number(number, start)
            return self.make("backref", start, kind="number", number=number)
        if not token.isidentifier() or token not in self.names:
            self.fail("bad_group", start, f"Unknown group name {token!r}.")
        self._known_closed_name(token, start)
        return self.make("backref", start, kind="name", name=token, number=self.names[token])

    def _numeric(self, start: int, first: str, in_class: bool) -> Node | dict[str, Any]:
        if in_class:
            if first not in _OCT:
                self.fail("bad_escape", start, f"Bad escape \\{first} inside a character class.")
            digits = first
            for _ in range(2):
                if self.i < self.n and self.s[self.i] in _OCT:
                    digits += self.s[self.i]
                    self.i += 1
                else:
                    break
            value = int(digits, 8)
            if value > 0o377:
                self.fail("bad_escape", start, "Octal escape is outside the range 0-377.")
            return self._char_result(start, chr(value), True)
        if first == "0":
            digits = "0"
            for _ in range(2):
                if self.i < self.n and self.s[self.i] in _OCT:
                    digits += self.s[self.i]
                    self.i += 1
                else:
                    break
            return self._char_result(start, chr(int(digits, 8)), False)
        digits = first
        if self.i < self.n and self.s[self.i] in _DIGITS:
            digits += self.s[self.i]
            self.i += 1
            if (
                digits[0] in _OCT
                and digits[1] in _OCT
                and self.i < self.n
                and self.s[self.i] in _OCT
            ):
                digits += self.s[self.i]
                self.i += 1
                value = int(digits, 8)
                if value > 0o377:
                    self.fail("bad_escape", start, f"Octal escape \\{digits} is outside 0-377.")
                return self._char_result(start, chr(value), False)
        group = int(digits)
        self._known_closed_number(group, start)
        return self.make("backref", start, kind="number", number=group)

    @overload
    def _char_result(self, start: int, char: str, in_class: Literal[True]) -> dict[str, Any]: ...

    @overload
    def _char_result(self, start: int, char: str, in_class: Literal[False]) -> Node: ...

    @overload
    def _char_result(self, start: int, char: str, in_class: bool) -> Node | dict[str, Any]: ...

    def _char_result(self, start: int, char: str, in_class: bool) -> Node | dict[str, Any]:
        if in_class:
            return {"kind": "char", "value": char, "start": start, "end": self.i}
        kind = _CHAR_KINDS.get(char)
        if kind is not None:
            return self.make("char", start, text=char, kind=kind)
        return self.make("literal", start, text=char)

    def apply_flag_chars(self, on: str, off: str, start: int) -> None:
        if ("L" in on or "L" in off) and self.engine == "python-re":
            self.fail("bad_flags", start, "The L flag cannot be used with str patterns.")
        if "a" in on and "u" in on:
            self.fail("bad_flags", start, "ASCII and UNICODE flags are incompatible.")
        flags = self.flags
        ignorecase = flags.ignorecase
        multiline = flags.multiline
        dotall = flags.dotall
        verbose = flags.verbose
        ascii_flag = flags.ascii
        unicode_flag = flags.unicode
        unicode_explicit = flags.unicode_explicit
        for char in on:
            if char == "i":
                ignorecase = True
            elif char == "m":
                multiline = True
            elif char == "s":
                dotall = True
            elif char == "x":
                verbose = True
            elif char == "a":
                ascii_flag = True
                unicode_flag = False
            elif char == "u":
                unicode_flag = True
                unicode_explicit = True
                ascii_flag = False
        for char in off:
            if char == "i":
                ignorecase = False
            elif char == "m":
                multiline = False
            elif char == "s":
                dotall = False
            elif char == "x":
                verbose = False
            elif char == "a":
                ascii_flag = False
            elif char == "u":
                unicode_flag = False
                unicode_explicit = False
        if ascii_flag and unicode_explicit:
            self.fail("bad_flags", start, "ASCII and UNICODE flags are incompatible.")
        self.flags = flags.replaced(
            ignorecase=ignorecase,
            multiline=multiline,
            dotall=dotall,
            verbose=verbose,
            ascii=ascii_flag,
            unicode=unicode_flag,
            unicode_explicit=unicode_explicit,
        )

    def open_capture(self, name: str | None, start: int) -> int:
        self.group_count += 1
        if self.group_count > 99:
            self.fail("too_many_groups", start, "More than 99 capturing groups.")
        number = self.group_count
        self.open_groups.append(number)
        if name is not None:
            self.names[name] = number
        return number

    def close_capture(self, number: int) -> None:
        self.open_groups.remove(number)
        self.closed.add(number)

    def read_name(self, start: int) -> str:
        begin = self.i
        while self.i < self.n and self.s[self.i] not in ">)=<":
            self.i += 1
        name = self.s[begin : self.i]
        if not name.isidentifier():
            self.fail(
                "bad_name",
                begin if name else start,
                f"Bad character in group name {name!r}.",
            )
        return name

    def expect_close(self, start: int) -> None:
        if self.peek() != ")":
            self.fail("unclosed_group", start, "Unclosed group. Expected ')'.")
        self.i += 1

    def children_of(self, node: Node) -> list[Node]:
        if node.type == "sequence":
            return list(node.children)
        if node.type == "empty":
            return []
        return [node]

    def coalesce(self, nodes: list[Node]) -> list[Node]:
        out: list[Node] = []
        buf: list[Node] = []

        def flush() -> None:
            if not buf:
                return
            if len(buf) == 1:
                out.append(buf[0])
            else:
                start = buf[0].start
                end = buf[-1].end
                text = "".join(item.text or "" for item in buf)
                out.append(
                    self.make(
                        "literal",
                        start,
                        end=end,
                        fragment=self.s[start:end],
                        text=text,
                    )
                )
            buf.clear()

        for item in nodes:
            item.children = self.coalesce(item.children)
            if item.type == "literal" and item.quantifier is None:
                buf.append(item)
            else:
                flush()
                out.append(item)
        flush()
        return out

    def skip_ws(self) -> None:
        if not self.flags.verbose:
            return
        while self.i < self.n:
            char = self.s[self.i]
            if char in _WHITESPACE:
                self.i += 1
                continue
            if char == "#":
                while self.i < self.n and self.s[self.i] != "\n":
                    self.i += 1
                continue
            break

    def peek(self) -> str:
        if self.i >= self.n:
            return ""
        return self.s[self.i]

    def make(self, type_name: str, start: int, **kwargs: Any) -> Node:
        end = int(kwargs.pop("end", self.i))
        fragment = str(kwargs.pop("fragment", self.s[start:end]))
        children = list(kwargs.pop("children", []))
        return Node(
            type=type_name,
            fragment=fragment,
            start=start,
            end=end,
            children=children,
            ignorecase=self.flags.ignorecase,
            multiline=self.flags.multiline,
            dotall=self.flags.dotall,
            ascii=self.flags.ascii,
            **kwargs,
        )

    def fail(
        self,
        kind: str,
        position: int,
        explanation: str,
        exit_code: int = EXIT_INVALID,
    ) -> NoReturn:
        fragment = self.s[position : position + 16] if 0 <= position <= self.n else ""
        raise PatternProblem(
            explanation,
            kind=kind,
            position=position,
            fragment=fragment,
            explanation=explanation,
            exit_code=exit_code,
        )

    def _top_children(self, node: Node) -> list[Node]:
        if node.type == "sequence":
            return self.coalesce(node.children)
        if node.type == "empty":
            return []
        return self.coalesce([node])

    def _known_closed_number(self, number: int, start: int) -> None:
        if number < 1 or number > self.group_count:
            self.fail("bad_group", start, f"Invalid group reference {number}.")
        if number in self.open_groups or number not in self.closed:
            self.fail(
                "open_group",
                start,
                "A backreference cannot refer to a group that is still open.",
            )

    def _known_closed_name(self, name: str, start: int) -> None:
        if name not in self.names:
            self.fail("bad_group", start, f"Unknown group name {name!r}.")
        self._known_closed_number(self.names[name], start)

    def _condition_ref(self, ref: str, start: int) -> tuple[int, str | None]:
        if not ref:
            self.fail("bad_group", start, "Conditional group is missing a name or number.")
        if ref.isdigit():
            number = int(ref)
            self._known_closed_number(number, start)
            return number, None
        if not ref.isidentifier():
            self.fail("bad_group", start, f"Bad conditional reference {ref!r}.")
        self._known_closed_name(ref, start)
        return self.names[ref], ref


def _display_children(node: Node) -> list[Node]:
    kids = list(node.children)
    if node.quantifier is not None:
        quant = node.quantifier
        kids.append(
            Node(
                type="repeat",
                fragment=quant.fragment,
                start=quant.start,
                end=quant.end,
                kind=quant.label(),
            )
        )
    return kids


def _anchor_label(node: Node) -> str:
    if node.kind == "start":
        return "Start of line" if node.multiline else "Start anchor"
    if node.kind == "end":
        return "End of line" if node.multiline else "End anchor"
    if node.kind == "absolute_start":
        return "Start of string"
    if node.kind == "absolute_end":
        return "End of string"
    if node.kind == "boundary":
        return "Word boundary"
    if node.kind == "non_boundary":
        return "Non-word boundary"
    return "Anchor"


def _category_label(node: Node) -> str:
    labels = {
        "digit": ("Digit", "ASCII digit"),
        "nondigit": ("Non-digit", "ASCII non-digit"),
        "word": ("Word character", "ASCII word character"),
        "nonword": ("Non-word character", "ASCII non-word character"),
        "space": ("Whitespace", "ASCII whitespace"),
        "nonspace": ("Non-whitespace", "ASCII non-whitespace"),
    }
    plain, ascii_label = labels.get(node.kind or "", ("Class", "ASCII class"))
    return ascii_label if node.ascii else plain


def _class_body(node: Node) -> str:
    bits: list[str] = []
    for part in node.parts:
        kind = part.get("kind")
        if kind == "range":
            bits.append(f"{part['start']}-{part['end']}")
        elif kind == "char":
            bits.append(visible(str(part.get("value", ""))))
        elif kind == "category":
            bits.append(str(part.get("source", part.get("name", ""))))
        elif kind == "property":
            bits.append(str(part.get("source", "")))
    return "".join(bits)


def _base_width(node: Node) -> int | None:
    if node.type in {"anchor", "comment", "empty", "lookahead", "lookbehind"}:
        return 0
    if node.type == "inline_flags":
        if not node.children:
            return 0
        return _sum_width(node.children)
    if node.type == "literal":
        return len(node.text or "")
    if node.type in {"category", "any", "char", "character_class", "property"}:
        return 1
    if node.type in {"group", "sequence", "atomic", "expression"}:
        return _sum_width(node.children)
    if node.type == "alternation":
        widths = [fixed_width(child) for child in node.children]
        if not widths or any(item is None for item in widths):
            return None if any(item is None for item in widths) else 0
        first = widths[0]
        if any(item != first for item in widths):
            return None
        return first
    if node.type in {"backref", "conditional", "recursion"}:
        return None
    return None


def _sum_width(nodes: list[Node]) -> int | None:
    total = 0
    for node in nodes:
        width = fixed_width(node)
        if width is None:
            return None
        total += width
    return total
