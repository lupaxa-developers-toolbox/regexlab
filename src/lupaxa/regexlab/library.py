"""Named pattern library in a user data directory. Names are unique."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from lupaxa.regexlab.errors import UsageError
from lupaxa.regexlab.flagset import parse_flags
from lupaxa.regexlab.parser import parse_pattern

_LIBRARY = "library.toml"


@dataclass
class LibraryEntry:
    name: str
    pattern: str
    engine: str = "python-re"
    flags: str = ""
    mode: str = "fullmatch"
    description: str = ""


def library_file(directory: Path) -> Path:
    return directory / _LIBRARY


def load_library(directory: Path) -> list[LibraryEntry]:
    path = library_file(directory)
    if not path.exists():
        return []
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"invalid library TOML: {exc}") from exc
    rows = data.get("patterns", [])
    if not isinstance(rows, list):
        raise UsageError("library patterns must be an array of tables")
    entries: list[LibraryEntry] = []
    for row in rows:
        if not isinstance(row, dict) or "name" not in row or "pattern" not in row:
            raise UsageError("each library pattern needs name and pattern")
        entries.append(
            LibraryEntry(
                name=str(row["name"]),
                pattern=str(row["pattern"]),
                engine=str(row.get("engine", "python-re")),
                flags=str(row.get("flags", "")),
                mode=str(row.get("mode", "fullmatch")),
                description=str(row.get("description", "")),
            )
        )
    return entries


def save_library(directory: Path, entries: list[LibraryEntry]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    lines = ['version = "1.0"', ""]
    for entry in entries:
        lines.extend(
            [
                "[[patterns]]",
                f"name = {_q(entry.name)}",
                f"pattern = {_q(entry.pattern)}",
                f"engine = {_q(entry.engine)}",
                f"flags = {_q(entry.flags)}",
                f"mode = {_q(entry.mode)}",
                f"description = {_q(entry.description)}",
                "",
            ]
        )
    library_file(directory).write_text("\n".join(lines), encoding="utf-8")


def add_entry(
    directory: Path,
    entry: LibraryEntry,
    *,
    force: bool,
) -> None:
    parse_pattern(entry.pattern, entry.engine, parse_flags(entry.flags, engine=entry.engine))
    entries = load_library(directory)
    names = [item.name for item in entries]
    if entry.name in names and not force:
        raise UsageError(f"pattern name {entry.name!r} already exists. Pass --force to overwrite.")
    if entry.name in names:
        entries = [item for item in entries if item.name != entry.name]
    entries.append(entry)
    save_library(directory, entries)


def remove_entry(directory: Path, name: str) -> None:
    entries = load_library(directory)
    kept = [item for item in entries if item.name != name]
    if len(kept) == len(entries):
        raise UsageError(f"no library pattern named {name!r}")
    save_library(directory, kept)


def find_entry(directory: Path, name: str) -> LibraryEntry:
    for entry in load_library(directory):
        if entry.name == name:
            return entry
    raise UsageError(f"no library pattern named {name!r}")


def search_entries(directory: Path, query: str) -> list[LibraryEntry]:
    needle = query.casefold()
    found: list[LibraryEntry] = []
    for entry in load_library(directory):
        haystack = " ".join([entry.name, entry.pattern, entry.description]).casefold()
        if needle in haystack:
            found.append(entry)
    return found


def render_entries(entries: list[LibraryEntry]) -> str:
    if not entries:
        return "no patterns"
    lines: list[str] = []
    for entry in entries:
        lines.append(f"{entry.name}  {entry.engine}  {entry.pattern}")
        if entry.description:
            lines.append(f"  {entry.description}")
    return "\n".join(lines)


def _q(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'
