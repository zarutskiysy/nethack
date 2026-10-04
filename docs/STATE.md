# Project state at freeze (2026-10-04 19:35 MSK)

Development on the nethackers.dunnolab.ai bot is frozen: no new experiments and no new releases until further notice.
Both experiment queues ran their in-flight games to completion and stopped; the Mac watchdog/daily launchd jobs are
unloaded.

## Boards (from tools/report.py, 19:33 MSK)

| tier | our best | rank | best rival | our impact |
|---|---|---|---|---|
| verified generalist | v10c `f3a2a42` **0.3244** | #1 (we hold #1-#7) | daglar 0.3063 (#10) | 0.87 (#7; homepage top-5 cut 1.89; daglar 5.78) |
| public generalist | v12pub `96ef326` **0.3820** | #1 | daglar 93960fb 0.3750 (#2) | 1.86 (#3; daglar 14.63) |

Nobody has ascended. The newest release, v10g `69f6da8`, scored 0.3176 verified (rank 6, the same as v10f). Small
single-role releases do not move the verified mean.

## Released programs (all pushed, pinned by the hub; never add identities to them, which would re-date their impact)

| program | commit | branch | purpose |
|---|---|---|---|
| v10c | f3a2a42 | v10c | verified #1 (0.3244) |
| v10d / v10e / v10f / v10g | f31cc4a / 781552d / 3c6aa60 / 69f6da8 | same names | later verified releases, 0.3175-0.3224 |
| v12pub | 96ef326 | v12pub | public #1 (0.3820): per-identity best public setup |
| v11pub, v7 | 00cf417, 94c4c1c | same names | older public-board variants |

## Final experiment results (dev held-out seeds; Mac arm64 and VM x86 pooled by inverse variance)

Mac: 2,787 games this run, 0 failures. VM: 7,564 games today, 0 failures.

Ship candidates (pooled z >= 2.5, >= 180 clusters), not released:
- Rogues `MISSILE_RECOVER + ROG_VOLLEY` on the rog_fix tree: +0.050, z 3.6, n 436. The same config on integ5 gives
  -0.006 (n 348), so the two trees disagree. Do not ship until that is understood.
- Rogues `DITCH_PET_ROLES [4,8,9]` on integ5: +0.036, z 2.8, n 508. Most of the signal is in one VM fresh-seed re-run.
- Rangers ran-elf-cha-fem and ran-hum-neu re-routed from pf_s25p8 to nhbot (with the v10g archery): +0.057, z 2.8,
  n 182, from the VM only. A single-group re-route needs a fresh-seed re-run first.

Close (z 1.5-2.5): Knights to nhbot (+0.027..0.029), Barbarian `MEDUSA_ISLE_HOP` (+0.002), `LMINION_ELBERETH`
(+0.0004), `stairs_first2` (+0.0036, z 2.0).

Rejected: Big Room stairs replay (brr1 -0.048, brr2 -0.060), `WIZ_DIVE_BOLT` (-0.028), `RAN_DIVE_VOLLEY`
(-0.026), `WEAPON_MODEL_FIX` (-0.014).

Full per-arm tables are in the workspace: `devruns/seqab_report.md` (Mac), `devruns_vm/seqab_report.md` (VM),
`devruns/daily/2026-10-04.md`.

## Not pushed, on purpose
- Feature and integration branches (integ*, *-kit, early-game, ...) are local only. Their history carries old
  AI-attribution trailers, and daglar copies pushed code within hours. Releases are pushed as squashed clean commits
  (`git commit-tree <tree> -p <last release>`).
- early-game: the work-in-progress grind/dive policy redesign is committed locally (5ce826d, flags default off,
  untested in games).

## How to resume
1. Read `/Users/semyon/Nethack/COMPETITION.md` (playbook) and the project memory.
2. Queues: the original queue files are saved as `tools/seqab_queue.pre_freeze.json` (Mac) and
   `tools/vm_queue.pre_freeze.json` (VM). Copy them back to un-freeze. In the live files every entry has
   `"disabled": true, "frozen_20261004": true`.
3. Mac autopilot: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.zarutskiysy.nethack.{watchdog,daily}.plist`.
4. VM: remove `~/Nethack/PAUSE`; its cron watchdog restarts seqab within 10 min.
