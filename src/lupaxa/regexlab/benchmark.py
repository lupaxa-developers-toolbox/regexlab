"""Benchmarks in the caller process. The CLI runs this inside a worker."""

from __future__ import annotations

import signal
import statistics
import time
from dataclasses import dataclass, field

from lupaxa.regexlab.engines import compile_pattern, iter_matches
from lupaxa.regexlab.flagset import FlagSet


class _Alarm(Exception):
    pass


def _handle_alarm(_signum: int, _frame: object) -> None:
    raise _Alarm()


@dataclass
class GrowthRow:
    size: int
    status: str
    avg_ms: float | None


@dataclass
class BenchmarkReport:
    compile_ms: float
    iterations: int
    avg_ms: float | None
    median_ms: float | None
    min_ms: float | None
    max_ms: float | None
    match_count: int
    timeouts: int
    growth: list[GrowthRow] = field(default_factory=list)


def run_benchmark(
    pattern: str,
    text: str,
    *,
    engine: str,
    flags: FlagSet,
    mode: str,
    iterations: int,
    timeout: float,
    growth: bool,
    max_input_size: int,
) -> BenchmarkReport:
    started = time.perf_counter()
    compiled = compile_pattern(engine, pattern, flags)
    compile_ms = (time.perf_counter() - started) * 1000
    timings: list[float] = []
    timeouts = 0
    match_count = 0
    for _ in range(iterations):
        elapsed, status, count = _once(compiled, text, mode, timeout)
        if status == "timeout":
            timeouts += 1
            continue
        timings.append(elapsed)
        match_count = count
    rows: list[GrowthRow] = []
    if growth:
        for size in (10, 100, 1000, 10000):
            if size > max_input_size:
                break
            sample = _sized(text, size)
            samples: list[float] = []
            row_timeouts = 0
            for _ in range(min(iterations, 5)):
                elapsed, status, _count = _once(compiled, sample, mode, timeout)
                if status == "timeout":
                    row_timeouts += 1
                else:
                    samples.append(elapsed)
            if row_timeouts and not samples:
                rows.append(GrowthRow(size, "timeout", None))
            elif samples:
                rows.append(GrowthRow(size, "ok", statistics.fmean(samples)))
            else:
                rows.append(GrowthRow(size, "empty", None))
    return BenchmarkReport(
        compile_ms=compile_ms,
        iterations=iterations,
        avg_ms=statistics.fmean(timings) if timings else None,
        median_ms=statistics.median(timings) if timings else None,
        min_ms=min(timings) if timings else None,
        max_ms=max(timings) if timings else None,
        match_count=match_count,
        timeouts=timeouts,
        growth=rows,
    )


def render_benchmark(report: BenchmarkReport) -> str:
    def num(value: float | None) -> str:
        return "null" if value is None else f"{value:.4f}"

    lines = [
        f"compile_ms: {report.compile_ms:.4f}",
        f"iterations: {report.iterations}",
        f"avg_ms: {num(report.avg_ms)}",
        f"median_ms: {num(report.median_ms)}",
        f"min_ms: {num(report.min_ms)}",
        f"max_ms: {num(report.max_ms)}",
        f"match_count: {report.match_count}",
        f"timeouts: {report.timeouts}",
    ]
    if report.growth:
        lines.append("growth:")
        lines.append("size  avg_ms  status")
        for row in report.growth:
            avg = "null" if row.avg_ms is None else f"{row.avg_ms:.4f}"
            lines.append(f"{row.size}  {avg}  {row.status}")
    return "\n".join(lines)


def _once(compiled: object, text: str, mode: str, timeout: float) -> tuple[float, str, int]:
    def invoke() -> tuple[float, int]:
        started = time.perf_counter()
        matches, _truncated = iter_matches(compiled, text, mode, max_matches=1000)  # type: ignore[arg-type]
        return (time.perf_counter() - started) * 1000, len(matches)

    if timeout > 0 and hasattr(signal, "setitimer"):
        previous = signal.signal(signal.SIGALRM, _handle_alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            elapsed, count = invoke()
        except _Alarm:
            return 0.0, "timeout", 0
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)
        return elapsed, "ok", count
    elapsed, count = invoke()
    return elapsed, "ok", count


def _sized(base: str, size: int) -> str:
    unit = base or "a"
    repeats = (size // len(unit)) + 1
    return (unit * repeats)[:size]
