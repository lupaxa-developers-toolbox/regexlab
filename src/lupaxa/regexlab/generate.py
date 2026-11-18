"""Generate example strings from a syntax tree and verify them with the engine."""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from lupaxa.regexlab.engines import compile_pattern, iter_matches
from lupaxa.regexlab.errors import IncompleteError, UnsupportedError
from lupaxa.regexlab.flagset import FlagSet
from lupaxa.regexlab.parser import Node, parse_pattern

_UNSUPPORTED = {"backref", "recursion", "conditional", "lookahead", "lookbehind"}


@dataclass
class NegativeSample:
    text: str
    category: str


@dataclass
class GenerateReport:
    positives: list[str] = field(default_factory=list)
    negatives: list[NegativeSample] = field(default_factory=list)
    incomplete: bool = False
    notes: list[str] = field(default_factory=list)


class _EmitFail(Exception):
    pass


def generate_samples(
    pattern: str,
    *,
    engine: str,
    flags: FlagSet,
    mode: str,
    count: int,
    seed: int,
    min_length: int,
    max_length: int,
    unique: bool,
    include_invalid: bool,
) -> GenerateReport:
    """Build samples. Every positive is checked, and every negative must fail."""

    node = parse_pattern(pattern, engine, flags)
    blocked = _blocked(node)
    if blocked:
        detail = "; ".join(blocked)
        raise UnsupportedError(
            "Refusing to generate from unsupported constructs "
            f"(they are reported, not ignored): {detail}"
        )
    rng = random.Random(seed)
    report = GenerateReport()
    seen: set[str] = set()
    attempts = 0
    limit = max(40, count * 50)
    while len(report.positives) < count and attempts < limit:
        attempts += 1
        try:
            text = _emit(node, rng, max_length)
        except _EmitFail:
            continue
        if len(text) < min_length or len(text) > max_length:
            continue
        if unique and text in seen:
            continue
        if not _matches(pattern, engine, flags, text, mode):
            continue
        seen.add(text)
        report.positives.append(text)
    if len(report.positives) < count:
        report.incomplete = True
        report.notes.append(
            f"Produced {len(report.positives)} of {count} verified positive samples "
            f"within {limit} attempts."
        )
    if include_invalid:
        for text in report.positives:
            for sample, category in _mutations(text):
                if sample == text:
                    continue
                if _matches(pattern, engine, flags, sample, mode):
                    continue
                if any(item.text == sample for item in report.negatives):
                    continue
                report.negatives.append(NegativeSample(sample, category))
        if not report.negatives:
            report.notes.append(
                "No negative sample survived verification. The pattern still matched each mutation."
            )
    if report.incomplete and not report.positives and count > 0:
        note = report.notes[0] if report.notes else "Could not generate a verified sample."
        raise IncompleteError(note)
    return report


def _blocked(node: Node) -> list[str]:
    found: list[str] = []

    def walk(current: Node) -> None:
        if current.type in _UNSUPPORTED:
            label = {
                "backref": "backreference",
                "recursion": "recursion",
                "conditional": "conditional group",
                "lookahead": "lookahead",
                "lookbehind": "lookbehind",
            }[current.type]
            found.append(f"{label} at position {current.start}")
        for child in current.children:
            walk(child)

    walk(node)
    return found


def _matches(pattern: str, engine: str, flags: FlagSet, text: str, mode: str) -> bool:
    compiled = compile_pattern(engine, pattern, flags)
    matches, _truncated = iter_matches(compiled, text, mode, max_matches=1)
    return bool(matches)


def _emit(node: Node, rng: random.Random, budget: int) -> str:
    def once() -> str:
        return _body(node, rng, budget)

    quant = node.quantifier
    if quant is None:
        return once()
    high = quant.max if quant.max is not None else min(quant.min + 3, 6)
    high = max(quant.min, min(high, 8, budget if budget > 0 else high))
    if quant.min > budget:
        raise _EmitFail()
    if quant.min > high:
        raise _EmitFail()
    count = quant.min if quant.min == high else rng.randint(quant.min, high)
    parts: list[str] = []
    used = 0
    for _ in range(count):
        piece = once()
        used += len(piece)
        if used > budget:
            raise _EmitFail()
        parts.append(piece)
    return "".join(parts)


def _body(node: Node, rng: random.Random, budget: int) -> str:
    kind = node.type
    if kind in {"expression", "sequence", "group", "atomic", "inline_flags"}:
        return "".join(_emit(child, rng, budget) for child in node.children)
    if kind == "alternation":
        if not node.children:
            return ""
        return _emit(rng.choice(node.children), rng, budget)
    if kind in {"literal", "char"}:
        return node.text or ""
    if kind == "any":
        alphabet = "abcXYZ012"
        if node.dotall:
            alphabet += "\n"
        return rng.choice(alphabet)
    if kind == "category":
        return rng.choice(_category_chars(node.kind or "", node.ascii))
    if kind == "character_class":
        choices = _class_chars(node)
        if not choices:
            raise _EmitFail()
        return rng.choice(choices)
    if kind in {"anchor", "comment", "empty"}:
        return ""
    if kind == "property":
        raise _EmitFail()
    raise _EmitFail()


def _category_chars(kind: str, ascii_only: bool) -> str:
    del ascii_only  # ASCII digits/words are valid Unicode members too.
    table = {
        "digit": "0123456789",
        "nondigit": "abcXYZ!",
        "word": "abcXYZ012_",
        "nonword": " \t!",
        "space": " \t",
        "nonspace": "abcXYZ",
    }
    return table.get(kind, "a")


def _class_chars(node: Node) -> str:
    chars: list[str] = []
    for part in node.parts:
        kind = part.get("kind")
        if kind == "range":
            start = ord(str(part["start"]))
            end = ord(str(part["end"]))
            span = end - start
            if span > 64:
                chars.append(chr(start))
                chars.append(chr(end))
                chars.append(chr((start + end) // 2))
            else:
                chars.extend(chr(value) for value in range(start, end + 1))
        elif kind == "char":
            chars.append(str(part.get("value", "")))
        elif kind == "category":
            chars.extend(_category_chars(str(part.get("name", "")), node.ascii))
    if node.negate:
        pool = list("abcXYZ012_ \t!")
        blocked = set(chars)
        chars = [char for char in pool if char not in blocked] or ["!"]
    return "".join(chars)


def _mutations(text: str) -> list[tuple[str, str]]:
    if not text:
        return [("x", "extra-character")]
    flip = "Z" if text[0] != "Z" else "Y"
    samples = [
        (flip + text[1:], "wrong-character"),
        (text[1:], "truncated"),
        (text + "!", "extra-character"),
    ]
    if text[0].isalpha():
        samples.append((text[0].swapcase() + text[1:], "case-flip"))
    return samples
