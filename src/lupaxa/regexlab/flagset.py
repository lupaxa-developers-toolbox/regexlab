"""Regex flag letters shared by the CLI, parser, and engines."""

from __future__ import annotations

from dataclasses import dataclass

from lupaxa.regexlab.errors import UsageError

_LETTERS = {
    "i": "ignorecase",
    "m": "multiline",
    "s": "dotall",
    "x": "verbose",
    "a": "ascii",
    "u": "unicode",
    "L": "locale",
}
_NAMES = {name: letter for letter, name in _LETTERS.items()}
_NAMES.update(
    {
        "ignorecase": "i",
        "multiline": "m",
        "dotall": "s",
        "verbose": "x",
        "ascii": "a",
        "unicode": "u",
        "locale": "L",
    }
)
_REGEX_EXTRA = {
    "V": "VERSION1",
    "r": "REVERSE",
    "f": "FULLCASE",
    "e": "ENHANCEMATCH",
}


@dataclass
class FlagSet:
    """Flags that affect parsing, explanation, and compilation."""

    ignorecase: bool = False
    multiline: bool = False
    dotall: bool = False
    verbose: bool = False
    ascii: bool = False
    unicode: bool = True
    unicode_explicit: bool = False
    locale: bool = False
    extras: str = ""

    def letters(self) -> str:
        parts: list[str] = []
        if self.ignorecase:
            parts.append("i")
        if self.multiline:
            parts.append("m")
        if self.dotall:
            parts.append("s")
        if self.verbose:
            parts.append("x")
        if self.ascii:
            parts.append("a")
        if self.unicode_explicit:
            parts.append("u")
        if self.locale:
            parts.append("L")
        if self.extras:
            parts.append(self.extras)
        return "".join(parts)

    def replaced(self, **changes: bool | str) -> FlagSet:
        data = {
            "ignorecase": self.ignorecase,
            "multiline": self.multiline,
            "dotall": self.dotall,
            "verbose": self.verbose,
            "ascii": self.ascii,
            "unicode": self.unicode,
            "unicode_explicit": self.unicode_explicit,
            "locale": self.locale,
            "extras": self.extras,
        }
        data.update(changes)
        return FlagSet(**data)  # type: ignore[arg-type]


def _tokens(raw: str) -> list[str]:
    if any(ch in raw for ch in ",| \t"):
        return [part for part in raw.replace("|", ",").replace(" ", ",").split(",") if part]
    return [raw]


def parse_flags(text: str | None, *, engine: str = "python-re") -> FlagSet:
    """Parse ``im``, ``i,m``, or ``IGNORECASE`` into a :class:`FlagSet`."""

    raw = (text or "").strip()
    if not raw:
        return FlagSet()
    letters: list[str] = []
    extras: list[str] = []
    for token in _tokens(raw):
        lower = token.lower()
        if len(token) > 1 and lower in _NAMES:
            letters.append(_NAMES[lower])
            continue
        if all(ch in _LETTERS or ch in _REGEX_EXTRA for ch in token):
            for ch in token:
                if ch in _REGEX_EXTRA:
                    if engine != "python-regex":
                        raise UsageError(
                            f"flag {ch} ({_REGEX_EXTRA[ch]}) is only available on python-regex"
                        )
                    extras.append(ch)
                else:
                    letters.append(ch)
            continue
        if lower in _NAMES:
            letters.append(_NAMES[lower])
            continue
        raise UsageError(f"unknown flag: {token}")
    if "a" in letters and "u" in letters:
        raise UsageError("flags a and u are incompatible")
    if "L" in letters and "a" in letters:
        raise UsageError("flags L and a are incompatible")
    if "L" in letters and engine == "python-re":
        raise UsageError("flag L applies to bytes patterns; Regex Lab compiles str patterns")
    flags = FlagSet()
    for ch in letters:
        if ch == "i":
            flags.ignorecase = True
        elif ch == "m":
            flags.multiline = True
        elif ch == "s":
            flags.dotall = True
        elif ch == "x":
            flags.verbose = True
        elif ch == "a":
            flags.ascii = True
            flags.unicode = False
        elif ch == "u":
            flags.unicode = True
            flags.unicode_explicit = True
            flags.ascii = False
        elif ch == "L":
            flags.locale = True
            flags.unicode = False
    flags.extras = "".join(extras)
    return flags


def flag_catalogue() -> list[dict[str, str]]:
    """Rows for ``regex-lab flags``."""

    rows = [
        {
            "letter": "i",
            "name": "IGNORECASE",
            "engines": "python-re, python-regex, pcre2",
            "meaning": "Case-insensitive matching.",
        },
        {
            "letter": "m",
            "name": "MULTILINE",
            "engines": "python-re, python-regex, pcre2",
            "meaning": "^ and $ match at line boundaries.",
        },
        {
            "letter": "s",
            "name": "DOTALL",
            "engines": "python-re, python-regex, pcre2",
            "meaning": "Dot matches a newline.",
        },
        {
            "letter": "x",
            "name": "VERBOSE",
            "engines": "python-re, python-regex, pcre2",
            "meaning": "Ignore whitespace and # comments outside classes.",
        },
        {
            "letter": "a",
            "name": "ASCII",
            "engines": "python-re, python-regex",
            "meaning": "\\d, \\w, and \\s match ASCII only.",
        },
        {
            "letter": "u",
            "name": "UNICODE",
            "engines": "python-re, python-regex",
            "meaning": "Unicode classes. This is the default for str patterns.",
        },
        {
            "letter": "L",
            "name": "LOCALE",
            "engines": "python-re (bytes only)",
            "meaning": "Locale-dependent classes. Not used for str patterns.",
        },
        {
            "letter": "V",
            "name": "VERSION1",
            "engines": "python-regex",
            "meaning": "regex module version-1 semantics.",
        },
        {
            "letter": "r",
            "name": "REVERSE",
            "engines": "python-regex",
            "meaning": "Search backwards.",
        },
        {
            "letter": "f",
            "name": "FULLCASE",
            "engines": "python-regex",
            "meaning": "Unicode full case-folding.",
        },
    ]
    return rows
