"""TOML configuration. Precedence is CLI, then ``--config``, then the user file."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lupaxa.regexlab.errors import UsageError
from lupaxa.regexlab.flagset import FlagSet, parse_flags

KNOWN_CONFIG = {
    "engine",
    "mode",
    "flags",
    "timeout",
    "max_matches",
    "max_input_size",
    "encoding",
    "no_colour",
    "detail",
    "seed",
    "strict",
    "quiet",
    "verbose",
    "library_dir",
    "count",
    "min_length",
    "max_length",
    "iterations",
    "by_line",
    "format",
    "unique",
    "context",
}

_BOOL_KEYS = {"no_colour", "strict", "quiet", "verbose", "by_line", "unique"}
_INT_KEYS = {
    "max_matches",
    "max_input_size",
    "seed",
    "count",
    "min_length",
    "max_length",
    "iterations",
    "context",
}
_STR_KEYS = {"engine", "mode", "flags", "encoding", "detail", "library_dir", "format"}
_FLOAT_KEYS = {"timeout"}

MODES = ("search", "match", "fullmatch", "finditer", "findall")
ENGINES = ("python-re", "python-regex", "pcre2")
DETAILS = ("summary", "detailed", "technical")


def default_config_path() -> Path:
    env = os.environ.get("REGEXLAB_CONFIG")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "regexlab" / "config.toml"


def default_library_dir() -> Path:
    env = os.environ.get("REGEXLAB_DATA")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return base / "regexlab"


@dataclass
class Settings:
    engine: str = "python-re"
    mode: str = "fullmatch"
    flags: str = ""
    flagset: FlagSet = field(default_factory=FlagSet)
    timeout: float = 1.0
    max_matches: int = 1000
    max_input_size: int = 1_048_576
    encoding: str = "utf-8"
    no_colour: bool = False
    detail: str = "detailed"
    seed: int = 0
    strict: bool = False
    quiet: bool = False
    verbose: bool = False
    json_output: bool = False
    by_line: bool = False
    count: int | None = None
    min_length: int = 0
    max_length: int = 32
    iterations: int = 20
    library_dir: Path = field(default_factory=default_library_dir)
    unique: bool = False
    format: str | None = None
    context: int = 0
    mode_from_user: bool = False
    warnings: list[str] = field(default_factory=list)

    def resolved_mode(self, command: str) -> str:
        if self.mode_from_user:
            return self.mode
        if command in {"matches", "findall"}:
            return "finditer"
        return self.mode


def load_toml_table(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(f"cannot read config {path}: {exc}") from exc
    except UnicodeError as exc:
        raise UsageError(f"config {path} is not UTF-8 text") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"invalid TOML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise UsageError(f"config {path} must be a TOML table")
    return data


def _check_types(data: dict[str, Any], path: Path) -> None:
    for key, value in data.items():
        if key in _BOOL_KEYS and not isinstance(value, bool):
            raise UsageError(f"{path}: {key} must be a boolean")
        if key in _INT_KEYS and (isinstance(value, bool) or not isinstance(value, int)):
            raise UsageError(f"{path}: {key} must be an integer")
        if key in _FLOAT_KEYS and (isinstance(value, bool) or not isinstance(value, (int, float))):
            raise UsageError(f"{path}: {key} must be a number")
        if key in _STR_KEYS and not isinstance(value, str):
            raise UsageError(f"{path}: {key} must be a string")


def _known_and_unknown(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    unknown = sorted(key for key in data if key not in KNOWN_CONFIG)
    known = {key: value for key, value in data.items() if key in KNOWN_CONFIG}
    return known, unknown


def resolve_settings(args: Any) -> Settings:
    """Merge defaults, the user file, ``--config``, and explicit CLI options."""

    explicit: set[str] = set(getattr(args, "_explicit", set()))
    warnings: list[str] = []
    user_raw: dict[str, Any] = {}
    file_raw: dict[str, Any] = {}
    user_path = default_config_path()
    config_arg = getattr(args, "config", None)
    file_path = Path(config_arg).expanduser() if config_arg else None
    if file_path is not None:
        if not file_path.is_file():
            raise UsageError(f"config file not found: {file_path}")
        file_raw = load_toml_table(file_path)
    if user_path.is_file() and (file_path is None or file_path.resolve() != user_path.resolve()):
        user_raw = load_toml_table(user_path)
    user_known, user_unknown = _known_and_unknown(user_raw)
    file_known, file_unknown = _known_and_unknown(file_raw)
    cli_strict = "strict" in explicit and bool(getattr(args, "strict", False))
    merged_strict = bool(user_known.get("strict") or file_known.get("strict") or cli_strict)
    unknown = user_unknown + file_unknown
    if unknown and merged_strict:
        names = ", ".join(unknown)
        raise UsageError(f"unknown config key: {names}")
    for name in unknown:
        warnings.append(f"ignoring unknown config key {name}")
    if user_raw:
        _check_types(user_known, user_path)
    if file_raw and file_path is not None:
        _check_types(file_known, file_path)

    settings = Settings()
    settings.warnings = warnings
    _apply_mapping(settings, user_known, from_user=True)
    _apply_mapping(settings, file_known, from_user=True)
    _apply_cli(settings, args, explicit)
    _validate(settings)
    settings.flagset = parse_flags(settings.flags, engine=settings.engine)
    settings.flags = settings.flagset.letters()
    return settings


def _apply_mapping(settings: Settings, data: dict[str, Any], *, from_user: bool) -> None:
    for key, value in data.items():
        if key == "library_dir":
            settings.library_dir = Path(str(value)).expanduser()
        elif key == "timeout":
            settings.timeout = float(value)
        elif key == "mode":
            settings.mode = str(value)
            if from_user:
                settings.mode_from_user = True
        elif hasattr(settings, key):
            setattr(settings, key, value)


def _apply_cli(settings: Settings, args: Any, explicit: set[str]) -> None:
    mapping = {
        "engine": "engine",
        "mode": "mode",
        "flags": "flags",
        "timeout": "timeout",
        "max_matches": "max_matches",
        "max_input_size": "max_input_size",
        "encoding": "encoding",
        "no_colour": "no_colour",
        "detail": "detail",
        "seed": "seed",
        "strict": "strict",
        "quiet": "quiet",
        "verbose": "verbose",
        "by_line": "by_line",
        "count": "count",
        "min_length": "min_length",
        "max_length": "max_length",
        "iterations": "iterations",
        "unique": "unique",
        "format": "format",
        "context": "context",
        "json": "json_output",
    }
    for dest, attr in mapping.items():
        if dest not in explicit:
            continue
        value = getattr(args, dest)
        if attr == "mode":
            settings.mode_from_user = True
        if dest == "timeout" and value is not None:
            settings.timeout = float(value)
            continue
        toggles = {"no_colour", "strict", "quiet", "verbose", "by_line", "unique", "json"}
        if value is not None or dest in toggles:
            setattr(settings, attr, value)
    if "library_dir" in explicit and getattr(args, "library_dir", None):
        settings.library_dir = Path(args.library_dir).expanduser()


def _validate(settings: Settings) -> None:
    if settings.engine not in ENGINES:
        raise UsageError(
            f"unknown engine {settings.engine!r}. Choose python-re, python-regex, or pcre2."
        )
    if settings.mode not in MODES:
        raise UsageError(f"unknown mode {settings.mode!r}. Choose {', '.join(MODES)}.")
    if settings.detail not in DETAILS:
        raise UsageError(f"unknown detail {settings.detail!r}. Choose {', '.join(DETAILS)}.")
    if settings.timeout <= 0:
        raise UsageError("--timeout must be greater than 0")
    if settings.max_matches <= 0:
        raise UsageError("--max-matches must be greater than 0")
    if settings.max_input_size <= 0:
        raise UsageError("--max-input-size must be greater than 0")
    if settings.min_length < 0 or settings.max_length < 0:
        raise UsageError("lengths must be zero or greater")
    if settings.min_length > settings.max_length:
        raise UsageError("--min-length cannot exceed --max-length")
    if settings.iterations <= 0:
        raise UsageError("--iterations must be greater than 0")
    if settings.context < 0:
        raise UsageError("--context must be zero or greater")
    if settings.count is not None and settings.count < 0:
        raise UsageError("--count must be zero or greater")


def settings_mapping(settings: Settings) -> dict[str, Any]:
    """Effective configuration for ``regex-lab config``."""

    return {
        "engine": settings.engine,
        "mode": settings.mode,
        "flags": settings.flags,
        "timeout": settings.timeout,
        "max_matches": settings.max_matches,
        "max_input_size": settings.max_input_size,
        "encoding": settings.encoding,
        "no_colour": settings.no_colour,
        "detail": settings.detail,
        "seed": settings.seed,
        "strict": settings.strict,
        "quiet": settings.quiet,
        "verbose": settings.verbose,
        "library_dir": str(settings.library_dir),
        "count": settings.count,
        "min_length": settings.min_length,
        "max_length": settings.max_length,
        "iterations": settings.iterations,
        "by_line": settings.by_line,
        "format": settings.format,
        "unique": settings.unique,
        "context": settings.context,
    }
