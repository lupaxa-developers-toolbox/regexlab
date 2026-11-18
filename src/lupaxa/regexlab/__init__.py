"""lupaxa.regexlab — explain, test, generate, and compare regular expressions.

The product is the ``regex-lab`` console script (alias ``regexlab``).
``lupaxa`` is a namespace package — there is no ``lupaxa/__init__.py``.
"""

from __future__ import annotations

from .version import __version__, get_version

__all__ = [
    "__version__",
    "get_version",
]
