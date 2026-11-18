"""Read subjects from arguments, files, directories, and stdin."""

from __future__ import annotations

import fnmatch
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from lupaxa.regexlab.config import Settings
from lupaxa.regexlab.errors import BinaryInputError, ResourceLimitError, UsageError


@dataclass
class Subject:
    label: str
    text: str


def read_pattern_file(path: Path, settings: Settings) -> str:
    raw = _read_bytes(path, settings.max_input_size)
    text = _decode(raw, settings.encoding, path)
    if text.endswith("\n"):
        text = text[:-1]
    return text


def gather_subjects(
    settings: Settings,
    texts: list[str] | None,
    paths: list[str] | None,
    *,
    use_stdin: bool,
    recursive: bool,
    include: list[str] | None,
    exclude: list[str] | None,
    by_line: bool,
) -> list[Subject]:
    subjects: list[Subject] = []
    for index, text in enumerate(texts or []):
        subjects.extend(_split(f"arg{index + 1}", text, by_line, settings))
    for raw_path in paths or []:
        path = Path(raw_path)
        if not path.exists():
            raise UsageError(f"input not found: {path}")
        if path.is_dir():
            if not recursive:
                raise UsageError(f"{path} is a directory. Pass --recursive to search it.")
            for file_path in _walk(path, include, exclude):
                subjects.extend(_file_subjects(file_path, settings, by_line))
        else:
            subjects.extend(_file_subjects(path, settings, by_line))
    if use_stdin:
        raw = sys.stdin.buffer.read(settings.max_input_size + 1)
        if len(raw) > settings.max_input_size:
            raise ResourceLimitError(
                f"stdin exceeds --max-input-size ({settings.max_input_size} bytes)"
            )
        if b"\x00" in raw:
            raise BinaryInputError("stdin is binary and was not treated as text")
        text = _decode(raw, settings.encoding, Path("stdin"))
        subjects.extend(_split("stdin", text, by_line, settings))
    return subjects


def _file_subjects(path: Path, settings: Settings, by_line: bool) -> list[Subject]:
    raw = _read_bytes(path, settings.max_input_size)
    text = _decode(raw, settings.encoding, path)
    return _split(str(path), text, by_line, settings)


def _read_bytes(path: Path, max_size: int) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc}") from exc
    if len(data) > max_size:
        raise ResourceLimitError(f"{path} exceeds --max-input-size ({max_size} bytes)")
    if b"\x00" in data:
        raise BinaryInputError(f"{path} is binary and was not treated as text")
    return data


def _decode(data: bytes, encoding: str, path: Path) -> str:
    try:
        return data.decode(encoding)
    except UnicodeError as exc:
        raise UsageError(f"{path} is not valid {encoding} text") from exc
    except LookupError as exc:
        raise UsageError(f"unknown encoding {encoding}") from exc


def _split(label: str, text: str, by_line: bool, settings: Settings) -> list[Subject]:
    if len(text.encode(settings.encoding, errors="replace")) > settings.max_input_size:
        raise ResourceLimitError(f"{label} exceeds --max-input-size")
    if not by_line:
        return [Subject(label, text)]
    lines = text.splitlines()
    return [Subject(f"{label}:{index + 1}", line) for index, line in enumerate(lines)]


def _walk(root: Path, include: list[str] | None, exclude: list[str] | None) -> list[Path]:
    found: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(filenames):
            if include and not any(fnmatch.fnmatch(name, pattern) for pattern in include):
                continue
            if exclude and any(fnmatch.fnmatch(name, pattern) for pattern in exclude):
                continue
            found.append(Path(dirpath) / name)
    return found
