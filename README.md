# nethack

A NetHack 3.6.6 bot for [NetHackers](https://nethackers.dunnolab.ai/).

- `bot/` — the solution (`bot.py` with `make_agent()`), a single engine `bot/nhbot`, an AutoAscend
  descendant forked from daglar-dragomirov/nethacker's `pf_s25p` (vkurenkov's "jawfish" s25 line).
  MIT, see `bot/LICENSE`.
- `tools/` — evaluation helpers: `sweep.py` (official `nethackers eval` over identities),
  `devrun.py` (native or in-container runs on held-out seeds with death diagnostics),
  `devcmp.py` (paired A/B comparison), `summary.py`.

Changes over the parent are listed in `CHANGES.md`.
