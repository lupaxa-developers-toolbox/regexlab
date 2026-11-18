"""TOML regex suites. Files are read with tomllib and never executed."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lupaxa.regexlab.engines import check_replacement, compile_pattern, iter_matches
from lupaxa.regexlab.errors import PatternProblem, UsageError
from lupaxa.regexlab.flagset import parse_flags
from lupaxa.regexlab.parser import parse_pattern

_TOP_KEYS = {
    "schema_version",
    "name",
    "engine",
    "pattern",
    "mode",
    "flags",
    "tests",
}
_CASE_KEYS = {
    "name",
    "input",
    "should_match",
    "span",
    "groups",
    "groupdict",
    "count",
    "replacement",
    "expected_replacement",
    "expected_split",
    "maxsplit",
    "pattern",
    "mode",
    "flags",
    "engine",
}


@dataclass
class SuiteCase:
    name: str
    text: str
    should_match: bool | None = None
    span: tuple[int, int] | None = None
    groups: list[str | None] | None = None
    groupdict: dict[str, str | None] | None = None
    count: int | None = None
    replacement: str | None = None
    expected_replacement: str | None = None
    expected_split: list[str | None] | None = None
    maxsplit: int = 0
    pattern: str | None = None
    mode: str | None = None
    flags: str | None = None
    engine: str | None = None


@dataclass
class Suite:
    name: str
    pattern: str
    engine: str
    mode: str
    flags: str
    schema_version: str = "1.0"
    tests: list[SuiteCase] = field(default_factory=list)
    path: Path | None = None


@dataclass
class CaseFailure:
    name: str
    message: str


@dataclass
class SuiteRun:
    passed: int
    failed: list[CaseFailure]

    @property
    def ok(self) -> bool:
        return not self.failed


def load_suite(path: Path) -> Suite:
    if not path.is_file():
        raise UsageError(f"suite not found: {path}")
    try:
        raw_text = path.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise UsageError(f"suite {path} is not UTF-8 text") from exc
    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError("suite root must be a TOML table")
    unknown = sorted(set(data) - _TOP_KEYS)
    if unknown:
        raise UsageError(f"unknown suite key: {', '.join(unknown)}")
    schema = str(data.get("schema_version", "1.0"))
    if schema != "1.0":
        raise UsageError(f"unsupported suite schema_version {schema!r}")
    for key in ("name", "pattern", "tests"):
        if key not in data:
            raise UsageError(f"suite is missing {key}")
    tests_raw = data["tests"]
    if not isinstance(tests_raw, list) or not tests_raw:
        raise UsageError("suite tests must be a non-empty array of tables")
    cases = [_case(item, index) for index, item in enumerate(tests_raw)]
    suite = Suite(
        name=str(data["name"]),
        pattern=str(data["pattern"]),
        engine=str(data.get("engine", "python-re")),
        mode=str(data.get("mode", "fullmatch")),
        flags=str(data.get("flags", "")),
        schema_version=schema,
        tests=cases,
        path=path,
    )
    return suite


def validate_suite(suite: Suite) -> list[str]:
    """Return warnings. Raise UsageError or PatternProblem when the suite is unusable."""

    warnings: list[str] = []
    flags = parse_flags(suite.flags, engine=suite.engine)
    parse_pattern(suite.pattern, suite.engine, flags)
    compile_pattern(suite.engine, suite.pattern, flags)
    for case in suite.tests:
        engine = case.engine or suite.engine
        pattern = case.pattern or suite.pattern
        flag_text = suite.flags if case.flags is None else case.flags
        case_flags = parse_flags(flag_text, engine=engine)
        parse_pattern(pattern, engine, case_flags)
        compile_pattern(engine, pattern, case_flags)
        if case.replacement is not None:
            check_replacement(engine, case.replacement)
            if case.expected_replacement is None:
                warnings.append(f"{case.name}: replacement has no expected_replacement")
    return warnings


def run_suite(suite: Suite) -> SuiteRun:
    failures: list[CaseFailure] = []
    passed = 0
    for case in suite.tests:
        problems = _run_case(suite, case)
        if problems:
            failures.extend(CaseFailure(case.name, item) for item in problems)
        else:
            passed += 1
    return SuiteRun(passed=passed, failed=failures)


def create_suite(
    path: Path,
    *,
    name: str,
    pattern: str,
    engine: str,
    mode: str,
    flags: str,
    force: bool,
) -> None:
    if path.exists() and not force:
        raise UsageError(f"{path} already exists. Pass --force to overwrite.")
    body = "\n".join(
        [
            'schema_version = "1.0"',
            f"name = {_toml_str(name)}",
            f"engine = {_toml_str(engine)}",
            f"pattern = {_toml_str(pattern)}",
            f"mode = {_toml_str(mode)}",
            f"flags = {_toml_str(flags)}",
            "",
            "[[tests]]",
            'name = "example"',
            f"input = {_toml_str('')}",
            "should_match = false",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def render_suite_run(result: SuiteRun) -> str:
    lines = [f"passed: {result.passed}", f"failed: {len(result.failed)}"]
    for item in result.failed:
        lines.append(f"FAIL {item.name}: {item.message}")
    return "\n".join(lines)


def _case(item: object, index: int) -> SuiteCase:
    if not isinstance(item, dict):
        raise UsageError(f"tests[{index}] must be a table")
    unknown = sorted(set(item) - _CASE_KEYS)
    if unknown:
        raise UsageError(f"tests[{index}] has unknown key: {', '.join(unknown)}")
    if "name" not in item or "input" not in item:
        raise UsageError(f"tests[{index}] needs name and input")
    span = None
    if "span" in item:
        raw_span = item["span"]
        if (
            not isinstance(raw_span, list)
            or len(raw_span) != 2
            or any(isinstance(part, bool) or not isinstance(part, int) for part in raw_span)
        ):
            raise UsageError(f"tests[{index}].span must be [start, end]")
        span = (int(raw_span[0]), int(raw_span[1]))
    groups = _string_list(item.get("groups"), index, "groups")
    expected_split = _string_list(item.get("expected_split"), index, "expected_split")
    groupdict = None
    if "groupdict" in item:
        raw_dict = item["groupdict"]
        if not isinstance(raw_dict, dict):
            raise UsageError(f"tests[{index}].groupdict must be a table")
        groupdict = {
            str(key): None if value is None else str(value) for key, value in raw_dict.items()
        }
    should = item.get("should_match")
    if should is not None and not isinstance(should, bool):
        raise UsageError(f"tests[{index}].should_match must be a boolean")
    count = item.get("count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int)):
        raise UsageError(f"tests[{index}].count must be an integer")
    maxsplit = item.get("maxsplit", 0)
    if isinstance(maxsplit, bool) or not isinstance(maxsplit, int):
        raise UsageError(f"tests[{index}].maxsplit must be an integer")
    return SuiteCase(
        name=str(item["name"]),
        text=str(item["input"]),
        should_match=should,
        span=span,
        groups=groups,
        groupdict=groupdict,
        count=None if count is None else int(count),
        replacement=None if item.get("replacement") is None else str(item["replacement"]),
        expected_replacement=(
            None if item.get("expected_replacement") is None else str(item["expected_replacement"])
        ),
        expected_split=expected_split,
        maxsplit=int(maxsplit),
        pattern=None if item.get("pattern") is None else str(item["pattern"]),
        mode=None if item.get("mode") is None else str(item["mode"]),
        flags=None if item.get("flags") is None else str(item["flags"]),
        engine=None if item.get("engine") is None else str(item["engine"]),
    )


def _string_list(value: object, index: int, key: str) -> list[str | None] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise UsageError(f"tests[{index}].{key} must be an array")
    out: list[str | None] = []
    for item in value:
        if item is None:
            out.append(None)
        else:
            out.append(str(item))
    return out


def _run_case(suite: Suite, case: SuiteCase) -> list[str]:
    engine = case.engine or suite.engine
    pattern = case.pattern or suite.pattern
    mode = case.mode or suite.mode
    flags = parse_flags(case.flags if case.flags is not None else suite.flags, engine=engine)
    problems: list[str] = []
    try:
        compiled = compile_pattern(engine, pattern, flags)
    except PatternProblem as exc:
        return [exc.explanation]
    if case.expected_split is not None or mode == "split":
        parts = compiled.split(case.text, case.maxsplit)
        if case.expected_split is not None and parts != case.expected_split:
            problems.append(f"split {parts!r} != {case.expected_split!r}")
        return problems
    if case.replacement is not None:
        check_replacement(engine, case.replacement)
        replaced = compiled.sub(case.replacement, case.text, 0)
        if case.expected_replacement is not None and replaced != case.expected_replacement:
            problems.append(f"replacement {replaced!r} != {case.expected_replacement!r}")
    matches, _truncated = iter_matches(compiled, case.text, mode, max_matches=1000)
    if case.should_match is True and not matches:
        problems.append("expected a match")
    if case.should_match is False and matches:
        problems.append("expected no match")
    if case.count is not None and len(matches) != case.count:
        problems.append(f"count {len(matches)} != {case.count}")
    if matches and case.span is not None:
        got = (matches[0].start, matches[0].end)
        if got != case.span:
            problems.append(f"span {got} != {case.span}")
    if matches and case.groups is not None and list(matches[0].groups) != case.groups:
        problems.append(f"groups {matches[0].groups!r} != {case.groups!r}")
    if matches and case.groupdict is not None and matches[0].groupdict != case.groupdict:
        problems.append(f"groupdict {matches[0].groupdict!r} != {case.groupdict!r}")
    return problems


def _toml_str(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
    )
    return f'"{escaped}"'


def suite_to_dict(suite: Suite) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    for case in suite.tests:
        item: dict[str, object] = {"name": case.name, "input": case.text}
        if case.should_match is not None:
            item["should_match"] = case.should_match
        if case.span is not None:
            item["span"] = [case.span[0], case.span[1]]
        if case.groups is not None:
            item["groups"] = case.groups
        if case.groupdict is not None:
            item["groupdict"] = case.groupdict
        if case.count is not None:
            item["count"] = case.count
        if case.replacement is not None:
            item["replacement"] = case.replacement
        if case.expected_replacement is not None:
            item["expected_replacement"] = case.expected_replacement
        if case.expected_split is not None:
            item["expected_split"] = case.expected_split
        if case.pattern is not None:
            item["pattern"] = case.pattern
        if case.mode is not None:
            item["mode"] = case.mode
        cases.append(item)
    return {
        "schema_version": suite.schema_version,
        "name": suite.name,
        "engine": suite.engine,
        "pattern": suite.pattern,
        "mode": suite.mode,
        "flags": suite.flags,
        "tests": cases,
    }


# Re-export for callers that want the invalid-regex exit on a bad suite pattern.
__all__ = [
    "Suite",
    "SuiteRun",
    "create_suite",
    "load_suite",
    "render_suite_run",
    "run_suite",
    "suite_to_dict",
    "validate_suite",
]
