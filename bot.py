from __future__ import annotations

import importlib
import os
import tempfile
from pathlib import Path

_cache_root = Path(tempfile.gettempdir()) / "nethack_arena_submission_cache"
_cache_root.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_root / "xdg"))
os.environ.setdefault("NUMBA_CACHE_DIR", str(_cache_root / "numba"))

import roles  # noqa: E402

# identity prefix -> specialist engine adapter (from daglar-dragomirov/nethacker@e29eb82, chosen there on held-out
# games): Healers on vlomshakov's engines, Samurai on daglar's v35. Every other identity plays the main engine, nhbot.
# Human Priests left PetrAnokhin's pf_pa for nhbot (eL1fe's spell bundle casts their healing): +0.053 +- 0.022 per game
# over 113 paired held-out games (ph0/ph1), in line with the hub's private seeds (dag25 0.260 vs pf_pa 0.228).
SPECIALISTS = {
    "hea-gno": "adapter_pf_hg",
    "hea-hum": "adapter_pf_hh",
    "sam": "adapter_pf_v35",
}


def _specialist(ident):
    if not ident or os.environ.get("NHBOT_NO_SPECIALISTS"):
        return None
    table = dict(SPECIALISTS)
    # dev runs: NHBOT_ROUTE='{"tou": "adapter_pf_v25"}' (an empty name routes to nhbot)
    if os.environ.get("NHBOT_ROUTE"):
        import json
        table.update(json.loads(os.environ["NHBOT_ROUTE"]))
    for prefix in sorted(table, key=len, reverse=True):
        if ident == prefix or ident.startswith(prefix + "-"):
            return table[prefix] or None
    return None


class Bot:
    """Routes each identity to an engine: nhbot (an AutoAscend descendant) or a specialist."""

    def __init__(self) -> None:
        self._drivers = {}
        self._driver = None

    def _get(self, module_name):
        if module_name not in self._drivers:
            self._drivers[module_name] = importlib.import_module(module_name).AutoAscendDriver()
        return self._drivers[module_name]

    def reset(self, initial_observation):
        ident = None
        try:
            ident = roles.identity(initial_observation)
        except Exception:  # noqa: BLE001
            pass
        module_name = _specialist(ident) or "adapter"
        if module_name == "adapter":
            try:
                roles.apply(ident)
            except Exception:  # noqa: BLE001 -- a bad override must never cost the episode
                pass
        self._driver = self._get(module_name)
        self._driver.reset(initial_observation)

    def act(self, observation):
        return self._driver.act(observation)

    def close(self):
        for driver in self._drivers.values():
            driver.close()


def make_agent():
    return Bot()
