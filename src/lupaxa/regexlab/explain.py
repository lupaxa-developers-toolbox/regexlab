"""Explanations derived from the syntax tree."""

from __future__ import annotations

from lupaxa.regexlab.parser import Node, Quantifier, visible


def explain_text(node: Node, *, engine: str, detail: str, flags: str) -> str:
    lines = _lines(node)
    if _tree_ignorecase(node):
        lines.insert(0, "Matching is case-insensitive.")
    if detail == "summary":
        body = " ".join(lines) if lines else "Empty pattern."
    else:
        body = "\n".join(lines) if lines else "Empty pattern."
    if detail != "technical":
        return body
    header = [
        f"engine: {engine}",
        f"flags: {flags or '(none)'}",
        "offsets:",
        *_offsets(node, 0),
    ]
    return body + "\n\n" + "\n".join(header)


def _lines(node: Node) -> list[str]:
    if node.type == "expression":
        lines: list[str] = []
        for child in node.children:
            lines.extend(_lines(child))
        if not lines:
            return ["Empty pattern. It matches an empty string."]
        return lines
    if node.type == "alternation":
        options = " or ".join(_noun(child) for child in node.children) or "an empty alternative"
        return [f"Either {_quant(options, node.quantifier)}."]
    if node.type == "conditional":
        target = node.name or str(node.number)
        yes = _noun(node.children[0]) if node.children else "an empty string"
        if len(node.children) > 1:
            no = _noun(node.children[1])
            text = f"If group {target} matched, {yes}; otherwise {no}."
        else:
            text = f"If group {target} matched, {yes}."
        return [text]
    return [_sentence(node)]


def _lead(text: str) -> str:
    if not text:
        return text
    return text[0].upper() + text[1:]


def _sentence(node: Node) -> str:
    if node.type == "anchor":
        return _anchor_sentence(node)
    if node.type == "group":
        inner = _join(node.children) or "an empty string"
        body = _quant(inner, node.quantifier)
        if node.kind == "named":
            return f'Capture "{node.name}" as {body}.'
        if node.kind == "non_capturing":
            return f"Non-capturing group: {body}."
        return f"Capture group {node.number} as {body}."
    if node.type == "inline_flags":
        if node.children:
            inner = _join(node.children)
            return f"With flags {node.text}: {inner}."
        return f"Turn on flags {node.text} for the rest of the pattern."
    if node.type == "comment":
        return "Comment, ignored by the engine."
    if node.type == "recursion":
        return "Recursion into the expression. Generation cannot expand this."
    if node.type == "backref":
        target = node.name or str(node.number)
        return f"Backreference to {target}, the text already captured by that group."
    if node.type in {"lookahead", "lookbehind"}:
        side = "ahead" if node.type == "lookahead" else "behind"
        polarity = "not " if node.negate else ""
        inner = _join(node.children) or "an empty string"
        return f"Look{side} that {polarity}{inner} is there, without consuming it."
    if node.type == "atomic":
        inner = _join(node.children) or "an empty string"
        quantified = _quant(inner, node.quantifier)
        return f"Atomic group: {quantified}. Once matched, it does not backtrack."
    return _lead(_quant(_noun(node), node.quantifier)) + "."


def _anchor_sentence(node: Node) -> str:
    kind = node.kind
    if kind == "start":
        if node.multiline:
            return "Start of a line."
        return "Start of the string."
    if kind == "end":
        if node.multiline:
            return "End of a line."
        return "End of the string."
    if kind == "absolute_start":
        return "Start of the string, even when multiline is set."
    if kind == "absolute_end":
        return "End of the string, even when multiline is set."
    if kind == "boundary":
        if node.ascii:
            return "An ASCII word boundary."
        return "A Unicode word boundary."
    if kind == "non_boundary":
        return "Not a word boundary."
    return "Anchor."


def _noun(node: Node) -> str:
    base = _base_noun(node)
    return _quant(base, node.quantifier)


def _base_noun(node: Node) -> str:
    if node.type == "literal":
        text = node.text or ""
        if text == "-":
            return 'a hyphen "-"'
        return f"the literal {visible(text)!r}"
    if node.type == "char":
        names = {
            "newline": "a newline",
            "tab": "a tab",
            "return": "a carriage return",
            "formfeed": "a form feed",
            "vtab": "a vertical tab",
            "bell": "a bell character",
        }
        return names.get(node.kind or "", f"the character {visible(node.text or '')!r}")
    if node.type == "category":
        return _category_noun(node)
    if node.type == "any":
        if node.dotall:
            return "any character, including a newline"
        return "any character except a newline"
    if node.type == "character_class":
        body = _class_phrase(node)
        if node.negate:
            return f"a character not in {body}"
        if body in {"lowercase letters", "uppercase letters", "decimal digits"}:
            return body
        return f"a character in {body}"
    if node.type == "group":
        inner = _join(node.children) or "an empty string"
        if node.kind == "named":
            return f'capture "{node.name}" ({inner})'
        if node.kind == "non_capturing":
            return f"({inner})"
        return f"capture group {node.number} ({inner})"
    if node.type == "anchor":
        return _anchor_sentence(node).rstrip(".")
    if node.type == "alternation":
        return " or ".join(_noun(child) for child in node.children)
    if node.type == "empty":
        return "an empty string"
    if node.type in {"sequence", "atomic", "inline_flags"}:
        return _join(node.children) or "an empty string"
    if node.type == "backref":
        return f"the text captured by {node.name or node.number}"
    if node.type == "property":
        return f"a Unicode property {node.text}"
    return node.type.replace("_", " ")


def _category_noun(node: Node) -> str:
    ascii_on = node.ascii
    if node.kind == "digit":
        return "an ASCII digit (0-9)" if ascii_on else "decimal digits"
    if node.kind == "nondigit":
        return "a non-ASCII-digit" if ascii_on else "a non-digit"
    if node.kind == "word":
        return "an ASCII word character" if ascii_on else "a Unicode word character"
    if node.kind == "nonword":
        return "a non-ASCII-word character" if ascii_on else "a non-word character"
    if node.kind == "space":
        return "an ASCII whitespace character" if ascii_on else "a Unicode whitespace character"
    if node.kind == "nonspace":
        return "a non-whitespace character"
    return "a character class"


def _class_phrase(node: Node) -> str:
    bits: list[str] = []
    for part in node.parts:
        kind = part.get("kind")
        if kind == "range":
            start = str(part["start"])
            end = str(part["end"])
            if start == "a" and end == "z":
                bits.append("lowercase letters")
            elif start == "A" and end == "Z":
                bits.append("uppercase letters")
            elif start == "0" and end == "9":
                bits.append("decimal digits")
            else:
                bits.append(f"{start} to {end}")
        elif kind == "char":
            bits.append(repr(visible(str(part.get("value", "")))))
        elif kind == "category":
            bits.append(str(part.get("source", part.get("name"))))
        elif kind == "property":
            bits.append(str(part.get("source", "property")))
    if not bits:
        return "the class"
    if len(bits) == 1 and node.parts and node.parts[0].get("kind") == "range":
        return bits[0]
    return ", ".join(bits)


def _join(children: list[Node]) -> str:
    return " then ".join(_noun(child) for child in children)


def _quant(base: str, quant: Quantifier | None) -> str:
    if quant is None:
        return base
    words = _quant_words(quant)
    return f"{words} {base}"


def _quant_words(quant: Quantifier) -> str:
    if quant.min == 0 and quant.max is None:
        words = "zero or more"
    elif quant.min == 1 and quant.max is None:
        words = "one or more"
    elif quant.min == 0 and quant.max == 1:
        words = "an optional"
    elif quant.max is None:
        words = f"{quant.min} or more"
    elif quant.min == quant.max:
        words = f"exactly {quant.min}"
    else:
        words = f"{quant.min} to {quant.max}"
    if quant.possessive:
        words += " possessive"
    elif quant.lazy:
        words += " lazy"
    return words


def _tree_ignorecase(node: Node) -> bool:
    return bool(node.ignorecase and node.type == "expression")


def _offsets(node: Node, indent: int) -> list[str]:
    pad = "  " * indent
    lines = [f"{pad}{node.type} [{node.start}:{node.end}] {node.fragment!r}"]
    for child in node.children:
        lines.extend(_offsets(child, indent + 1))
    return lines
