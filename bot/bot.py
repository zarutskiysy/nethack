from __future__ import annotations

import os
import tempfile
from pathlib import Path

_cache_root = Path(tempfile.gettempdir()) / "nethack_arena_submission_cache"
_cache_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
os.environ.setdefault("NUMBA_CACHE_DIR", str(_cache_root / "numba"))

import adapter  # noqa: E402


class Bot:
    """One engine (nhbot, an AutoAscend descendant) for every identity."""

    def __init__(self) -> None:
        self._driver = adapter.AutoAscendDriver()

    def reset(self, initial_observation):
        self._driver.reset(initial_observation)

    def act(self, observation):
        return self._driver.act(observation)

    def close(self):
        self._driver.close()


def make_agent():
    return Bot()
