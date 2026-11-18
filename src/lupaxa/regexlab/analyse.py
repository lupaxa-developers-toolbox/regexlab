"""Structural analysis and lint. Heuristics are labelled as heuristics."""

from __future__ import annotations

from dataclasses import dataclass

from lupaxa.regexlab.flagset import FlagSet
from lupaxa.regexlab.parser import Node, parse_pattern

_META = set(".^$*+?{}[]\\|()")


@dataclass
class Finding:
    id: str
    severity: str
    start: int
    end: int
    explanation: str
    evidence: str
    suggestion: str
    confidence: float
    heuristic: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "severity": self.severity,
            "location": {"start": self.start, "end": self.end},
            "explanation": self.explanation,
            "evidence": self.evidence,
            "suggestion": self.suggestion,
            "confidence": self.confidence,
            "heuristic": self.heuristic,
        }


def analyse_pattern(pattern: str, *, engine: str, flags: FlagSet) -> list[Finding]:
    node = parse_pattern(pattern, engine, flags)
    findings: list[Finding] = []
    _nested(node, findings)
    _wildcards(node, findings)
    _alternations(node, findings)
    _captures(node, findings)
    _anchors(node, findings)
    return findings


def lint_pattern(pattern: str, *, engine: str, flags: FlagSet) -> list[Finding]:
    node = parse_pattern(pattern, engine, flags)
    findings: list[Finding] = []
    _redundant_repeat(node, findings)
    _escapes(node, findings)
    _ranges(node, findings)
    _portability(node, engine, findings)
    return findings


def _nested(node: Node, findings: list[Finding]) -> None:
    if node.quantifier is not None and _contains_quantifier(node.children):
        findings.append(
            Finding(
                id="nested-quantifier",
                severity="warning",
                start=node.start,
                end=node.end,
                explanation=(
                    "A quantifier contains another quantifier. This is a heuristic "
                    "backtracking risk, not a proof of catastrophic behaviour."
                ),
                evidence=node.fragment,
                suggestion="Prefer a single quantified class, or bound both repeats.",
                confidence=0.75,
                heuristic=True,
            )
        )
    if node.quantifier is not None and any(child.type == "alternation" for child in node.children):
        findings.append(
            Finding(
                id="backtracking",
                severity="warning",
                start=node.start,
                end=node.end,
                explanation=(
                    "A repeated alternation can overlap itself. Heuristic only: "
                    "the engine may explore many splits."
                ),
                evidence=node.fragment,
                suggestion="Rewrite overlapping alternatives so each branch has a distinct prefix.",
                confidence=0.6,
                heuristic=True,
            )
        )
    for child in node.children:
        _nested(child, findings)


def _contains_quantifier(nodes: list[Node]) -> bool:
    return any(node.quantifier is not None or _contains_quantifier(node.children) for node in nodes)


def _wildcards(node: Node, findings: list[Finding]) -> None:
    quant = node.quantifier
    unbounded = quant is not None and not (quant.min == quant.max and quant.max is not None)
    if node.type == "any" and unbounded:
        findings.append(
            Finding(
                id="wildcard",
                severity="info",
                start=node.start,
                end=node.end,
                explanation="A quantified dot matches a variable run of characters.",
                evidence=node.fragment,
                suggestion=(
                    "Constrain it with a class or a possessive quantifier "
                    "when the span should be tight."
                ),
                confidence=0.5,
                heuristic=True,
            )
        )
    for child in node.children:
        _wildcards(child, findings)


def _alternations(node: Node, findings: list[Finding]) -> None:
    if node.type == "alternation":
        seen: list[str] = []
        for child in node.children:
            key = child.fragment
            if key in seen:
                findings.append(
                    Finding(
                        id="overlapping-alternation",
                        severity="warning",
                        start=node.start,
                        end=node.end,
                        explanation=(
                            "Two alternatives have the same fragment, so one of them never wins."
                        ),
                        evidence=node.fragment,
                        suggestion="Remove the duplicate alternative.",
                        confidence=0.9,
                        heuristic=False,
                    )
                )
                break
            seen.append(key)
    for child in node.children:
        _alternations(child, findings)


def _captures(node: Node, findings: list[Finding]) -> None:
    referenced = _referenced(node)
    for group in _groups(node):
        key = group.name or str(group.number)
        if key not in referenced:
            findings.append(
                Finding(
                    id="unused-capture",
                    severity="info",
                    start=group.start,
                    end=group.end,
                    explanation=(
                        "This capturing group is never referenced by a backreference. "
                        "Heuristic: it may still be used by a replacement or a caller."
                    ),
                    evidence=group.fragment,
                    suggestion=(
                        "Use a non-capturing group if the text does not need to be captured."
                    ),
                    confidence=0.4,
                    heuristic=True,
                )
            )


def _groups(node: Node) -> list[Node]:
    found: list[Node] = []
    if node.type == "group" and node.kind in {"capturing", "named"}:
        found.append(node)
    for child in node.children:
        found.extend(_groups(child))
    return found


def _referenced(node: Node) -> set[str]:
    found: set[str] = set()

    def walk(current: Node) -> None:
        if current.type == "backref":
            if current.name:
                found.add(current.name)
            if current.number is not None:
                found.add(str(current.number))
        if current.type == "conditional":
            if current.name:
                found.add(current.name)
            if current.number is not None:
                found.add(str(current.number))
        for child in current.children:
            walk(child)

    walk(node)
    return found


def _anchors(node: Node, findings: list[Finding]) -> None:
    if node.type != "expression":
        return
    significant = [
        child
        for child in node.children
        if child.type not in {"comment", "inline_flags"} or child.children
    ]
    if not significant:
        return
    starts = significant[0].type == "anchor" and significant[0].kind in {"start", "absolute_start"}
    ends = significant[-1].type == "anchor" and significant[-1].kind in {"end", "absolute_end"}
    if starts and ends:
        return
    findings.append(
        Finding(
            id="unanchored",
            severity="info",
            start=node.start,
            end=node.end,
            explanation=(
                "The pattern does not anchor both ends. fullmatch mode still anchors the test; "
                "search mode does not."
            ),
            evidence=node.fragment,
            suggestion="Add ^ or \\A and $ or \\Z when the whole string should match.",
            confidence=0.45,
            heuristic=True,
        )
    )


def _redundant_repeat(node: Node, findings: list[Finding]) -> None:
    quant = node.quantifier
    if quant is not None and quant.min == quant.max == 1:
        findings.append(
            Finding(
                id="redundant-repetition",
                severity="warning",
                start=quant.start,
                end=quant.end,
                explanation="A repeat of exactly one does not change the match.",
                evidence=quant.fragment,
                suggestion="Remove the {1} quantifier.",
                confidence=0.95,
                heuristic=False,
            )
        )
    for left, right in zip(node.children, node.children[1:], strict=False):
        if not _unbounded_greedy(left) or not _unbounded_greedy(right):
            continue
        if _atom_key(left) != _atom_key(right):
            continue
        findings.append(
            Finding(
                id="redundant-repetition",
                severity="warning",
                start=left.start,
                end=right.end,
                explanation=(
                    "Two adjacent unbounded repeats of the same atom overlap. "
                    "The second repeat cannot consume anything the first left behind."
                ),
                evidence=left.fragment + right.fragment,
                suggestion="Keep a single quantified atom.",
                confidence=0.9,
                heuristic=False,
            )
        )
    for child in node.children:
        _redundant_repeat(child, findings)


def _unbounded_greedy(node: Node) -> bool:
    quant = node.quantifier
    return quant is not None and quant.max is None and not quant.lazy and not quant.possessive


def _atom_key(node: Node) -> tuple[object, ...]:
    return (node.type, node.kind, node.text, tuple(node.parts), node.negate)


def _escapes(node: Node, findings: list[Finding]) -> None:
    if node.type == "literal" and "\\" in node.fragment:
        index = 0
        fragment = node.fragment
        while index < len(fragment):
            if fragment[index] == "\\" and index + 1 < len(fragment):
                nxt = fragment[index + 1]
                if nxt not in _META:
                    findings.append(
                        Finding(
                            id="unnecessary-escape",
                            severity="warning",
                            start=node.start + index,
                            end=node.start + index + 2,
                            explanation=(
                                f"Escaping {nxt!r} has no effect outside a character class."
                            ),
                            evidence="\\" + nxt,
                            suggestion=f"Write {nxt} without a backslash.",
                            confidence=0.85,
                            heuristic=False,
                        )
                    )
                index += 2
                continue
            index += 1
    for child in node.children:
        _escapes(child, findings)


def _ranges(node: Node, findings: list[Finding]) -> None:
    if node.type == "character_class":
        spans: list[tuple[int, int, str]] = []
        for part in node.parts:
            if part.get("kind") != "range":
                continue
            start = ord(str(part["start"]))
            end = ord(str(part["end"]))
            label = f"{part['start']}-{part['end']}"
            if start == end:
                findings.append(
                    Finding(
                        id="redundant-range",
                        severity="warning",
                        start=node.start,
                        end=node.end,
                        explanation=f"The range {label} contains only one character.",
                        evidence=node.fragment,
                        suggestion="Write that character on its own.",
                        confidence=0.9,
                        heuristic=False,
                    )
                )
            for prev_start, prev_end, prev_label in spans:
                if start <= prev_end and end >= prev_start:
                    findings.append(
                        Finding(
                            id="overlapping-range",
                            severity="warning",
                            start=node.start,
                            end=node.end,
                            explanation=f"Ranges {prev_label} and {label} overlap.",
                            evidence=node.fragment,
                            suggestion="Merge them into one range.",
                            confidence=0.8,
                            heuristic=False,
                        )
                    )
            spans.append((start, end, label))
    for child in node.children:
        _ranges(child, findings)


def _portability(node: Node, engine: str, findings: list[Finding]) -> None:
    notes: list[tuple[str, str]] = []
    if node.type == "recursion":
        notes.append(("recursion", "Recursion is not available in python-re."))
    if node.type == "property":
        notes.append(("unicode-property", "Unicode properties are not available in python-re."))
    if node.quantifier is not None and node.quantifier.possessive and engine != "python-re":
        notes.append(("possessive", "Confirm possessive quantifiers on every target engine."))
    for ident, explanation in notes:
        findings.append(
            Finding(
                id="portability",
                severity="warning",
                start=node.start,
                end=node.end,
                explanation=explanation,
                evidence=node.fragment,
                suggestion=f"Avoid {ident} if the pattern must run on python-re.",
                confidence=0.7,
                heuristic=False,
            )
        )
    for child in node.children:
        _portability(child, engine, findings)
