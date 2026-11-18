"""Colour policy. ``NO_COLOR`` and ``--no-colour`` both disable ANSI."""

from __future__ import annotations

import os
from io import StringIO

from rich.console import Console
from rich.text import Text


def no_color_env() -> bool:
    """True when the process environment disables colour.

    The ``NO_COLOR`` convention treats a present variable as off, including
    an empty value.
    """

    return "NO_COLOR" in os.environ


def colour_enabled(*, no_colour: bool) -> bool:
    return not (no_colour or no_color_env())


def highlight_spans(text: str, spans: list[tuple[int, int]], *, colour: bool) -> str:
    """Highlight match spans. Markers are used when colour is off."""

    if not colour or no_color_env():
        return _mark(text, spans)
    buf = StringIO()
    console = Console(file=buf, force_terminal=True, no_color=False, color_system="standard")
    rich = Text(text)
    for start, end in spans:
        if end > start:
            rich.stylize("reverse", start, end)
    console.print(rich, end="")
    return buf.getvalue()


def _mark(text: str, spans: list[tuple[int, int]]) -> str:
    inserts: list[tuple[int, int, str]] = []
    for start, end in spans:
        if end > start:
            inserts.append((start, 0, "«"))
            inserts.append((end, 1, "»"))
        else:
            inserts.append((start, 0, "│"))
    inserts.sort()
    pieces: list[str] = []
    cursor = 0
    for offset, _order, token in inserts:
        pieces.append(text[cursor:offset])
        pieces.append(token)
        cursor = offset
    pieces.append(text[cursor:])
    return "".join(pieces)
