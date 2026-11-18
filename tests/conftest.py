"""Keep tests off the developer's config and library files."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_regexlab_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    home = tmp_path_factory.mktemp("regexlab-home")
    monkeypatch.setenv("REGEXLAB_CONFIG", str(home / "missing.toml"))
    monkeypatch.setenv("REGEXLAB_DATA", str(home / "data"))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
