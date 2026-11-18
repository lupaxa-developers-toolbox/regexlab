"""Worker operations. Importing this module registers them with the isolator."""

from __future__ import annotations

from typing import Any

from lupaxa.regexlab.benchmark import render_benchmark, run_benchmark
from lupaxa.regexlab.compare import compare_patterns, render_compare
from lupaxa.regexlab.engines import check_replacement, compile_pattern, iter_matches
from lupaxa.regexlab.errors import EXIT_OK, IncompleteError, PatternProblem, UnsupportedError
from lupaxa.regexlab.flagset import parse_flags
from lupaxa.regexlab.generate import generate_samples
from lupaxa.regexlab.isolate import OPS, _Alarm, arm, disarm


def _flags(payload: dict[str, Any]) -> Any:
    return parse_flags(payload.get("flags") or "", engine=payload["engine"])


def _match_dict(item: Any) -> dict[str, Any]:
    return {
        "text": item.text,
        "start": item.start,
        "end": item.end,
        "groups": item.groups,
        "groupdict": item.groupdict,
    }


def op_match(payload: dict[str, Any]) -> dict[str, Any]:
    flags = _flags(payload)
    compiled = compile_pattern(payload["engine"], payload["pattern"], flags)
    subjects = []
    arm(float(payload.get("timeout") or 1))
    try:
        for label, text in payload["subjects"]:
            matches, truncated = iter_matches(
                compiled,
                text,
                payload["mode"],
                max_matches=int(payload["max_matches"]),
            )
            subjects.append(
                {
                    "label": label,
                    "text": text,
                    "matches": [_match_dict(item) for item in matches],
                    "truncated": truncated,
                }
            )
    except _Alarm:
        return {
            "status": "timeout",
            "exit_code": 5,
            "error": {
                "type": "timeout",
                "message": "matching exceeded the timeout",
                "position": None,
                "fragment": payload["pattern"][:40],
                "explanation": "The match was stopped because it exceeded --timeout.",
            },
        }
    finally:
        disarm()
    return {"status": "ok", "exit_code": EXIT_OK, "subjects": subjects}


def op_replace(payload: dict[str, Any]) -> dict[str, Any]:
    flags = _flags(payload)
    check_replacement(payload["engine"], payload["replacement"])
    compiled = compile_pattern(payload["engine"], payload["pattern"], flags)
    count = int(payload.get("count") or 0)
    results = []
    arm(float(payload.get("timeout") or 1))
    try:
        for label, text in payload["subjects"]:
            replaced = compiled.sub(payload["replacement"], text, count)
            results.append({"label": label, "input": text, "output": replaced})
    except _Alarm:
        return _timeout_payload("replace", payload["pattern"])
    finally:
        disarm()
    return {"status": "ok", "exit_code": EXIT_OK, "results": results}


def op_split(payload: dict[str, Any]) -> dict[str, Any]:
    flags = _flags(payload)
    compiled = compile_pattern(payload["engine"], payload["pattern"], flags)
    maxsplit = int(payload.get("maxsplit") or 0)
    results = []
    arm(float(payload.get("timeout") or 1))
    try:
        for label, text in payload["subjects"]:
            matches, _truncated = iter_matches(
                compiled,
                text,
                "finditer",
                max_matches=maxsplit or 10000,
            )
            if maxsplit:
                matches = matches[:maxsplit]
            segments: list[str] = []
            separators: list[str] = []
            cursor = 0
            for item in matches:
                segments.append(text[cursor : item.start])
                separators.append(item.text)
                cursor = item.end
            segments.append(text[cursor:])
            results.append(
                {
                    "label": label,
                    "segments": segments,
                    "separators": separators,
                }
            )
    except _Alarm:
        return _timeout_payload("split", payload["pattern"])
    finally:
        disarm()
    return {"status": "ok", "exit_code": EXIT_OK, "results": results}


def op_generate(payload: dict[str, Any]) -> dict[str, Any]:
    flags = _flags(payload)
    arm(float(payload.get("timeout") or 1))
    try:
        report = generate_samples(
            payload["pattern"],
            engine=payload["engine"],
            flags=flags,
            mode=payload["mode"],
            count=int(payload["count"]),
            seed=int(payload["seed"]),
            min_length=int(payload["min_length"]),
            max_length=int(payload["max_length"]),
            unique=bool(payload["unique"]),
            include_invalid=bool(payload["include_invalid"]),
        )
    except _Alarm:
        return _timeout_payload("generate", payload["pattern"])
    except (UnsupportedError, IncompleteError, PatternProblem):
        raise
    finally:
        disarm()
    code = 8 if report.incomplete else 0
    return {
        "status": "ok",
        "exit_code": code,
        "positives": report.positives,
        "negatives": [{"text": item.text, "category": item.category} for item in report.negatives],
        "notes": report.notes,
        "incomplete": report.incomplete,
    }


def op_compare(payload: dict[str, Any]) -> dict[str, Any]:
    flags = _flags(payload)
    arm(float(payload.get("timeout") or 1))
    try:
        report = compare_patterns(
            payload["first"],
            payload["second"],
            list(payload.get("samples") or []),
            engine=payload["engine"],
            flags=flags,
            mode=payload["mode"],
            seed=int(payload["seed"]),
            generate_count=int(payload.get("generate_count") or 0),
            replacement=payload.get("replacement"),
            max_length=int(payload["max_length"]),
            min_length=int(payload["min_length"]),
        )
    except _Alarm:
        return _timeout_payload("compare", payload["first"])
    finally:
        disarm()
    code = 0
    if report.incomplete and not report.samples:
        code = 8
    elif payload.get("fail_on_difference") and report.different:
        code = 9
    elif report.incomplete:
        code = 8
    return {
        "status": "ok",
        "exit_code": code,
        "text": render_compare(report),
        "incomplete": report.incomplete,
        "different": report.different,
        "both": report.both,
        "neither": report.neither,
        "only_first": report.only_first,
        "only_second": report.only_second,
        "capture_diffs": report.capture_diffs,
        "span_diffs": report.span_diffs,
        "replacement_diffs": report.replacement_diffs,
        "notes": report.notes,
    }


def op_benchmark(payload: dict[str, Any]) -> dict[str, Any]:
    flags = _flags(payload)
    report = run_benchmark(
        payload["pattern"],
        payload["text"],
        engine=payload["engine"],
        flags=flags,
        mode=payload["mode"],
        iterations=int(payload["iterations"]),
        timeout=float(payload["timeout"]),
        growth=bool(payload.get("growth")),
        max_input_size=int(payload["max_input_size"]),
    )
    code = 5 if report.timeouts and report.avg_ms is None else 0
    return {
        "status": "ok" if code == 0 else "timeout",
        "exit_code": code,
        "text": render_benchmark(report),
        "compile_ms": report.compile_ms,
        "iterations": report.iterations,
        "avg_ms": report.avg_ms,
        "median_ms": report.median_ms,
        "min_ms": report.min_ms,
        "max_ms": report.max_ms,
        "match_count": report.match_count,
        "timeouts": report.timeouts,
        "growth": [
            {"size": row.size, "status": row.status, "avg_ms": row.avg_ms} for row in report.growth
        ],
    }


def _timeout_payload(op: str, pattern: str) -> dict[str, Any]:
    return {
        "status": "timeout",
        "exit_code": 5,
        "error": {
            "type": "timeout",
            "message": f"{op} exceeded the timeout",
            "position": None,
            "fragment": pattern[:40],
            "explanation": "The worker stopped the operation because it exceeded --timeout.",
        },
    }


OPS["match"] = op_match
OPS["replace"] = op_replace
OPS["split"] = op_split
OPS["generate"] = op_generate
OPS["compare"] = op_compare
OPS["benchmark"] = op_benchmark
