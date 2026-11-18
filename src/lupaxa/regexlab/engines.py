"""Engine adapters. Optional engines are detected at runtime and never substituted."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lupaxa.regexlab.errors import EXIT_INVALID, PatternProblem, UnsupportedError
from lupaxa.regexlab.flagset import FlagSet

ENGINE_NAMES = ("python-re", "python-regex", "pcre2")

_INSTALL = {
    "python-re": None,
    "python-regex": "pip install 'lupaxa-regexlab[regex]'",
    "pcre2": "pip install 'lupaxa-regexlab[pcre2]'",
}


@dataclass
class EngineInfo:
    name: str
    available: bool
    detail: str
    install: str | None


@dataclass
class MatchInfo:
    text: str
    start: int
    end: int
    groups: list[str | None]
    groupdict: dict[str, str | None]


@dataclass
class Compiled:
    engine: str
    pattern: str
    flags: FlagSet
    raw: Any
    groupindex: dict[str, int] = field(default_factory=dict)
    groups: int = 0

    def search(self, text: str, pos: int = 0) -> MatchInfo | None:
        return _normalise(self.raw.search(text, pos), text)

    def match(self, text: str) -> MatchInfo | None:
        return _normalise(self.raw.match(text), text)

    def fullmatch(self, text: str) -> MatchInfo | None:
        fn = getattr(self.raw, "fullmatch", None)
        if fn is not None:
            return _normalise(fn(text), text)
        found = self.search(text, 0)
        if found is not None and found.start == 0 and found.end == len(text):
            return found
        return None

    def sub(self, repl: str, text: str, count: int = 0) -> str:
        try:
            result = self.raw.sub(repl, text, count=count)
        except (re.error, IndexError, ValueError) as exc:
            raise PatternProblem(
                str(exc),
                kind="bad_replacement",
                position=None,
                fragment=repl[:40],
                explanation=f"The replacement template was rejected by {self.engine}: {exc}",
                exit_code=EXIT_INVALID,
            ) from exc
        if isinstance(result, bytes):
            return result.decode("utf-8", "replace")
        return str(result)

    def split(self, text: str, maxsplit: int = 0) -> list[str]:
        try:
            parts = self.raw.split(text, maxsplit=maxsplit)
        except (re.error, ValueError) as exc:
            raise PatternProblem(
                str(exc),
                kind="bad_split",
                position=None,
                fragment=self.pattern[:40],
                explanation=f"{self.engine} rejected the split: {exc}",
            ) from exc
        out: list[str] = []
        for part in parts:
            if isinstance(part, bytes):
                out.append(part.decode("utf-8", "replace"))
            elif part is None:
                out.append("")
            else:
                out.append(str(part))
        return out


def list_engines() -> list[EngineInfo]:
    return [
        EngineInfo("python-re", True, "Python standard library re", None),
        EngineInfo(
            "python-regex",
            _importable("regex"),
            "PyPI package regex",
            None if _importable("regex") else _INSTALL["python-regex"],
        ),
        EngineInfo(
            "pcre2",
            _pcre2_available(),
            "PCRE2 via python-pcre2",
            None if _pcre2_available() else _INSTALL["pcre2"],
        ),
    ]


def require_engine(name: str) -> EngineInfo:
    for info in list_engines():
        if info.name == name:
            if not info.available:
                hint = info.install or "install the optional extra"
                raise UnsupportedError(
                    f"engine {name} is not installed. {hint}. "
                    "Regex Lab will not substitute another engine."
                )
            return info
    raise UnsupportedError(f"unknown engine {name}")


def compile_pattern(engine: str, pattern: str, flags: FlagSet) -> Compiled:
    require_engine(engine)
    if engine == "python-re":
        return _compile_re(pattern, flags)
    if engine == "python-regex":
        return _compile_regex(pattern, flags)
    if engine == "pcre2":
        return _compile_pcre2(pattern, flags)
    raise UnsupportedError(f"unknown engine {engine}")


def escape_text(engine: str, text: str) -> str:
    require_engine(engine)
    if engine == "python-re":
        return re.escape(text)
    if engine == "python-regex":
        import regex as regex_mod

        return str(regex_mod.escape(text))
    import pcre2

    escape = getattr(pcre2, "escape", None)
    if escape is None:
        raise UnsupportedError("this pcre2 binding does not provide escape(); refusing to guess")
    result = escape(text)
    if isinstance(result, bytes):
        return result.decode("utf-8", "replace")
    return str(result)


def check_replacement(engine: str, replacement: str) -> None:
    """Reject replacement syntax that belongs to a different engine.

    A literal dollar on python-re is written ``\\$``. An unescaped ``$1`` or
    ``${name}`` is PCRE syntax and is not silently left as text.
    """

    if engine == "pcre2":
        return
    i = 0
    while i < len(replacement):
        ch = replacement[i]
        if ch == "\\" and i + 1 < len(replacement):
            i += 2
            continue
        if ch == "$" and i + 1 < len(replacement):
            nxt = replacement[i + 1]
            if nxt.isdigit() or nxt == "{":
                raise PatternProblem(
                    "unsupported replacement syntax",
                    kind="unsupported_replacement",
                    position=i,
                    fragment=replacement[i : i + 12],
                    explanation=(
                        f"{engine} replacements use \\\\1 and \\\\g<name>. "
                        f"Unescaped {replacement[i : i + 8]!r} is PCRE syntax and was rejected. "
                        "Write \\$ for a literal dollar."
                    ),
                    exit_code=7,
                )
        i += 1


def iter_matches(
    compiled: Compiled,
    text: str,
    mode: str,
    *,
    max_matches: int,
) -> tuple[list[MatchInfo], bool]:
    """Return matches and whether ``max_matches`` truncated the result.

    Zero-width matches advance one character so the scan cannot loop.
    """

    if mode == "fullmatch":
        found = compiled.fullmatch(text)
        return ([found] if found else []), False
    if mode == "match":
        found = compiled.match(text)
        return ([found] if found else []), False
    if mode == "search":
        found = compiled.search(text)
        return ([found] if found else []), False
    if mode not in {"finditer", "findall"}:
        from lupaxa.regexlab.errors import UsageError

        raise UsageError(f"unknown mode {mode}")
    out: list[MatchInfo] = []
    pos = 0
    length = len(text)
    truncated = False
    while pos <= length:
        if len(out) >= max_matches:
            truncated = True
            break
        found = compiled.search(text, pos)
        if found is None:
            break
        out.append(found)
        nxt = found.start + 1 if found.end <= found.start else found.end
        if nxt <= pos:
            nxt = pos + 1
        pos = nxt
    return out, truncated


def _compile_re(pattern: str, flags: FlagSet) -> Compiled:
    try:
        raw = re.compile(pattern, _re_bits(flags))
    except re.error as exc:
        raise _from_re_error(exc, pattern) from exc
    return Compiled(
        engine="python-re",
        pattern=pattern,
        flags=flags,
        raw=raw,
        groupindex=dict(raw.groupindex),
        groups=raw.groups,
    )


def _compile_regex(pattern: str, flags: FlagSet) -> Compiled:
    import regex as regex_mod

    bits = 0
    for letter, value in (
        ("i", regex_mod.IGNORECASE),
        ("m", regex_mod.MULTILINE),
        ("s", regex_mod.DOTALL),
        ("x", regex_mod.VERBOSE),
        ("a", regex_mod.ASCII),
        ("L", getattr(regex_mod, "LOCALE", 0)),
    ):
        enabled = {
            "i": flags.ignorecase,
            "m": flags.multiline,
            "s": flags.dotall,
            "x": flags.verbose,
            "a": flags.ascii,
            "L": flags.locale,
        }
        if enabled[letter]:
            bits |= value
    extra_map = {
        "V": "VERSION1",
        "r": "REVERSE",
        "f": "FULLCASE",
        "e": "ENHANCEMATCH",
    }
    for ch in flags.extras:
        attr = extra_map.get(ch)
        if attr and hasattr(regex_mod, attr):
            bits |= getattr(regex_mod, attr)
    try:
        raw = regex_mod.compile(pattern, bits)
    except regex_mod.error as exc:
        raise _from_re_error(exc, pattern) from exc
    return Compiled(
        engine="python-regex",
        pattern=pattern,
        flags=flags,
        raw=raw,
        groupindex=dict(getattr(raw, "groupindex", {})),
        groups=int(getattr(raw, "groups", 0)),
    )


def _compile_pcre2(pattern: str, flags: FlagSet) -> Compiled:
    import pcre2

    compile_fn = getattr(pcre2, "compile", None)
    if compile_fn is None:
        raise UnsupportedError("this pcre2 binding has no compile(); refusing to guess an API")
    bits = _pcre2_bits(pcre2, flags)
    try:
        raw = compile_fn(pattern, flags=bits) if bits else compile_fn(pattern)
    except TypeError:
        try:
            raw = compile_fn(pattern)
        except Exception as exc:
            raise PatternProblem(
                str(exc),
                kind="compile_error",
                position=None,
                fragment=pattern[:40],
                explanation=f"pcre2 rejected the pattern: {exc}",
            ) from exc
    except Exception as exc:
        pos = getattr(exc, "pos", None)
        raise PatternProblem(
            str(exc),
            kind="compile_error",
            position=pos if isinstance(pos, int) else None,
            fragment=pattern[:40],
            explanation=f"pcre2 rejected the pattern: {exc}",
        ) from exc
    return Compiled(engine="pcre2", pattern=pattern, flags=flags, raw=raw)


def _re_bits(flags: FlagSet) -> int:
    bits = 0
    if flags.ignorecase:
        bits |= re.IGNORECASE
    if flags.multiline:
        bits |= re.MULTILINE
    if flags.dotall:
        bits |= re.DOTALL
    if flags.verbose:
        bits |= re.VERBOSE
    if flags.ascii:
        bits |= re.ASCII
    return bits


def _pcre2_bits(module: Any, flags: FlagSet) -> int:
    bits = 0
    mapping = (
        (flags.ignorecase, ("I", "IGNORECASE", "CASELESS")),
        (flags.multiline, ("M", "MULTILINE")),
        (flags.dotall, ("S", "DOTALL")),
        (flags.verbose, ("X", "EXTENDED", "VERBOSE")),
    )
    for enabled, names in mapping:
        if not enabled:
            continue
        for name in names:
            if hasattr(module, name):
                bits |= int(getattr(module, name))
                break
    return bits


def _normalise(match: Any, text: str) -> MatchInfo | None:
    if match is None:
        return None
    group0 = match.group(0)
    if isinstance(group0, bytes):
        group0 = group0.decode("utf-8", "replace")
    start, end = match.span()
    groups: list[str | None] = []
    for value in match.groups():
        if isinstance(value, bytes):
            groups.append(value.decode("utf-8", "replace"))
        elif value is None:
            groups.append(None)
        else:
            groups.append(str(value))
    named: dict[str, str | None] = {}
    if hasattr(match, "groupdict"):
        for key, value in match.groupdict().items():
            if isinstance(value, bytes):
                named[str(key)] = value.decode("utf-8", "replace")
            elif value is None:
                named[str(key)] = None
            else:
                named[str(key)] = str(value)
    if group0 is None:
        group0 = text[start:end]
    return MatchInfo(
        text=str(group0),
        start=int(start),
        end=int(end),
        groups=groups,
        groupdict=named,
    )


def _from_re_error(exc: BaseException, pattern: str) -> PatternProblem:
    pos = getattr(exc, "pos", None)
    position = pos if isinstance(pos, int) else None
    fragment = ""
    if position is not None and 0 <= position <= len(pattern):
        fragment = pattern[position : position + 12]
    return PatternProblem(
        str(exc),
        kind="compile_error",
        position=position,
        fragment=fragment,
        explanation=str(exc),
    )


def _importable(name: str) -> bool:
    try:
        __import__(name)
    except ImportError:
        return False
    return True


def _pcre2_available() -> bool:
    return _importable("pcre2") or _importable("python_pcre2")
