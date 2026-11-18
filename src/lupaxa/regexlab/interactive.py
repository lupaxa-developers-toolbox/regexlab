"""Textual workbench. Evaluation runs in a cancellable worker process."""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, Select, Static, TextArea

from lupaxa.regexlab.config import Settings
from lupaxa.regexlab.explain import explain_text
from lupaxa.regexlab.library import LibraryEntry, add_entry, find_entry
from lupaxa.regexlab.parser import parse_pattern, render_tree
from lupaxa.regexlab.suite import load_suite, render_suite_run, run_suite

_MODES = ("fullmatch", "match", "search", "finditer", "findall")


class RegexLabApp(App[None]):
    """Pattern editor with live, bounded evaluation."""

    TITLE = "Regex Lab"
    CSS = """
    Screen { layout: vertical; }
    #controls { height: auto; layout: horizontal; }
    #pattern-input { width: 1fr; }
    #body { layout: horizontal; height: 1fr; }
    #primary, #secondary { width: 1fr; height: 1fr; }
    #matches, #groups, #explanation, #tree, #warnings, #performance {
        height: auto;
        max-height: 14;
    }
    .compact #secondary { display: none; }
    .compact #controls { layout: vertical; }
    """
    BINDINGS = [
        Binding("ctrl+s", "save_pattern", "Save"),
        Binding("ctrl+o", "load_pattern", "Load"),
        Binding("ctrl+r", "run_suite", "Suite"),
        Binding("escape", "cancel_work", "Cancel", priority=True),
    ]

    def __init__(self, settings: Settings | None = None, pattern: str = "") -> None:
        super().__init__()
        self.settings = settings or Settings()
        self._initial = pattern
        self._token = 0
        self._holder: dict[str, Any] = {}
        self._timer: Any = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="controls"):
            yield Input(placeholder="Pattern", id="pattern-input")
            yield Select(
                [(name, name) for name in ("python-re", "python-regex", "pcre2")],
                id="engine-select",
                value=self.settings.engine,
                allow_blank=False,
            )
            yield Input(placeholder="flags", id="flags-input", value=self.settings.flags)
            yield Select(
                [(name, name) for name in _MODES],
                id="mode-select",
                value="fullmatch",
                allow_blank=False,
            )
            yield Button("Run", id="run-button")
        with Horizontal(id="body"):
            with Vertical(id="primary"):
                yield TextArea(id="text-input")
                yield Static("Matches", id="matches")
                yield Static("Groups", id="groups")
                yield Static("", id="performance")
            with Vertical(id="secondary"):
                yield Static("Explanation", id="explanation")
                yield Static("Tree", id="tree")
                yield Static("Warnings", id="warnings")
                yield Input(placeholder="Library name", id="library-name")
                yield Input(placeholder="Suite path", id="suite-path")
        yield Footer()

    def on_mount(self) -> None:
        self._apply_size(self.size.width, self.size.height)
        if self._initial:
            self.query_one("#pattern-input", Input).value = self._initial
            self._schedule()

    def on_resize(self, event: Any) -> None:
        self._apply_size(event.size.width, event.size.height)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "pattern-input":
            self._schedule()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        del event
        self._schedule()

    def on_select_changed(self, event: Select.Changed) -> None:
        del event
        self._schedule()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-button":
            self._schedule()

    def action_cancel_work(self) -> None:
        proc = self._holder.get("proc")
        if proc is not None and proc.is_alive():
            proc.terminate()
        self.query_one("#performance", Static).update("cancelled")

    def action_save_pattern(self) -> None:
        name = self.query_one("#library-name", Input).value.strip()
        pattern = self.query_one("#pattern-input", Input).value
        if not name or not pattern:
            self.query_one("#warnings", Static).update(
                "Set a library name and a pattern before saving."
            )
            return
        try:
            add_entry(
                self.settings.library_dir,
                LibraryEntry(
                    name=name,
                    pattern=pattern,
                    engine=str(self.query_one("#engine-select", Select).value),
                    flags=self.query_one("#flags-input", Input).value,
                    mode=str(self.query_one("#mode-select", Select).value),
                ),
                force=False,
            )
        except Exception as exc:  # noqa: BLE001 - show library errors in the UI
            self.query_one("#warnings", Static).update(str(exc))
            return
        self.query_one("#warnings", Static).update(f"Saved {name}.")

    def action_load_pattern(self) -> None:
        name = self.query_one("#library-name", Input).value.strip()
        if not name:
            self.query_one("#warnings", Static).update("Enter a library name to load.")
            return
        try:
            entry = find_entry(self.settings.library_dir, name)
        except Exception as exc:  # noqa: BLE001
            self.query_one("#warnings", Static).update(str(exc))
            return
        self.query_one("#pattern-input", Input).value = entry.pattern
        self.query_one("#flags-input", Input).value = entry.flags
        self._schedule()

    def action_run_suite(self) -> None:
        raw = self.query_one("#suite-path", Input).value.strip()
        if not raw:
            self.query_one("#warnings", Static).update("Enter a suite path.")
            return
        try:
            from pathlib import Path

            result = run_suite(load_suite(Path(raw)))
        except Exception as exc:  # noqa: BLE001
            self.query_one("#warnings", Static).update(str(exc))
            return
        self.query_one("#matches", Static).update(render_suite_run(result))

    def _apply_size(self, width: int, height: int) -> None:
        if width < 80 or height < 24:
            self.add_class("compact")
        else:
            self.remove_class("compact")

    def _schedule(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(0.15, self._start_eval)

    def _start_eval(self) -> None:
        pattern = self.query_one("#pattern-input", Input).value
        if not pattern:
            self.query_one("#explanation", Static).update("Enter a pattern.")
            self.query_one("#tree", Static).update("")
            self.query_one("#matches", Static).update("")
            self.query_one("#warnings", Static).update("")
            return
        proc = self._holder.get("proc")
        if proc is not None and proc.is_alive():
            proc.terminate()
        self._token += 1
        token = self._token
        self.run_worker(lambda: self._evaluate(token, pattern), thread=True, exclusive=True)

    def _evaluate(self, token: int, pattern: str) -> None:
        import time

        from lupaxa.regexlab.flagset import parse_flags
        from lupaxa.regexlab.isolate import run

        started = time.perf_counter()
        engine = str(self.query_one("#engine-select", Select).value)
        flags_text = self.query_one("#flags-input", Input).value
        mode = str(self.query_one("#mode-select", Select).value)
        subject = self.query_one("#text-input", TextArea).text
        warnings: list[str] = []
        try:
            flags = parse_flags(flags_text, engine=engine)
            node = parse_pattern(pattern, engine, flags)
            explanation = explain_text(
                node, engine=engine, detail="detailed", flags=flags.letters()
            )
            tree = render_tree(node)
        except Exception as exc:  # noqa: BLE001 - surface parser errors in the UI
            self.call_from_thread(self._show_static, token, str(exc), "", "", "", f"{exc}")
            return
        payload = {
            "engine": engine,
            "pattern": pattern,
            "flags": flags.letters(),
            "mode": mode,
            "timeout": self.settings.timeout,
            "max_matches": self.settings.max_matches,
            "subjects": [("input", subject)],
        }
        message = run(
            "match",
            payload,
            timeout=self.settings.timeout + 0.75,
            method="spawn",
            holder=self._holder,
        )
        if token != self._token:
            return
        elapsed = (time.perf_counter() - started) * 1000
        if message.get("exit_code") not in (0, None) or message.get("status") != "ok":
            error = message.get("error") or {}
            detail = error.get("explanation") or error.get("message") or message.get("status")
            warnings.append(str(detail))
            match_text = "\n".join(warnings)
            group_text = ""
        else:
            subject_row = (message.get("subjects") or [{}])[0]
            rows = subject_row.get("matches") or []
            match_lines = []
            group_lines = []
            for index, row in enumerate(rows, start=1):
                match_lines.append(
                    f"{index}: {row.get('text')!r} [{row.get('start')}:{row.get('end')}]"
                )
                group_lines.append(f"{index}: {row.get('groups')} {row.get('groupdict')}")
            match_text = "\n".join(match_lines) or "no match"
            group_text = "\n".join(group_lines) or "(none)"
        self.call_from_thread(
            self._show_static,
            token,
            match_text,
            group_text,
            explanation,
            tree,
            "\n".join(warnings),
            f"{elapsed:.1f} ms",
        )

    def _show_static(
        self,
        token: int,
        matches: str,
        groups: str,
        explanation: str,
        tree: str,
        warnings: str,
        performance: str = "",
    ) -> None:
        if token != self._token and token != 0:
            return
        self.query_one("#matches", Static).update(matches)
        self.query_one("#groups", Static).update(groups)
        self.query_one("#explanation", Static).update(explanation)
        self.query_one("#tree", Static).update(tree)
        self.query_one("#warnings", Static).update(warnings)
        if performance:
            self.query_one("#performance", Static).update(performance)
