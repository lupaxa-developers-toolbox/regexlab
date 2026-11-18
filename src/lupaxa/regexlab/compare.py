"""Sample-based comparison. Sampling never proves two patterns are equivalent."""

from __future__ import annotations

from dataclasses import dataclass, field

from lupaxa.regexlab.engines import (
    Compiled,
    MatchInfo,
    check_replacement,
    compile_pattern,
    iter_matches,
)
from lupaxa.regexlab.errors import IncompleteError, UnsupportedError
from lupaxa.regexlab.flagset import FlagSet
from lupaxa.regexlab.generate import generate_samples

DISCLAIMER = "Sample comparison only. This does not prove the patterns are equivalent."


@dataclass
class CompareReport:
    both: list[str] = field(default_factory=list)
    neither: list[str] = field(default_factory=list)
    only_first: list[str] = field(default_factory=list)
    only_second: list[str] = field(default_factory=list)
    capture_diffs: list[str] = field(default_factory=list)
    span_diffs: list[str] = field(default_factory=list)
    replacement_diffs: list[str] = field(default_factory=list)
    incomplete: bool = False
    notes: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)

    @property
    def different(self) -> bool:
        return bool(
            self.only_first
            or self.only_second
            or self.capture_diffs
            or self.span_diffs
            or self.replacement_diffs
        )


def compare_patterns(
    first: str,
    second: str,
    samples: list[str],
    *,
    engine: str,
    flags: FlagSet,
    mode: str,
    seed: int,
    generate_count: int,
    replacement: str | None,
    max_length: int,
    min_length: int,
) -> CompareReport:
    report = CompareReport()
    gathered = list(samples)
    if generate_count > 0:
        try:
            generated = generate_samples(
                first,
                engine=engine,
                flags=flags,
                mode=mode,
                count=generate_count,
                seed=seed,
                min_length=min_length,
                max_length=max_length,
                unique=True,
                include_invalid=False,
            )
        except UnsupportedError as exc:
            report.incomplete = True
            report.notes.append(str(exc))
        except IncompleteError as exc:
            report.incomplete = True
            report.notes.append(str(exc))
        else:
            gathered.extend(generated.positives)
            if generated.incomplete:
                report.incomplete = True
                report.notes.extend(generated.notes)
    if not gathered:
        report.incomplete = True
        report.notes.append("No samples were available to compare.")
        return report
    if replacement is not None:
        check_replacement(engine, replacement)
    left = compile_pattern(engine, first, flags)
    right = compile_pattern(engine, second, flags)
    report.samples = gathered
    for sample in gathered:
        _classify(report, left, right, sample, mode, replacement)
    report.notes.append(DISCLAIMER)
    return report


def _classify(
    report: CompareReport,
    left: Compiled,
    right: Compiled,
    sample: str,
    mode: str,
    replacement: str | None,
) -> None:
    left_matches, _ = iter_matches(left, sample, mode, max_matches=20)
    right_matches, _ = iter_matches(right, sample, mode, max_matches=20)
    if left_matches and right_matches:
        report.both.append(sample)
        if _captures_differ(left_matches[0], right_matches[0]):
            report.capture_diffs.append(sample)
        if (left_matches[0].start, left_matches[0].end) != (
            right_matches[0].start,
            right_matches[0].end,
        ):
            report.span_diffs.append(sample)
        if replacement is not None:
            replaced_left = left.sub(replacement, sample, 0)
            replaced_right = right.sub(replacement, sample, 0)
            if replaced_left != replaced_right:
                report.replacement_diffs.append(sample)
        return
    if left_matches:
        report.only_first.append(sample)
        return
    if right_matches:
        report.only_second.append(sample)
        return
    report.neither.append(sample)


def _captures_differ(left: MatchInfo, right: MatchInfo) -> bool:
    return left.groups != right.groups or left.groupdict != right.groupdict


def render_compare(report: CompareReport) -> str:
    lines = [
        f"both: {len(report.both)}",
        f"neither: {len(report.neither)}",
        f"only first: {len(report.only_first)}",
        f"only second: {len(report.only_second)}",
        f"capture diffs: {len(report.capture_diffs)}",
        f"span diffs: {len(report.span_diffs)}",
        f"replacement diffs: {len(report.replacement_diffs)}",
    ]
    if report.incomplete:
        lines.append("incomplete: yes")
    for note in report.notes:
        lines.append(note)
    return "\n".join(lines)
