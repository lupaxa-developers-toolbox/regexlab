"""Exit codes and error types for Regex Lab."""

from __future__ import annotations

from typing import Any

EXIT_OK = 0
EXIT_GENERAL = 1
EXIT_USAGE = 2
EXIT_INVALID = 3
EXIT_SUITE = 4
EXIT_TIMEOUT = 5
EXIT_RESOURCE = 6
EXIT_UNSUPPORTED = 7
EXIT_INCOMPLETE = 8
EXIT_DIFFERENCE = 9
EXIT_LINT = 10


class RegexLabError(Exception):
    """Base error that maps to a process exit code."""

    exit_code = EXIT_GENERAL
    kind = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(RegexLabError):
    exit_code = EXIT_USAGE
    kind = "usage"


class ResourceLimitError(RegexLabError):
    exit_code = EXIT_RESOURCE
    kind = "resource"


class UnsupportedError(RegexLabError):
    exit_code = EXIT_UNSUPPORTED
    kind = "unsupported"


class IncompleteError(RegexLabError):
    exit_code = EXIT_INCOMPLETE
    kind = "incomplete"


class BinaryInputError(RegexLabError):
    """Binary input is refused rather than decoded as text."""

    kind = "binary"


class PatternProblem(RegexLabError):
    """A pattern that is invalid or unsupported on the selected engine."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        position: int | None,
        fragment: str,
        explanation: str,
        exit_code: int = EXIT_INVALID,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.position = position
        self.fragment = fragment
        self.explanation = explanation
        self.exit_code = exit_code

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "message": self.message,
            "position": self.position,
            "fragment": self.fragment,
            "explanation": self.explanation,
        }


class UsageExit(Exception):
    """Argparse help or usage, already printed. ``code`` is the exit status."""

    def __init__(self, code: int) -> None:
        super().__init__(str(code))
        self.code = code
