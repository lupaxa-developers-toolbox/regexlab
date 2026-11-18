"""Textual app construction. Evaluation is not started for an empty pattern."""

from __future__ import annotations

import asyncio

from lupaxa.regexlab.interactive import RegexLabApp

WIDGETS = (
    "pattern-input",
    "engine-select",
    "flags-input",
    "mode-select",
    "text-input",
    "matches",
    "groups",
    "explanation",
    "tree",
    "warnings",
    "performance",
)


def test_app_imports_and_widgets() -> None:
    app = RegexLabApp()

    async def _check() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            for widget_id in WIDGETS:
                assert app.query_one(f"#{widget_id}")
            assert app.query_one("#run-button")
            await pilot.resize_terminal(40, 12)
            await pilot.pause()
            assert app.has_class("compact")

    asyncio.run(_check())
