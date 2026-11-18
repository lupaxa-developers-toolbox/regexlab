"""Match reporting shared by test, matches, and findall."""

from __future__ import annotations

from lupaxa.regexlab.colour import highlight_spans
from lupaxa.regexlab.engines import MatchInfo


def line_column(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last = text.rfind("\n", 0, offset)
    column = offset + 1 if last < 0 else offset - last
    return line, column


def context_block(text: str, start: int, radius: int) -> str:
    lines = text.splitlines() or [""]
    line_index = text.count("\n", 0, start)
    begin = max(0, line_index - radius)
    end = min(len(lines), line_index + radius + 1)
    return "\n".join(lines[begin:end])


def render_matches(
    subject_label: str,
    subject: str,
    matches: list[MatchInfo],
    *,
    engine: str,
    flags: str,
    mode: str,
    colour: bool,
    context: int,
    truncated: bool,
) -> str:
    lines = [
        f"subject: {subject_label}",
        f"engine: {engine}",
        f"flags: {flags or '(none)'}",
        f"mode: {mode}",
        f"matches: {len(matches)}",
    ]
    if truncated:
        lines.append("warning: match list truncated by --max-matches")
    if not matches:
        lines.append("no match")
        return "\n".join(lines)
    spans = [(item.start, item.end) for item in matches if item.end >= item.start]
    highlighted = highlight_spans(subject, spans, colour=colour)
    if "\n" not in subject and len(subject) <= 200:
        lines.append(f"highlighted: {highlighted}")
    for index, item in enumerate(matches, start=1):
        line, column = line_column(subject, item.start)
        groups = ", ".join("null" if group is None else group for group in item.groups) or "(none)"
        named = (
            ", ".join(f"{key}={value}" for key, value in item.groupdict.items())
            if item.groupdict
            else "(none)"
        )
        lines.extend(
            [
                f"match {index}",
                f"  text: {item.text}",
                f"  span: {item.start}-{item.end}",
                f"  line: {line}",
                f"  column: {column}",
                f"  groups: {groups}",
                f"  named: {named}",
            ]
        )
        if context:
            lines.append("  context:")
            for row in context_block(subject, item.start, context).splitlines():
                lines.append(f"    {row}")
    return "\n".join(lines)


def split_rows(compiled_split: list[str], pattern_groups: int) -> str:
    """Show segments. Capturing splits from the engine include separators."""

    del pattern_groups
    lines: list[str] = []
    for index, part in enumerate(compiled_split):
        kind = "segment" if index % 2 == 0 else "separator"
        # Without a known capturing pattern, every part is still labelled in order.
        # Callers that computed separators separately can pass them preformatted.
        lines.append(f"{kind} {index}: {part}")
    return "\n".join(lines)


def render_split(segments: list[str], separators: list[str]) -> str:
    lines: list[str] = []
    for index, segment in enumerate(segments):
        lines.append(f"segment {index}: {segment}")
        if index < len(separators):
            lines.append(f"separator {index}: {separators[index]}")
    return "\n".join(lines)
