"""Command-line interface for Regex Lab.

Every path returns an int. Usage errors raise :class:`UsageExit` instead of
calling ``sys.exit`` from argparse.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

from lupaxa.regexlab import __version__
from lupaxa.regexlab.analyse import analyse_pattern, lint_pattern
from lupaxa.regexlab.colour import colour_enabled
from lupaxa.regexlab.config import Settings, resolve_settings, settings_mapping
from lupaxa.regexlab.engines import escape_text, list_engines, require_engine
from lupaxa.regexlab.errors import (
    EXIT_DIFFERENCE,
    EXIT_INCOMPLETE,
    EXIT_LINT,
    EXIT_OK,
    EXIT_USAGE,
    PatternProblem,
    RegexLabError,
    UsageError,
    UsageExit,
)
from lupaxa.regexlab.explain import explain_text
from lupaxa.regexlab.export import export_suite
from lupaxa.regexlab.flagset import flag_catalogue, parse_flags
from lupaxa.regexlab.inputs import gather_subjects, read_pattern_file
from lupaxa.regexlab.library import (
    LibraryEntry,
    add_entry,
    find_entry,
    library_file,
    load_library,
    remove_entry,
    render_entries,
    search_entries,
)
from lupaxa.regexlab.matching import render_matches, render_split
from lupaxa.regexlab.parser import parse_pattern, render_tree
from lupaxa.regexlab.suite import (
    create_suite,
    load_suite,
    render_suite_run,
    run_suite,
    suite_to_dict,
    validate_suite,
)
from lupaxa.regexlab.visualise import visualise

COMMANDS = (
    "explain",
    "parse",
    "test",
    "interactive",
    "matches",
    "findall",
    "replace",
    "split",
    "generate",
    "compare",
    "analyse",
    "lint",
    "benchmark",
    "visualise",
    "escape",
    "suite",
    "library",
    "export",
    "engines",
    "flags",
    "config",
    "version",
)


@dataclass
class Outcome:
    code: int
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    pattern: str | None = None
    mode: str | None = None


class RegexParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self._print_message(f"error: {message}\n", sys.stderr)
        raise UsageExit(EXIT_USAGE)

    def exit(self, status: int = 0, message: str | None = None) -> NoReturn:
        if message:
            self._print_message(message, sys.stderr)
        raise UsageExit(int(status or 0))


def _mark(namespace: argparse.Namespace, dest: str) -> None:
    seen = getattr(namespace, "_explicit", None)
    if seen is None:
        seen = set()
        namespace._explicit = seen
    seen.add(dest)


class ExplicitStore(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, values)
        _mark(namespace, self.dest)


class ExplicitTrue(argparse.Action):
    def __init__(self, option_strings: list[str], dest: str, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        setattr(namespace, self.dest, True)
        _mark(namespace, self.dest)


class ExplicitAppend(argparse.Action):
    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        current = getattr(namespace, self.dest)
        items = list(current) if current else []
        items.append(values)
        setattr(namespace, self.dest, items)
        _mark(namespace, self.dest)


def build_parser() -> RegexParser:
    common = RegexParser(add_help=False)
    _add_common(common)
    parser = RegexParser(
        prog="regex-lab",
        description="Explain, test, generate, compare, and debug regular expressions.",
    )
    parser.add_argument("--version", action="store_true", help="Print regex-lab and the version.")
    sub = parser.add_subparsers(dest="command", parser_class=RegexParser)

    def add(name: str, help_text: str) -> RegexParser:
        return sub.add_parser(name, parents=[common], help=help_text)

    explain = add("explain", "Explain a pattern from its syntax tree.")
    explain.add_argument("pattern", nargs="?")
    parse = add("parse", "Print the syntax tree. The pattern is not executed.")
    parse.add_argument("pattern", nargs="?")
    test = add("test", "Test subjects. The default mode is fullmatch.")
    test.add_argument("pattern", nargs="?")
    test.add_argument("texts", nargs="*")
    test.add_argument("--expect", choices=("match", "nomatch"), default=None)
    interactive = add("interactive", "Open the terminal workbench.")
    interactive.add_argument("pattern", nargs="?")
    matches = add("matches", "Show matches, spans, and groups.")
    matches.add_argument("pattern", nargs="?")
    matches.add_argument("texts", nargs="*")
    findall = add("findall", "Find matches in strings, files, or directories.")
    findall.add_argument("pattern", nargs="?")
    findall.add_argument("texts", nargs="*")
    replace = add(
        "replace",
        "Preview a replacement. Files change only with --output or --in-place --yes.",
    )
    replace.add_argument("texts", nargs="*")
    split = add("split", "Split text and show segments and separators.")
    split.add_argument("pattern", nargs="?")
    split.add_argument("texts", nargs="*")
    generate = add("generate", "Generate examples and verify each one with the engine.")
    generate.add_argument("pattern", nargs="?")
    compare = add("compare", "Compare two patterns on samples. This does not prove equivalence.")
    compare.add_argument("pattern_a")
    compare.add_argument("pattern_b")
    compare.add_argument("texts", nargs="*")
    analyse = add("analyse", "Report structural risks. Heuristics are labelled heuristic.")
    analyse.add_argument("pattern", nargs="?")
    lint = add("lint", "Lint style and portability. --strict exits 10 on warnings.")
    lint.add_argument("pattern", nargs="?")
    benchmark = add("benchmark", "Time matches in a worker process.")
    benchmark.add_argument("pattern", nargs="?")
    benchmark.add_argument("texts", nargs="*")
    visual = add("visualise", "Draw the syntax tree as text, SVG, HTML, or Mermaid.")
    visual.add_argument("pattern", nargs="?")
    escape = add("escape", "Escape literal text for the selected engine.")
    escape.add_argument("texts", nargs="*")
    suite = add("suite", "Create, validate, run, list, and show TOML suites.")
    suite_sub = suite.add_subparsers(dest="suite_command", parser_class=RegexParser)
    created = suite_sub.add_parser("create", parents=[common], help="Write a suite file.")
    created.add_argument("path")
    created.add_argument("--name", required=True)
    created.add_argument("--pattern", required=True)
    validated = suite_sub.add_parser("validate", parents=[common], help="Check a suite file.")
    validated.add_argument("path")
    ran = suite_sub.add_parser("run", parents=[common], help="Run suite assertions.")
    ran.add_argument("path")
    listed = suite_sub.add_parser("list", parents=[common], help="List suites or tests.")
    listed.add_argument("path")
    showed = suite_sub.add_parser("show", parents=[common], help="Show a suite.")
    showed.add_argument("path")
    library = add("library", "Store named patterns in the user data directory.")
    lib_sub = library.add_subparsers(dest="library_command", parser_class=RegexParser)
    added = lib_sub.add_parser("add", parents=[common], help="Add a named pattern.")
    added.add_argument("name")
    added.add_argument("pattern")
    added.add_argument("--description", default="")
    lib_sub.add_parser("list", parents=[common], help="List saved patterns.")
    shown = lib_sub.add_parser("show", parents=[common], help="Show one pattern.")
    shown.add_argument("name")
    searched = lib_sub.add_parser(
        "search",
        parents=[common],
        help="Search names, patterns, and descriptions.",
    )
    searched.add_argument("query")
    removed = lib_sub.add_parser("remove", parents=[common], help="Remove a pattern by name.")
    removed.add_argument("name")
    lib_sub.add_parser("export", parents=[common], help="Write the library to a file.")
    export = add("export", "Export a suite to pytest, unittest, JSON, TOML, or text.")
    export.add_argument("path")
    add("engines", "List engines that are available or not installed.")
    add("flags", "List flag letters and what they change.")
    add("config", "Print the effective configuration.")
    add("version", "Print regex-lab and the version.")
    return parser


def _add_common(parser: RegexParser) -> None:
    parser.add_argument("--engine", action=ExplicitStore, default=None)
    parser.add_argument("--flags", action=ExplicitStore, default=None)
    parser.add_argument("--input", action=ExplicitAppend, default=None, dest="input")
    parser.add_argument("--pattern-file", action=ExplicitStore, default=None)
    parser.add_argument("--stdin", action=ExplicitTrue, default=None)
    parser.add_argument("--format", action=ExplicitStore, default=None)
    parser.add_argument("--output", action=ExplicitStore, default=None)
    parser.add_argument("--json", action=ExplicitTrue, default=None, dest="json")
    parser.add_argument("--quiet", action=ExplicitTrue, default=None)
    parser.add_argument("--verbose", action=ExplicitTrue, default=None)
    parser.add_argument("--no-colour", action=ExplicitTrue, default=None)
    parser.add_argument("--config", action=ExplicitStore, default=None)
    parser.add_argument("--encoding", action=ExplicitStore, default=None)
    parser.add_argument("--timeout", action=ExplicitStore, type=float, default=None)
    parser.add_argument("--max-matches", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--max-input-size", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--seed", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--strict", action=ExplicitTrue, default=None)
    parser.add_argument("--mode", action=ExplicitStore, default=None)
    parser.add_argument("--detail", action=ExplicitStore, default=None)
    parser.add_argument("--by-line", action=ExplicitTrue, default=None)
    parser.add_argument("--recursive", action=ExplicitTrue, default=None)
    parser.add_argument("--include", action=ExplicitAppend, default=None)
    parser.add_argument("--exclude", action=ExplicitAppend, default=None)
    parser.add_argument("--context", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--count", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--min-length", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--max-length", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--unique", action=ExplicitTrue, default=None)
    parser.add_argument("--include-invalid", action=ExplicitTrue, default=None)
    parser.add_argument("--replacement", action=ExplicitStore, default=None)
    parser.add_argument("--in-place", action=ExplicitTrue, default=None)
    parser.add_argument("--yes", action=ExplicitTrue, default=None)
    parser.add_argument("--force", action=ExplicitTrue, default=None)
    parser.add_argument("--iterations", action=ExplicitStore, type=int, default=None)
    parser.add_argument("--growth", action=ExplicitTrue, default=None)
    parser.add_argument("--fail-on-difference", action=ExplicitTrue, default=None)
    parser.add_argument(
        "--generate",
        action=ExplicitStore,
        type=int,
        default=None,
        dest="generate_count",
    )
    parser.add_argument("--library-dir", action=ExplicitStore, default=None)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageExit as exc:
        return exc.code
    settings: Settings | None = None
    try:
        if getattr(args, "version", False) and args.command in {None, "version"}:
            print(f"regex-lab {__version__}")
            return EXIT_OK
        if args.command is None:
            if sys.stdin.isatty() and sys.stdout.isatty():
                settings = resolve_settings(args)
                return _launch_interactive(settings, None)
            parser.print_help(sys.stderr)
            return EXIT_USAGE
        if args.command == "version":
            print(f"regex-lab {__version__}")
            return EXIT_OK
        settings = resolve_settings(args)
        outcome = _dispatch(args, settings)
        return _emit(args.command, settings, outcome)
    except UsageExit as exc:
        return exc.code
    except (UsageError, PatternProblem, RegexLabError) as exc:
        return _emit_error(args, settings, exc)


def _dispatch(args: argparse.Namespace, settings: Settings) -> Outcome:
    command = args.command
    if command == "explain":
        return _explain(args, settings)
    if command == "parse":
        return _parse(args, settings)
    if command in {"test", "matches", "findall"}:
        return _match_command(args, settings)
    if command == "replace":
        return _replace(args, settings)
    if command == "split":
        return _split(args, settings)
    if command == "generate":
        return _generate(args, settings)
    if command == "compare":
        return _compare(args, settings)
    if command == "analyse":
        return _findings(args, settings, kind="analyse")
    if command == "lint":
        return _findings(args, settings, kind="lint")
    if command == "benchmark":
        return _benchmark(args, settings)
    if command == "visualise":
        return _visualise(args, settings)
    if command == "escape":
        return _escape(args, settings)
    if command == "suite":
        return _suite(args, settings)
    if command == "library":
        return _library(args, settings)
    if command == "export":
        return _export(args, settings)
    if command == "engines":
        return _engines(settings)
    if command == "flags":
        return _flags(settings)
    if command == "config":
        return _config(settings)
    if command == "interactive":
        pattern = _optional_pattern(args, settings)
        code = _launch_interactive(settings, pattern)
        return Outcome(code, pattern=pattern, mode=settings.mode)
    raise UsageError(f"unknown command {command}")


def _explain(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    flags = parse_flags(settings.flags, engine=settings.engine)
    node = parse_pattern(pattern, settings.engine, flags)
    text = explain_text(node, engine=settings.engine, detail=settings.detail, flags=flags.letters())
    return Outcome(
        EXIT_OK,
        text,
        data={"explanation": text, "detail": settings.detail},
        pattern=pattern,
        mode=settings.mode,
    )


def _parse(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    flags = parse_flags(settings.flags, engine=settings.engine)
    node = parse_pattern(pattern, settings.engine, flags)
    text = render_tree(node)
    return Outcome(
        EXIT_OK,
        text,
        data={"tree": node.to_dict()},
        pattern=pattern,
        mode=None,
    )


def _match_command(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    mode = settings.resolved_mode(args.command)
    subjects = _subjects(args, settings)
    if not subjects:
        raise UsageError("input is required (arguments, --input, or --stdin)")
    message = _worker(
        "match",
        {
            "engine": settings.engine,
            "pattern": pattern,
            "flags": settings.flags,
            "mode": mode,
            "timeout": settings.timeout,
            "max_matches": settings.max_matches,
            "subjects": [(item.label, item.text) for item in subjects],
        },
        settings,
        scale=max(1, len(subjects)),
    )
    failed = _worker_failure(message)
    if failed is not None:
        failed.pattern = pattern
        failed.mode = mode
        return failed
    colour = colour_enabled(no_colour=settings.no_colour)
    blocks: list[str] = []
    failures: list[str] = []
    expect = getattr(args, "expect", None) or "match"
    for row in message["subjects"]:
        blocks.append(
            render_matches(
                row["label"],
                row["text"],
                _restore_matches(row["matches"]),
                engine=settings.engine,
                flags=settings.flags,
                mode=mode,
                colour=colour and not settings.json_output,
                context=settings.context,
                truncated=bool(row["truncated"]),
            )
        )
        matched = bool(row["matches"])
        ok = matched if expect == "match" else not matched
        if args.command == "test" and not ok:
            failures.append(row["label"])
    text = "\n\n".join(blocks)
    code = EXIT_OK
    if args.command == "test":
        if failures:
            text += "\nfail: " + ", ".join(failures)
            code = 1
        else:
            text += "\npass"
    return Outcome(
        code,
        text,
        data={"subjects": message["subjects"]},
        pattern=pattern,
        mode=mode,
    )


def _replace(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern, replacement, texts = _replace_operands(args, settings)
    if args.in_place and not args.yes:
        raise UsageError("--in-place modifies files. Pass --yes to confirm.")
    subjects = _subjects(args, settings, texts)
    if not subjects:
        raise UsageError("input is required")
    if args.in_place and not args.input:
        raise UsageError("--in-place needs --input files")
    message = _worker(
        "replace",
        {
            "engine": settings.engine,
            "pattern": pattern,
            "flags": settings.flags,
            "replacement": replacement,
            "timeout": settings.timeout,
            "count": settings.count or 0,
            "subjects": [(item.label, item.text) for item in subjects],
        },
        settings,
        scale=max(1, len(subjects)),
    )
    failed = _worker_failure(message)
    if failed is not None:
        failed.pattern = pattern
        return failed
    lines = [f"{row['label']}: {row['output']}" for row in message["results"]]
    if args.output:
        if len(message["results"]) != 1:
            raise UsageError("--output writes one result. Pass one input.")
        Path(args.output).write_text(message["results"][0]["output"], encoding=settings.encoding)
    elif args.in_place:
        paths = list(args.input or [])
        if len(paths) != len(message["results"]):
            raise UsageError("--in-place expects one result per input file")
        for path, row in zip(paths, message["results"], strict=True):
            Path(path).write_text(row["output"], encoding=settings.encoding)
    return Outcome(
        EXIT_OK,
        "\n".join(lines),
        data={"results": message["results"]},
        pattern=pattern,
        mode=settings.mode,
    )


def _split(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    subjects = _subjects(args, settings)
    if not subjects:
        raise UsageError("input is required")
    message = _worker(
        "split",
        {
            "engine": settings.engine,
            "pattern": pattern,
            "flags": settings.flags,
            "timeout": settings.timeout,
            "maxsplit": settings.count or 0,
            "subjects": [(item.label, item.text) for item in subjects],
        },
        settings,
        scale=max(1, len(subjects)),
    )
    failed = _worker_failure(message)
    if failed is not None:
        failed.pattern = pattern
        return failed
    blocks = [
        f"{row['label']}\n{render_split(row['segments'], row['separators'])}"
        for row in message["results"]
    ]
    return Outcome(
        EXIT_OK,
        "\n\n".join(blocks),
        data={"results": message["results"]},
        pattern=pattern,
        mode="split",
    )


def _generate(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    count = 5 if settings.count is None else settings.count
    if count < 1:
        raise UsageError("generate --count must be at least 1")
    mode = settings.resolved_mode("generate")
    message = _worker(
        "generate",
        {
            "engine": settings.engine,
            "pattern": pattern,
            "flags": settings.flags,
            "mode": mode,
            "timeout": max(settings.timeout * count, settings.timeout + 1),
            "count": count,
            "seed": settings.seed,
            "min_length": settings.min_length,
            "max_length": settings.max_length,
            "unique": settings.unique,
            "include_invalid": bool(args.include_invalid),
        },
        settings,
        scale=max(count, 1),
    )
    failed = _worker_failure(message)
    if failed is not None:
        failed.pattern = pattern
        failed.mode = mode
        return failed
    lines = [f"positive: {item}" for item in message["positives"]]
    for item in message["negatives"]:
        lines.append(f"negative: {item['category']}: {item['text']}")
    lines.extend(message.get("notes") or [])
    code = EXIT_INCOMPLETE if message.get("incomplete") else EXIT_OK
    return Outcome(
        code,
        "\n".join(lines),
        data={
            "positives": message["positives"],
            "negatives": message["negatives"],
            "incomplete": message.get("incomplete"),
        },
        pattern=pattern,
        mode=mode,
    )


def _compare(args: argparse.Namespace, settings: Settings) -> Outcome:
    samples = [item.text for item in _subjects(args, settings)]
    mode = settings.resolved_mode("compare")
    message = _worker(
        "compare",
        {
            "engine": settings.engine,
            "flags": settings.flags,
            "first": args.pattern_a,
            "second": args.pattern_b,
            "samples": samples,
            "mode": mode,
            "seed": settings.seed,
            "generate_count": int(args.generate_count or 0),
            "replacement": args.replacement,
            "max_length": settings.max_length,
            "min_length": settings.min_length,
            "timeout": settings.timeout * max(1, int(args.generate_count or 1)),
            "fail_on_difference": bool(args.fail_on_difference),
        },
        settings,
        scale=max(1, int(args.generate_count or 1)),
    )
    failed = _worker_failure(message)
    if failed is not None:
        failed.pattern = args.pattern_a
        failed.mode = mode
        return failed
    code = int(message.get("exit_code") or 0)
    if args.fail_on_difference and message.get("different"):
        code = EXIT_DIFFERENCE
    elif message.get("incomplete") and code == 0:
        code = EXIT_INCOMPLETE
    return Outcome(
        code,
        message.get("text") or "",
        data={
            "both": message.get("both"),
            "neither": message.get("neither"),
            "only_first": message.get("only_first"),
            "only_second": message.get("only_second"),
            "capture_diffs": message.get("capture_diffs"),
            "span_diffs": message.get("span_diffs"),
            "replacement_diffs": message.get("replacement_diffs"),
            "incomplete": message.get("incomplete"),
            "different": message.get("different"),
        },
        pattern=args.pattern_a,
        mode=mode,
    )


def _findings(args: argparse.Namespace, settings: Settings, *, kind: str) -> Outcome:
    pattern = _require_pattern(args, settings)
    flags = parse_flags(settings.flags, engine=settings.engine)
    if kind == "analyse":
        findings = analyse_pattern(pattern, engine=settings.engine, flags=flags)
    else:
        findings = lint_pattern(pattern, engine=settings.engine, flags=flags)
    lines = []
    for item in findings:
        tag = "heuristic" if item.heuristic else "check"
        lines.append(
            f"{item.severity} {item.id} [{item.start}:{item.end}] "
            f"({tag}, confidence {item.confidence:.2f})\n"
            f"  {item.explanation}\n"
            f"  evidence: {item.evidence}\n"
            f"  suggestion: {item.suggestion}"
        )
    text = "\n".join(lines) if lines else "no findings"
    code = EXIT_OK
    policy = any(item.severity in {"warning", "error"} for item in findings)
    if kind == "lint" and settings.strict and policy:
        code = EXIT_LINT
    return Outcome(
        code,
        text,
        data={"findings": [item.to_dict() for item in findings]},
        pattern=pattern,
        mode=None,
    )


def _benchmark(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    subjects = _subjects(args, settings)
    if subjects:
        text = "\n".join(item.text for item in subjects)
    elif args.growth:
        text = "a"
    else:
        raise UsageError("benchmark needs input, or --growth to synthesise sizes")
    mode = settings.resolved_mode("benchmark")
    scale = settings.iterations * (6 if args.growth else 1)
    message = _worker(
        "benchmark",
        {
            "engine": settings.engine,
            "pattern": pattern,
            "flags": settings.flags,
            "text": text,
            "mode": mode,
            "iterations": settings.iterations,
            "timeout": settings.timeout,
            "growth": bool(args.growth),
            "max_input_size": settings.max_input_size,
        },
        settings,
        scale=scale,
    )
    failed = _worker_failure(message)
    if failed is not None:
        failed.pattern = pattern
        failed.mode = mode
        return failed
    return Outcome(
        int(message.get("exit_code") or 0),
        message.get("text") or "",
        data={
            "compile_ms": message.get("compile_ms"),
            "avg_ms": message.get("avg_ms"),
            "median_ms": message.get("median_ms"),
            "min_ms": message.get("min_ms"),
            "max_ms": message.get("max_ms"),
            "match_count": message.get("match_count"),
            "timeouts": message.get("timeouts"),
            "growth": message.get("growth"),
        },
        pattern=pattern,
        mode=mode,
    )


def _visualise(args: argparse.Namespace, settings: Settings) -> Outcome:
    pattern = _require_pattern(args, settings)
    flags = parse_flags(settings.flags, engine=settings.engine)
    node = parse_pattern(pattern, settings.engine, flags)
    fmt = settings.format or "tree"
    text = visualise(node, pattern, fmt)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    return Outcome(EXIT_OK, text, data={"format": fmt}, pattern=pattern, mode=None)


def _escape(args: argparse.Namespace, settings: Settings) -> Outcome:
    require_engine(settings.engine)
    subjects = _subjects(args, settings)
    if not subjects:
        raise UsageError("text to escape is required")
    lines = [escape_text(settings.engine, item.text) for item in subjects]
    return Outcome(
        EXIT_OK,
        "\n".join(lines),
        data={"escaped": lines},
        pattern=None,
        mode=None,
    )


def _suite(args: argparse.Namespace, settings: Settings) -> Outcome:
    action = args.suite_command
    if not action:
        raise UsageError("usage: regex-lab suite {create,validate,run,list,show}")
    if action == "create":
        create_suite(
            Path(args.path),
            name=args.name,
            pattern=args.pattern,
            engine=settings.engine,
            mode=settings.mode,
            flags=settings.flags,
            force=bool(args.force),
        )
        return Outcome(EXIT_OK, f"wrote {args.path}", pattern=args.pattern, mode=settings.mode)
    suite = load_suite(Path(args.path))
    if action == "validate":
        warnings = validate_suite(suite)
        return Outcome(
            EXIT_OK,
            f"valid {suite.name}",
            warnings=warnings,
            pattern=suite.pattern,
            mode=suite.mode,
        )
    if action == "run":
        from lupaxa.regexlab.isolate import _Alarm, arm, disarm

        arm(settings.timeout * max(1, len(suite.tests)))
        try:
            result = run_suite(suite)
        except _Alarm:
            return Outcome(
                5,
                error={
                    "type": "timeout",
                    "message": "suite exceeded the timeout",
                    "position": None,
                    "fragment": suite.pattern[:40],
                    "explanation": "The suite was stopped because it exceeded --timeout.",
                },
                pattern=suite.pattern,
                mode=suite.mode,
            )
        finally:
            disarm()
        code = EXIT_OK if result.ok else 4
        return Outcome(
            code,
            render_suite_run(result),
            data={"passed": result.passed, "failed": [item.__dict__ for item in result.failed]},
            pattern=suite.pattern,
            mode=suite.mode,
        )
    if action == "list":
        path = Path(args.path)
        if path.is_dir():
            names = sorted(item.name for item in path.glob("*.toml"))
            return Outcome(EXIT_OK, "\n".join(names) or "no suites", mode=None)
        names = [case.name for case in suite.tests]
        return Outcome(EXIT_OK, "\n".join(names), pattern=suite.pattern, mode=suite.mode)
    shown = suite_to_dict(suite)
    lines = [
        f"name: {suite.name}",
        f"engine: {suite.engine}",
        f"mode: {suite.mode}",
        f"pattern: {suite.pattern}",
    ]
    for case in suite.tests:
        lines.append(f"test: {case.name} should_match={case.should_match}")
    return Outcome(EXIT_OK, "\n".join(lines), data=shown, pattern=suite.pattern, mode=suite.mode)


def _library(args: argparse.Namespace, settings: Settings) -> Outcome:
    action = args.library_command
    directory = settings.library_dir
    if not action:
        raise UsageError("usage: regex-lab library {add,list,show,search,remove,export}")
    if action == "add":
        add_entry(
            directory,
            LibraryEntry(
                name=args.name,
                pattern=args.pattern,
                engine=settings.engine,
                flags=settings.flags,
                mode=settings.mode,
                description=args.description or "",
            ),
            force=bool(args.force),
        )
        return Outcome(EXIT_OK, f"added {args.name}", pattern=args.pattern, mode=settings.mode)
    if action == "list":
        entries = load_library(directory)
        rows = [item.__dict__ for item in entries]
        return Outcome(EXIT_OK, render_entries(entries), data={"patterns": rows})
    if action == "show":
        entry = find_entry(directory, args.name)
        return Outcome(
            EXIT_OK,
            render_entries([entry]),
            data={"pattern": entry.__dict__},
            pattern=entry.pattern,
            mode=entry.mode,
        )
    if action == "search":
        entries = search_entries(directory, args.query)
        rows = [item.__dict__ for item in entries]
        return Outcome(EXIT_OK, render_entries(entries), data={"patterns": rows})
    if action == "remove":
        remove_entry(directory, args.name)
        return Outcome(EXIT_OK, f"removed {args.name}")
    fmt = settings.format or "toml"
    path = library_file(directory)
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if fmt == "json":
        rows = [item.__dict__ for item in load_library(directory)]
        text = json.dumps(rows, ensure_ascii=False, indent=2)
    if args.output:
        if Path(args.output).exists() and not args.force:
            raise UsageError(f"{args.output} already exists. Pass --force to overwrite.")
        Path(args.output).write_text(text, encoding="utf-8")
    return Outcome(EXIT_OK, text, data={"format": fmt})


def _export(args: argparse.Namespace, settings: Settings) -> Outcome:
    suite = load_suite(Path(args.path))
    fmt = settings.format or "pytest"
    output = Path(args.output) if args.output else None
    text = export_suite(suite, fmt, output, force=bool(args.force))
    return Outcome(EXIT_OK, text, data={"format": fmt}, pattern=suite.pattern, mode=suite.mode)


def _engines(settings: Settings) -> Outcome:
    rows = list_engines()
    lines = ["Available regex engines:", ""]
    width = max(len(row.name) for row in rows)
    for index, row in enumerate(rows):
        if row.available:
            status = "Available (default)" if index == 0 else "Available"
        else:
            status = "Not installed"
        lines.append(f"  {row.name.ljust(width)}  {status}")
        if row.install:
            lines.append(f"    {row.install}")
    return Outcome(
        EXIT_OK,
        "\n".join(lines),
        data={
            "engines": [
                {
                    "name": row.name,
                    "available": row.available,
                    "install": row.install,
                    "detail": row.detail,
                }
                for row in rows
            ]
        },
        mode=None,
    )


def _flags(settings: Settings) -> Outcome:
    rows = flag_catalogue()
    lines = [f"{row['letter']}  {row['name']}  {row['engines']}  {row['meaning']}" for row in rows]
    return Outcome(EXIT_OK, "\n".join(lines), data={"flags": rows}, mode=None, pattern=None)


def _config(settings: Settings) -> Outcome:
    mapping = settings_mapping(settings)
    lines = [f"{key}: {value}" for key, value in mapping.items()]
    return Outcome(
        EXIT_OK,
        "\n".join(lines),
        data={"config": mapping},
        warnings=list(settings.warnings),
        mode=settings.mode,
    )


def _launch_interactive(settings: Settings, pattern: str | None) -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("error: interactive mode requires a TTY", file=sys.stderr)
        return EXIT_USAGE
    from lupaxa.regexlab.interactive import RegexLabApp

    RegexLabApp(settings=settings, pattern=pattern or "").run()
    return EXIT_OK


def _worker(
    op: str,
    payload: dict[str, Any],
    settings: Settings,
    *,
    scale: float,
) -> dict[str, Any]:
    import lupaxa.regexlab.ops  # noqa: F401
    from lupaxa.regexlab.isolate import run

    watchdog = max(settings.timeout * scale + 0.75, settings.timeout + 0.5)
    return run(op, payload, timeout=watchdog, method="fork")


def _worker_failure(message: dict[str, Any]) -> Outcome | None:
    if message.get("status") == "ok" and int(message.get("exit_code") or 0) in {0, 8, 9}:
        return None
    if message.get("status") == "timeout" or message.get("exit_code") == 5:
        return Outcome(5, error=message.get("error"))
    if message.get("status") == "error" or message.get("error"):
        return Outcome(int(message.get("exit_code") or 1), error=message.get("error"))
    return None


def _restore_matches(rows: list[dict[str, Any]]) -> list[Any]:
    from lupaxa.regexlab.engines import MatchInfo

    return [
        MatchInfo(
            text=row["text"],
            start=row["start"],
            end=row["end"],
            groups=list(row["groups"]),
            groupdict=dict(row["groupdict"]),
        )
        for row in rows
    ]


def _subjects(
    args: argparse.Namespace,
    settings: Settings,
    texts: list[str] | None = None,
) -> list[Any]:
    source = texts if texts is not None else list(getattr(args, "texts", None) or [])
    return gather_subjects(
        settings,
        source,
        list(args.input) if getattr(args, "input", None) else None,
        use_stdin=bool(args.stdin),
        recursive=bool(args.recursive),
        include=list(args.include) if args.include else None,
        exclude=list(args.exclude) if args.exclude else None,
        by_line=settings.by_line,
    )


def _require_pattern(args: argparse.Namespace, settings: Settings) -> str:
    pattern = _optional_pattern(args, settings)
    if pattern is None:
        raise UsageError("a pattern is required (argument or --pattern-file)")
    return pattern


def _optional_pattern(args: argparse.Namespace, settings: Settings) -> str | None:
    if getattr(args, "pattern_file", None):
        return read_pattern_file(Path(args.pattern_file), settings)
    pattern = getattr(args, "pattern", None)
    if pattern:
        return str(pattern)
    return None


def _replace_operands(args: argparse.Namespace, settings: Settings) -> tuple[str, str, list[str]]:
    operands = list(args.texts or [])
    replacement = args.replacement
    if args.pattern_file:
        pattern = read_pattern_file(Path(args.pattern_file), settings)
        if replacement is None:
            if not operands:
                raise UsageError("a replacement is required")
            replacement = operands.pop(0)
        return pattern, str(replacement), operands
    if replacement is not None:
        if not operands:
            raise UsageError("a pattern is required")
        return operands[0], str(replacement), operands[1:]
    if len(operands) < 2:
        raise UsageError("usage: regex-lab replace PATTERN REPLACEMENT [TEXT ...]")
    return operands[0], operands[1], operands[2:]


def _emit(command: str, settings: Settings, outcome: Outcome) -> int:
    for warning in outcome.warnings:
        if warning not in settings.warnings:
            settings.warnings.append(warning)
    if settings.json_output:
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "ok": outcome.code == 0,
            "command": command,
            "engine": settings.engine,
            "pattern": outcome.pattern,
            "flags": settings.flags,
            "mode": outcome.mode,
            "error": outcome.error,
            "warnings": [{"message": item} for item in settings.warnings],
        }
        payload.update(outcome.data)
        payload["error"] = outcome.error
        payload["warnings"] = [{"message": item} for item in settings.warnings]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return outcome.code
    if outcome.text:
        print(outcome.text)
    for warning in settings.warnings:
        if not settings.quiet:
            print(f"warning: {warning}", file=sys.stderr)
    if outcome.error:
        _print_error(outcome.error)
    return outcome.code


def _emit_error(args: argparse.Namespace, settings: Settings | None, exc: RegexLabError) -> int:
    error = (
        exc.as_dict()
        if isinstance(exc, PatternProblem)
        else {
            "type": exc.kind,
            "message": str(exc),
            "position": None,
            "fragment": None,
            "explanation": str(exc),
        }
    )
    wants_json = bool(getattr(args, "json", False))
    if wants_json:
        engine = "python-re"
        if settings is not None:
            engine = settings.engine
        elif getattr(args, "engine", None):
            engine = args.engine
        flags = settings.flags if settings is not None else (getattr(args, "flags", None) or "")
        payload: dict[str, Any] = {
            "schema_version": "1.0",
            "ok": False,
            "command": getattr(args, "command", None),
            "engine": engine,
            "pattern": getattr(args, "pattern", None),
            "flags": flags,
            "mode": settings.mode if settings is not None else None,
            "error": error,
            "warnings": [],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_error(error)
    return exc.exit_code


def _print_error(error: dict[str, Any]) -> None:
    print(f"error: {error.get('explanation') or error.get('message')}", file=sys.stderr)
    if error.get("position") is not None:
        print(f"  position: {error['position']}", file=sys.stderr)
        print(f"  fragment: {error.get('fragment')}", file=sys.stderr)
