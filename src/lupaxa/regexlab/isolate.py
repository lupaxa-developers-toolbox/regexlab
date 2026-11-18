"""Process isolation for untrusted matching. Hung workers are killed."""

from __future__ import annotations

import multiprocessing
import os
import signal
import time
import warnings
from pathlib import Path
from typing import Any

from lupaxa.regexlab.errors import EXIT_GENERAL, EXIT_TIMEOUT

OPS: dict[str, Any] = {}


class _Alarm(Exception):
    pass


def _handle_alarm(_signum: int, _frame: object) -> None:
    raise _Alarm()


def arm(timeout: float) -> None:
    if timeout > 0 and hasattr(signal, "setitimer"):
        signal.signal(signal.SIGALRM, _handle_alarm)
        signal.setitimer(signal.ITIMER_REAL, timeout)


def disarm() -> None:
    if hasattr(signal, "setitimer"):
        signal.setitimer(signal.ITIMER_REAL, 0)


def run(
    op: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    method: str = "fork",
    holder: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run ``op`` in a child process and kill it if ``timeout`` elapses."""

    _prepare_path()
    warnings.filterwarnings(
        "ignore",
        message=r".*fork.*",
        category=DeprecationWarning,
    )
    ctx = multiprocessing.get_context(method)
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_child, args=(op, payload, child), daemon=True)  # type: ignore[attr-defined]
    proc.start()
    child.close()
    if holder is not None:
        holder["proc"] = proc
    deadline = time.monotonic() + timeout
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _kill(proc)
                return _timeout(op)
            if parent.poll(min(0.05, remaining)):
                try:
                    message = parent.recv()
                except EOFError:
                    message = {
                        "status": "error",
                        "exit_code": EXIT_GENERAL,
                        "error": _error("worker", "The worker closed the pipe."),
                    }
                proc.join(1)
                return message
            if not proc.is_alive():
                proc.join(0.2)
                return {
                    "status": "error",
                    "exit_code": EXIT_GENERAL,
                    "error": _error("worker", f"The worker exited with code {proc.exitcode}."),
                }
    finally:
        parent.close()
        if proc.is_alive():
            _kill(proc)


def _child(op: str, payload: dict[str, Any], connection: Any) -> None:
    import lupaxa.regexlab.ops  # noqa: F401  (registers OPS)

    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        handler = OPS.get(op)
        if handler is None:
            connection.send(
                {
                    "status": "error",
                    "exit_code": EXIT_GENERAL,
                    "error": _error("worker", f"Unknown worker operation {op}."),
                }
            )
            return
        connection.send(handler(payload))
    except _Alarm:
        connection.send(_timeout(op))
    except Exception as exc:  # noqa: BLE001 - worker boundary
        from lupaxa.regexlab.errors import PatternProblem, RegexLabError

        if isinstance(exc, PatternProblem):
            connection.send(
                {
                    "status": "error",
                    "exit_code": exc.exit_code,
                    "error": exc.as_dict(),
                }
            )
        elif isinstance(exc, RegexLabError):
            connection.send(
                {
                    "status": "error",
                    "exit_code": exc.exit_code,
                    "error": _error(exc.kind, str(exc)),
                }
            )
        else:
            connection.send(
                {
                    "status": "error",
                    "exit_code": EXIT_GENERAL,
                    "error": _error(type(exc).__name__, str(exc)),
                }
            )
    finally:
        connection.close()


def _kill(proc: Any) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(0.5)
    if proc.is_alive():
        proc.kill()
        proc.join(0.5)


def _timeout(op: str) -> dict[str, Any]:
    return {
        "status": "timeout",
        "exit_code": EXIT_TIMEOUT,
        "error": _error("timeout", f"{op} exceeded the timeout and the worker was stopped."),
    }


def _error(kind: str, message: str) -> dict[str, Any]:
    return {
        "type": kind,
        "message": message,
        "position": None,
        "fragment": None,
        "explanation": message,
    }


def _prepare_path() -> None:
    src = Path(__file__).resolve().parents[2]
    current = os.environ.get("PYTHONPATH", "")
    parts = [part for part in current.split(os.pathsep) if part]
    text = str(src)
    if text not in parts:
        os.environ["PYTHONPATH"] = os.pathsep.join([text, *parts]) if parts else text
