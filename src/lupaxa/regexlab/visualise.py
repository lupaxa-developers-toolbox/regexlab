"""Offline pattern diagrams. HTML and SVG escape untrusted pattern text."""

from __future__ import annotations

import html

from lupaxa.regexlab.parser import Node, node_label, render_tree


def visualise(node: Node, pattern: str, fmt: str) -> str:
    if fmt in {"tree", "ascii"}:
        return render_tree(node)
    if fmt == "mermaid":
        return _mermaid(node)
    if fmt == "svg":
        return _svg(node, pattern)
    if fmt == "html":
        return _html(node, pattern)
    from lupaxa.regexlab.errors import UsageError

    raise UsageError("format must be tree, ascii, svg, html, or mermaid")


def _mermaid(node: Node) -> str:
    lines = ["flowchart TD"]
    counter = 0

    def walk(current: Node, parent: str | None) -> None:
        nonlocal counter
        counter += 1
        ident = f"n{counter}"
        label = _mermaid_label(node_label(current))
        lines.append(f'    {ident}["{label}"]')
        if parent is not None:
            lines.append(f"    {parent} --> {ident}")
        for child in _kids(current):
            walk(child, ident)

    walk(node, None)
    return "\n".join(lines)


def _mermaid_label(text: str) -> str:
    escaped = html.escape(text, quote=True)
    return escaped.replace("[", "&#91;").replace("]", "&#93;").replace("\n", " ")


def _svg(node: Node, pattern: str) -> str:
    rows = render_tree(node).splitlines() or [""]
    height = 40 + 22 * len(rows)
    width = 640
    body = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        (
            '<text x="16" y="24" font-family="ui-monospace,monospace" font-size="14">'
            f"{html.escape(pattern)}</text>"
        ),
    ]
    for index, row in enumerate(rows):
        y = 52 + index * 22
        body.append(
            f'<text x="16" y="{y}" font-family="ui-monospace,monospace" font-size="14">'
            f"{html.escape(row)}</text>"
        )
    body.append("</svg>")
    return "\n".join(body)


def _html(node: Node, pattern: str) -> str:
    tree = html.escape(render_tree(node))
    safe_pattern = html.escape(pattern)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Regex Lab</title>\n"
        "<style>body{font-family:ui-monospace,monospace;margin:1.5rem}"
        "pre{white-space:pre-wrap}</style>\n"
        "</head>\n"
        "<body>\n"
        "<!-- generated offline by regex-lab -->\n"
        f'<h1>Regex Lab</h1>\n<pre id="pattern">{safe_pattern}</pre>\n'
        f'<pre id="tree">{tree}</pre>\n'
        "</body>\n</html>\n"
    )


def _kids(node: Node) -> list[Node]:
    children = list(node.children)
    if node.quantifier is not None:
        from lupaxa.regexlab.parser import Node as TreeNode

        quant = node.quantifier
        children.append(
            TreeNode(
                type="repeat",
                fragment=quant.fragment,
                start=quant.start,
                end=quant.end,
                kind=quant.label(),
            )
        )
    return children
