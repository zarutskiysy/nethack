"""Unit tests (fakes, no NetHack games) for VALLEY_DIVE (research/valley_dive.md).
Run from the repo root:  python tests/test_valley_dive.py"""
import os
import re
import sys

sys.path.insert(0, os.getcwd())

from nhbot import dive_logic as DL                            # noqa: E402
from nhbot import jf_config, valley                           # noqa: E402
from nhbot.valley_walk import ValleyWalker                    # noqa: E402

NLE_SRC = '/Users/semyon/.cache/uv/sdists-v9/pypi/nle/1.3.0/_0oztOvrHoWSPlUu/src'


class Recorder:
    """Any method the code under test calls on the fake dive: records the name, returns None (falsy)."""

    def __init__(self, calls, name):
        self._calls, self._name = calls, name

    def __call__(self, *a, **k):
        self._calls.append(self._name)
        return None

    def __getattr__(self, name):
        return Recorder(self._calls, f'{self._name}.{name}')


class BL:
    def __init__(self, depth, hp=40, maxhp=40):
        self.depth = depth
        self.hitpoints, self.max_hitpoints = hp, maxhp
        self.hunger_state = 0
        self.time = 5000
        self.y, self.x = 10, 40
        self.experience_level = 9


class Lvl:
    def __init__(self, dnum, dlevel):
        self.dungeon_number, self.level_number = dnum, dlevel

    def key(self):
        return (self.dungeon_number, self.level_number)


class NoGlobalLogic(Exception):
    pass


class FakeAgent:
    def __init__(self, dnum, dlevel, depth, monsters=()):
        self.level = Lvl(dnum, dlevel)
        self.blstats = BL(depth)
        self.monsters = list(monsters)
        self.logs = []
        self.searches = 0

    def current_level(self):
        return self.level

    def get_visible_monsters(self):
        return list(self.monsters)

    def log(self, msg):
        self.logs.append(msg)

    def search(self, n=1):
        self.searches += 1

    @property
    def global_logic(self):
        # should_dive's regular trigger reads the grind milestone: reaching it means the VALLEY_DIVE branch let go
        raise NoGlobalLogic()


class FakeDive:
    """The real DiveLogic methods under test, bound to this object; everything else is a Recorder."""
    plan_step = DL.DiveLogic.plan_step
    valley_dive_below = DL.DiveLogic.valley_dive_below
    gehennom_dive_step = DL.DiveLogic.gehennom_dive_step
    in_gehennom = DL.DiveLogic.in_gehennom
    in_valley = DL.DiveLogic.in_valley
    should_dive = DL.DiveLogic.should_dive
    gehennom_scare = DL.DiveLogic.gehennom_scare

    def __init__(self, agent):
        self.agent = agent
        self.calls = []
        self.undiggable = set()
        self._valley_misplaced = False
        self.diving = False
        self.tasks = []

    def __getattr__(self, name):
        return Recorder(self.__dict__['calls'], name)

    def _task(self, name):
        self.tasks.append(name)

    def descend(self):
        self.calls.append('descend')

    def valley_step(self):
        self.calls.append('valley_step')


def flags(**kw):
    for k, v in kw.items():
        setattr(jf_config, k, v)


DEFAULTS = dict(VALLEY_DIVE=jf_config.VALLEY_DIVE, VALLEY_DIVE_SCARE=jf_config.VALLEY_DIVE_SCARE,
                VALLEY_DIVE_MAX_DEPTH=jf_config.VALLEY_DIVE_MAX_DEPTH, VALLEY_WALK=jf_config.VALLEY_WALK,
                GEHENNOM_DIVE=jf_config.GEHENNOM_DIVE)


# ---------------------------------------------------------------- flags
def test_flag_default_off():
    assert DEFAULTS['VALLEY_DIVE'] is False
    assert DEFAULTS['VALLEY_DIVE_MAX_DEPTH'] == 50
    assert DEFAULTS['GEHENNOM_DIVE'] is True       # VALLEY_DIVE rides on the Gehennom dive's level tests
    assert DL.GEHENNOM in DL.MAIN_LINE              # try_dig_down digs Gehennom levels


# ---------------------------------------------------------------- should_dive
def test_should_dive_starts_in_gehennom():
    flags(VALLEY_DIVE=True)
    agent = FakeAgent(1, 1, 28)
    dive = FakeDive(agent)
    assert dive.should_dive() is True
    assert dive.diving and dive.mines_done and not dive.rescue and dive.dive_start_turn == 5000
    assert any('VALLEY_DIVE' in m for m in agent.logs)


def test_should_dive_flag_off_or_main_dungeon_unchanged():
    for on, dnum in ((False, 1), (True, 0)):
        flags(VALLEY_DIVE=on)
        dive = FakeDive(FakeAgent(dnum, 3 if dnum == 0 else 1, 28))
        try:
            dive.should_dive()
            assert 0, 'expected the regular trigger'
        except NoGlobalLogic:
            pass
        assert not dive.diving


# ---------------------------------------------------------------- plan_step routing
def test_plan_step_below_valley_goes_straight_to_descend():
    flags(VALLEY_DIVE=True)
    dive = FakeDive(FakeAgent(1, 5, 33))
    dive.plan_step()
    assert dive.calls[-1] == 'descend'
    for detour in ('should_fetch_digging_tool', 'should_explore_fully', 'prep_dive_pickup', 'should_farm',
                   'should_camp', 'should_search_dwarves', 'should_sweep_portal', 'castle.active'):
        assert detour not in dive.calls, (detour, dive.calls)
    assert dive.tasks[-1] == 'gehennom dig-dive'


def test_plan_step_flag_off_keeps_the_detours():
    flags(VALLEY_DIVE=False)
    dive = FakeDive(FakeAgent(1, 5, 33))
    dive.plan_step()
    assert dive.calls[-1] == 'descend'
    assert 'should_fetch_digging_tool' in dive.calls and 'should_explore_fully' in dive.calls
    assert 'gehennom dig-dive' not in dive.tasks


def test_plan_step_valley_keeps_valley_step():
    flags(VALLEY_DIVE=True)
    dive = FakeDive(FakeAgent(1, 1, 28))
    dive.plan_step()
    assert dive.calls == ['valley_step']


def test_plan_step_main_dungeon_unchanged():
    flags(VALLEY_DIVE=True)
    dive = FakeDive(FakeAgent(0, 12, 12))
    dive.plan_step()
    assert 'should_fetch_digging_tool' in dive.calls
    assert 'gehennom dig-dive' not in dive.tasks


def test_hurt_without_monsters_still_rests_first():
    """The plan's rest (no hostile in view, below REST_BELOW, not a Gehennom digger) stays above the dive step."""
    flags(VALLEY_DIVE=True)
    agent = FakeAgent(1, 5, 33)
    agent.blstats.hitpoints = 5
    dive = FakeDive(agent)
    dive.plan_step()
    assert dive.tasks == ['rest'] and agent.searches == 1 and 'descend' not in dive.calls


# ---------------------------------------------------------------- gehennom_dive_step
def test_dive_step_stops_at_dlvl_50():
    flags(VALLEY_DIVE=True)
    agent = FakeAgent(1, 22, 50)
    dive = FakeDive(agent)
    dive.gehennom_dive_step()
    assert 'descend' not in dive.calls and agent.searches == 1
    assert dive.tasks[-1].startswith('gehennom: Dlvl 50')
    flags(VALLEY_DIVE_MAX_DEPTH=60)
    dive = FakeDive(FakeAgent(1, 22, 50))
    dive.gehennom_dive_step()
    assert dive.calls[-1] == 'descend'


def test_dive_step_hard_floor_takes_the_stairs():
    """A Wizard's Tower level (hardfloor): try_dig_down marked it undiggable; descend() then finds the '>'."""
    flags(VALLEY_DIVE=True)
    dive = FakeDive(FakeAgent(1, 13, 40))
    dive.undiggable.add((1, 13))
    dive.gehennom_dive_step()
    assert dive.calls[-1] == 'descend' and dive.tasks[-1].startswith('gehennom: stairs')


def test_dive_step_logs_each_level_once():
    flags(VALLEY_DIVE=True)
    agent = FakeAgent(1, 6, 34)
    dive = FakeDive(agent)
    dive.gehennom_dive_step()
    dive.gehennom_dive_step()
    assert sum(m.startswith('GDIVE on Gehennom level 6') for m in agent.logs) == 1


# ---------------------------------------------------------------- the Valley walk and the scare hold
def test_walker_active_with_valley_dive():
    for walk, vdive, dlevel, want in ((False, True, 1, True), (False, False, 1, False), (True, False, 1, True),
                                      (False, True, 2, False)):
        flags(VALLEY_WALK=walk, VALLEY_DIVE=vdive)
        dive = FakeDive(FakeAgent(1, dlevel, 28))
        walker = ValleyWalker.__new__(ValleyWalker)
        walker.dive, walker.agent = dive, dive.agent
        assert walker.active() is want, (walk, vdive, dlevel)
    flags(VALLEY_WALK=False, VALLEY_DIVE=True)
    dive = FakeDive(FakeAgent(1, 1, 28))
    dive._valley_misplaced = True
    walker = ValleyWalker.__new__(ValleyWalker)
    walker.dive, walker.agent = dive, dive.agent
    assert walker.active() is False


def _scare_gate_passed(vdive, scare, dnum=1):
    flags(VALLEY_DIVE=vdive, VALLEY_DIVE_SCARE=scare)
    dive = FakeDive(FakeAgent(dnum, 5, 33))
    gen = dive.gehennom_scare().strategy()
    assert next(gen) is False         # nothing next to us: no drop either way
    return 'on_scare_scroll' in dive.calls


def test_scare_hold_gate():
    assert DL.GEHENNOM_SCARE is False
    assert _scare_gate_passed(True, True)
    assert not _scare_gate_passed(True, False)
    assert not _scare_gate_passed(False, True)
    assert not _scare_gate_passed(True, True, dnum=0)


# ---------------------------------------------------------------- the level files (verified in the NLE source)
def _des_levels(path):
    """{level name: FLAGS line} of a .des file."""
    out, name = {}, None
    for line in open(path, errors='replace'):
        m = re.match(r'MAZE:\s*"([^"]+)"', line)
        if m:
            name = m.group(1)
            out[name] = ''
        elif name and line.startswith('FLAGS:'):
            out[name] = line
    return out


def test_level_files_hardfloor_and_valley_stairs():
    if not os.path.isdir(NLE_SRC):
        print('  (NLE source not found: skipped)')
        return
    geh = _des_levels(f'{NLE_SRC}/dat/gehennom.des')
    yen = _des_levels(f'{NLE_SRC}/dat/yendor.des')
    hard = {n for n, f in list(geh.items()) + list(yen.items()) if 'hardfloor' in f}
    assert hard == {'valley', 'sanctum', 'wizard1', 'wizard2', 'wizard3'}, hard
    for n in ('juiblex', 'orcus', 'asmodeus', 'baalz', 'fakewiz1', 'fakewiz2'):
        assert n in geh or n in yen
    text = open(f'{NLE_SRC}/dat/gehennom.des').read()
    valley_part = text.split('MAZE: "valley"')[1].split('MAZE:')[0]
    assert 'STAIR:(01,01),down' in valley_part
    assert valley.DOWN_STAIRS == valley.bot(1, 1) == (2, 3)
    # Can_dig_down: hardfloor, the bottom level and the vibrating-square level only (dungeon.c)
    dun = open(f'{NLE_SRC}/src/dungeon.c').read()
    body = dun.split('Can_dig_down(lev)')[1].split('}')[0]
    assert 'hardfloor' in body and 'Is_botlevel' in body and 'Invocation_lev' in body
    # Elbereth is void in Gehennom (monmove.c onscary), prayer too (pray.c)
    assert '|| Inhell' in open(f'{NLE_SRC}/src/monmove.c').read().split('onscary(x, y, mtmp)')[1][:3000]
    assert 'Since you are in Gehennom' in open(f'{NLE_SRC}/src/pray.c').read()


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            flags(**DEFAULTS)
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
