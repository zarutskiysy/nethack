"""Unit tests (fakes, no NetHack game) for PT_V2 (nhbot/castle_tune.py, castle_front.py; research/castle_debug.md):
the fixes from the tc1 forensics of the passtune lane. Fakes from tests/test_castle_tune.py / test_castle_basecamp.py.
Run from the repo root:  python tests/test_castle_lane_v2.py"""
import os
import sys

import nle.nethack as nh

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import test_castle_tune as T                                  # noqa: E402
import test_castle_basecamp as B                              # noqa: E402
from nhbot import jf_config                                   # noqa: E402
from nhbot import castle_tune as ctune                        # noqa: E402
from nhbot import castle_front as cfront                      # noqa: E402
from nhbot.castle_logic import to_bot                         # noqa: E402
from nle.nethack import actions as A                          # noqa: E402

flags = T.flags


def _glyph(name):
    i = next(i for i in range(nh.NUMMONS) if nh.permonst(i).mname == name)
    return nh.GLYPH_MON_OFF + i


XORN, EARTH_EL, GHOST, SOLDIER_G, EEL_G, JAGUAR = (_glyph(n) for n in (
    'xorn', 'earth elemental', 'ghost', 'soldier', 'giant eel', 'jaguar'))


def test_flag_defaults():
    assert jf_config.PT_V2 is True
    assert jf_config.CASTLE_PASSTUNE is False      # PT_V2 acts only inside the lane: flag-off games unchanged
    assert jf_config.PT_GO_TURNS > 0 and jf_config.PT_FARM_STALL > 0 and jf_config.PT_HELD_TRIES > 0


# ---------------------------------------------------------------- held by a sea monster: Elbereth, not the end
def test_held_writes_elbereth_and_waits():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(pos=(4, 9))
        agent.message = 'The giant eel bites!  The giant eel swings itself around you!'
        assert tune._step() is True and not tune.done
        assert agent.steps[-1] == ('engrave', 'Elbereth') and tune._engraved()
        # still held, Elbereth under us: wait for the holder's move (no blow: setmangry would erase it)
        agent.message = 'You cannot escape from the giant eel!'
        assert tune._step() is True and agent.steps[-1] == 'search' and not tune.done
        assert A.Command.FIGHT not in agent.steps
        # released: the lane goes on (the tune search from the Elbereth square)
        agent.message = 'You get released!'
        assert not tune._held()
        assert tune._step() is True and A.Command.APPLY in agent.steps and not tune.done


def test_held_budget_then_abort():
    with flags(CASTLE_PASSTUNE=True, PT_HELD_TRIES=2):
        agent, dive, tune = T.setup(pos=(4, 9))
        agent.inventory.engraving_below_me = 'Elbereth'
        agent.message = 'The giant eel swings itself around you!'
        assert tune._step() is True and tune._step() is True
        assert tune._step() is False and tune.done and 'held' in tune.reason


def test_held_budget_is_per_grab():
    with flags(CASTLE_PASSTUNE=True, PT_HELD_TRIES=2):
        agent, dive, tune = T.setup(pos=(4, 9))
        agent.inventory.engraving_below_me = 'Elbereth'
        for _ in range(3):                        # three separate grabs over a long stay
            agent.message = 'The giant eel swings itself around you!'
            assert tune._step() is True and tune._step() is True
            agent.message = 'You get released!'
            assert tune._step() is True and not tune.done and tune.tries['held'] == 0


def test_held_cannot_write_aborts_as_before():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(pos=(4, 9))
        agent.engrave_ok = False
        agent.message = 'The giant eel swings itself around you!'
        assert tune._step() is False and 'held' in tune.reason


def test_held_flag_off_unchanged():
    with flags(CASTLE_PASSTUNE=True, PT_V2=False):
        agent, dive, tune = T.setup(pos=(4, 9))
        agent.message = 'The giant eel swings itself around you!'
        assert tune._step() is False and 'held' in tune.reason
        assert ('engrave', 'Elbereth') not in agent.steps


# ---------------------------------------------------------------- the Elbereth budget counts failed writes
def test_elbereth_budget_resets_on_an_intact_engraving():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup()
        agent.inventory.engraving_below_me = 'Elbereth'
        tune.tries['elbereth'] = jf_config.PT_ELBERETH_TRIES   # 12 writes over a long farm
        tune._step()
        assert tune.tries['elbereth'] == 0
        agent.inventory.engraving_below_me = '?lbe??th'          # allmain.c u_wipe_engr smudged it
        n = len(agent.steps)
        assert tune._step() is True and ('engrave', 'Elbereth') in agent.steps[n:]
    # PT_V2 off: the lifetime budget is spent, no new Elbereth (wiz-elf 645's jaguar)
    with flags(CASTLE_PASSTUNE=True, PT_V2=False):
        agent, dive, tune = T.setup()
        agent.inventory.engraving_below_me = '?lbe??th'
        tune.tries['elbereth'] = jf_config.PT_ELBERETH_TRIES
        n = len(agent.steps)
        tune._step()
        assert ('engrave', 'Elbereth') not in agent.steps[n:]


# ---------------------------------------------------------------- the crusher and what it can't touch
def test_crush_immune_is_dbridge_automiss():
    for g in (XORN, EARTH_EL, GHOST):
        assert ctune.crush_immune(g), g
    for g in (SOLDIER_G, EEL_G, JAGUAR, nh.GLYPH_INVISIBLE, T.SS.S_room):
        assert not ctune.crush_immune(g), g


def test_no_raise_on_a_xorn():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        B.known_tune(agent, tune)
        T.put_monster(agent, ctune.SPAN, 'xorn', XORN)
        assert tune._victims() == ([], [])
        cycles = tune.cycles
        assert tune._step() is True and agent.span_state == 'down' and tune.cycles == cycles
        assert agent.steps[-1] == 'search'
        T.clear_monsters(agent)
        T.put_monster(agent, ctune.PORTCULLIS, 'soldier', SOLDIER_G)
        assert tune._step() is True and agent.span_state == 'up' and tune.cycles == cycles + 1
    with flags(CASTLE_PASSTUNE=True, PT_V2=False):
        agent, dive, tune = T.setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        B.known_tune(agent, tune)
        T.put_monster(agent, ctune.SPAN, 'xorn', XORN)
        assert tune._victims() == ([ctune.SPAN], [])


def test_quiet_crusher_end_is_marked():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        B.known_tune(agent, tune)
        r = True
        for _ in range(jf_config.PT_CRUSH_WAIT + 5):
            r = tune._step()
            if not r:
                break
        assert r is False and tune.handed_off and tune.quiet_end
    # a crusher ended by its raise cap is not quiet
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        B.known_tune(agent, tune)
        tune.cycles = jf_config.PT_CRUSH_MAX
        T.put_monster(agent, ctune.SPAN)
        assert tune._step() is False and tune.handed_off and not tune.quiet_end


# ---------------------------------------------------------------- the farm's end
def test_farm_strong_by_xl_alone():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True):
        agent, dive, tune = B.setup(tune='DGABE', hp=62, maxhp=62)
        agent.inventory.engraving_below_me = 'Elbereth'
        B.known_tune(agent, tune)
        agent.blstats.experience_level = jf_config.PT_FARM_XL
        assert tune._step() is False and tune.handed_off
        assert any('M:farm_over' in m and 'strong' in m for m in agent.logs)
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True, PT_V2=False):
        agent, dive, tune = B.setup(tune='DGABE', hp=62, maxhp=62)
        agent.inventory.engraving_below_me = 'Elbereth'
        B.known_tune(agent, tune)
        agent.blstats.experience_level = jf_config.PT_FARM_XL
        assert tune._step() is True and not tune.handed_off       # max HP 62 < PT_FARM_HP: farms on


def test_farm_stall_without_experience():
    with flags(CASTLE_PASSTUNE=True, CASTLE_FARM_THEN_ENTER=True, PT_FARM_STALL=50):
        agent, dive, tune = B.setup(tune='DGABE')
        agent.inventory.engraving_below_me = 'Elbereth'
        agent.blstats.experience_points = 1500
        B.known_tune(agent, tune)
        assert tune._step() is True and not tune.handed_off
        agent.blstats.time += 30
        agent.blstats.experience_points = 1700                    # a kill: the clock starts again
        assert tune._step() is True and not tune.handed_off
        agent.blstats.time += 45
        assert tune._step() is True and not tune.handed_off
        agent.blstats.time += 10
        assert tune._step() is False and tune.handed_off
        assert any('stalled' in m for m in agent.logs)


# ---------------------------------------------------------------- the walk: the survival layers take a fight
def test_walk_yields_to_a_hostile_next_to_us():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(pos=(-2, 8))
        assert tune.active()
        T.put_monster(agent, (-3, 8), 'horse', _glyph('horse'))
        assert not tune.active() and tune._yielding and not tune.done
        assert any('yielding' in m for m in agent.logs)
        T.clear_monsters(agent)
        assert tune.active() and not tune._yielding
    # a peaceful one is no reason
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(pos=(-2, 8))
        T.put_monster(agent, (-3, 8), 'watchman', _glyph('watchman'))
        y, x = to_bot(-3, 8)
        agent.monster_tracker.peaceful_monster_mask[y, x] = True
        assert tune.active()
    # on the tune square the lane keeps the fight (Elbereth, the crusher, the aborts)
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(pos=(4, 7))
        T.put_monster(agent, (3, 7), 'hill orc', _glyph('hill orc'))
        assert tune.active()
    # resting at the camp: the camp's own fight
    with flags(CASTLE_PASSTUNE=True, CASTLE_BASECAMP=True):
        agent, dive, tune = B.setup(pos=(3, 8))
        tune.camping = True
        T.put_monster(agent, (2, 8), 'hill orc', _glyph('hill orc'))
        assert tune.active()
    with flags(CASTLE_PASSTUNE=True, PT_V2=False):
        agent, dive, tune = T.setup(pos=(-2, 8))
        T.put_monster(agent, (-3, 8), 'horse', _glyph('horse'))
        assert tune.active()


def test_walk_turn_budget():
    with flags(CASTLE_PASSTUNE=True, PT_GO_TURNS=100):
        agent, dive, tune = T.setup(pos=(-6, 8))
        assert tune._step() is True and tune._pos() == (-5, 8)     # walking
        agent.blstats.time += 101
        assert tune._step() is False and tune.done and 'not reached in 100 turns' in tune.reason
    with flags(CASTLE_PASSTUNE=True, PT_GO_TURNS=100, PT_V2=False):
        agent, dive, tune = T.setup(pos=(-6, 8))
        assert tune._step() is True
        agent.blstats.time += 101
        assert tune._step() is True and not tune.done


# ---------------------------------------------------------------- the hand-over after a quiet crusher
def test_quiet_handoff_skips_the_maze_mouth_hold():
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(tune='DGABE')
        front = dive.front
        tune.handed_off = True
        tune.quiet_end = True
        assert front._tune_quiet()
        calls = []
        front._advance = lambda target, nxt: calls.append((target, nxt)) or True
        assert front._hold_v3() is True
        assert calls == [(cfront.HALL_HOLD, 1)] and front.hold_over and front.lures == cfront.MAX_LURES
        assert any('M:inside' in m and 'quiet' in m for m in agent.logs)
        # a retreat later goes back to the hold as before (the skip is used once)
        front.hold_over = False
        front._go = lambda p, why: calls.append(('go', p)) or True
        front._hold_v3()
        assert calls[-1][0] == 'go'
    with flags(CASTLE_PASSTUNE=True):
        agent, dive, tune = T.setup(tune='DGABE')
        tune.handed_off = True
        tune.quiet_end = False                      # (a raise cap / turn budget ended it)
        assert not dive.front._tune_quiet()
    with flags(CASTLE_PASSTUNE=True, PT_V2=False):
        agent, dive, tune = T.setup(tune='DGABE')
        tune.handed_off = True
        tune.quiet_end = True
        assert not dive.front._tune_quiet()


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
