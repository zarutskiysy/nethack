"""Unit tests (fakes, no game) for STAIRS_FIRST (nhbot/dive_logic.py: _stairs_first_level_ok, _stairs_first_target,
_stairs_first_safe, _stairs_first_go, _go_down, the hooks in dig_first and try_dig_down).

run: /Users/semyon/Nethack/dev/.venv/bin/python /Users/semyon/Nethack/stairs_first/tools/test_stairs_first.py
"""
import contextlib
import os
import sys

import numpy as np

WT = os.environ.get('STAIRS_FIRST_WT', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WT)

from nhbot import jf_config  # noqa: E402
from nhbot.character import Character  # noqa: E402
from nhbot.dive_logic import DiveLogic  # noqa: E402
from nhbot.glyph import MON, SS  # noqa: E402

ELF = MON.permonst(MON.from_name('Grey-elf'))
JACKAL = MON.permonst(MON.from_name('jackal'))
NEWT = MON.permonst(MON.from_name('newt'))
ANT = MON.permonst(MON.from_name('soldier ant'))
EYE = MON.permonst(MON.from_name('floating eye'))


class Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeLevel:
    def __init__(self, key, shape=(21, 79)):
        self._key = key
        self.dungeon_number, self.level_number = key
        self.objects = np.full(shape, SS.S_room, dtype=np.int16)
        self.walkable = np.ones(shape, dtype=bool)
        self.stair_destination = {}

    def key(self):
        return self._key


class FakeAgent:
    """Open level, Chebyshev BFS and straight paths; go_to takes max_steps steps (all if None); '>' changes level."""

    def __init__(self, level, y, x, hp=50, maxhp=50, time=5000, race=Character.HUMAN):
        self.level = level
        self.blstats = Obj(y=y, x=x, time=time, hitpoints=hp, max_hitpoints=maxhp, depth=level.level_number,
                           experience_level=8, hunger_state=1)
        self.character = Obj(race=race, prop=Obj(blind=False, confusion=False, stun=False, hallu=False))
        self.monsters = []          # (y, x, permonst)
        self.logs, self.moves = [], []
        self.step_count = 0

    def current_level(self):
        return self.level

    def log(self, s):
        self.logs.append(s)

    def bfs(self):
        h, w = self.level.objects.shape
        yy, xx = np.mgrid[0:h, 0:w]
        return np.maximum(abs(yy - self.blstats.y), abs(xx - self.blstats.x))

    def path(self, fy, fx, ty, tx, dis=None):
        out = [(fy, fx)]
        while (fy, fx) != (ty, tx):
            fy += int(np.sign(ty - fy))
            fx += int(np.sign(tx - fx))
            out.append((fy, fx))
        return out

    def neighbors(self, y, x, shuffle=True, diagonal=True):
        h, w = self.level.objects.shape
        return [(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                if (dy or dx) and 0 <= y + dy < h and 0 <= x + dx < w]

    def get_visible_monsters(self):
        dis = self.bfs()
        return sorted((int(dis[y, x]), y, x, p, 0) for y, x, p in self.monsters)

    def go_to(self, y, x, stop_one_before=False, max_steps=None, **kw):
        b = self.blstats
        steps = 0
        while (b.y, b.x) != (y, x) and (max_steps is None or steps < max_steps):
            ny, nx = b.y + int(np.sign(y - b.y)), b.x + int(np.sign(x - b.x))
            if stop_one_before and (ny, nx) == (y, x):
                break
            b.y, b.x = ny, nx
            b.time += 1
            steps += 1
            self.moves.append(('step', b.y, b.x))

    def move(self, d):
        self.moves.append(d)
        k = self.level.key()
        self.level = FakeLevel((k[0], k[1] + (1 if d == '>' else -1)))
        self.blstats.depth = self.level.level_number
        self.blstats.time += 1
        self.monsters = []


def make_dive(agent, medusa=None):
    d = object.__new__(DiveLogic)
    d.agent = agent
    d.diving = True
    d.medusa_level = medusa
    d._avoid_stairs_until = {}
    d._crowd_retreats = {}
    d._dead_traps = set()
    d._dig_tries = {}
    d._arrived = None
    d._arrival_pending = None
    d._pit_at = None
    d._last_task = None
    d.level_first_turn = {}
    d.undiggable = set()
    d._dig_blocked_until = -1
    d.castle = Obj(active=lambda: False)
    d.in_valley = lambda: False
    d._raven_level_below = lambda: False
    d.levitating = lambda: False
    d.rested = []
    d.rest_if_hurt = lambda: d.rested.append(1) or False
    return d


@contextlib.contextmanager
def flags(**kw):
    old = {k: getattr(jf_config, k) for k in kw}
    for k, v in kw.items():
        setattr(jf_config, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(jf_config, k, v)


def scene(depth=12, me=(10, 40), down=None, trap=None, medusa=None, race=Character.HUMAN):
    lvl = FakeLevel((0, depth))
    if down is not None:
        lvl.objects[down] = SS.S_dnstair
    if trap is not None:
        lvl.objects[trap] = SS.S_trap_door
    a = FakeAgent(lvl, *me, race=race)
    return a, make_dive(a, medusa)


ON = dict(STAIRS_FIRST=True, STAIRS_FIRST_MAX_STEPS=12, STAIRS_FIRST_MIN_DEPTH=5, STAIRS_FIRST_TRAPS=True)


def test_off_does_nothing():
    a, d = scene(down=(10, 45))
    with flags(STAIRS_FIRST=False):
        assert not d._stairs_first_level_ok()
        assert d._stairs_first_target() is None


def test_radius():
    with flags(**ON):
        a, d = scene(down=(10, 52))            # 12 steps
        assert d._stairs_first_target() == (12, 10, 52, 'stairs')
        a, d = scene(down=(10, 53))            # 13 steps
        assert d._stairs_first_target() is None
    with flags(**dict(ON, STAIRS_FIRST_MAX_STEPS=20)):
        a, d = scene(down=(10, 53))
        assert d._stairs_first_target()[0] == 13


def test_dig_started():
    with flags(**ON):
        a, d = scene(down=(10, 45))
        d._dig_tries[(0, 12)] = 1
        assert d._stairs_first_target() is None
        a, d = scene(down=(10, 45))
        d._pit_at = ((0, 12), (10, 40))
        assert d._stairs_first_target() is None
        d._pit_at = ((0, 11), (10, 40))       # a pit on another level doesn't count
        assert d._stairs_first_target() is not None


def test_level_guards():
    with flags(**ON):
        assert scene(depth=19, down=(10, 45))[1]._stairs_first_target() is not None
        assert scene(depth=20, down=(10, 45))[1]._stairs_first_target() is None   # below may be Medusa's (21)
        assert scene(depth=21, down=(10, 45), medusa=(0, 23))[1]._stairs_first_target() is not None
        assert scene(depth=22, down=(10, 45), medusa=(0, 23))[1]._stairs_first_target() is None
        assert scene(depth=23, down=(10, 45), medusa=(0, 23))[1]._stairs_first_target() is None
        assert scene(depth=4, down=(10, 45))[1]._stairs_first_target() is None      # Mines branch zone
        assert scene(down=(10, 45), race=Character.DWARF)[1]._stairs_first_target() is None
        a, d = scene(down=(10, 45))
        a.level.dungeon_number = 2   # the Mines
        assert d._stairs_first_target() is None
        a, d = scene(down=(10, 45))
        a.character.prop.blind = True
        assert d._stairs_first_target() is None
        a, d = scene(down=(10, 45))
        d.castle = Obj(active=lambda: True)
        assert d._stairs_first_target() is None
        a, d = scene(down=(10, 45))
        d._avoid_stairs_until[((0, 12), (10, 45))] = 10 ** 9   # a '>' we came back up by
        assert d._stairs_first_target() is None
        a, d = scene(down=(10, 45))
        a.level.stair_destination[(10, 45)] = ((2, 3), (5, 5))  # known to lead into the Mines
        assert d._stairs_first_target() is None


def test_hostiles():
    with flags(**ON):
        a, d = scene(down=(10, 46))
        a.monsters = [(10, 41, NEWT)]                          # adjacent: no walk
        assert d._stairs_first_target() is None
        a.monsters = [(10, 41, EYE)]                           # passive: ignored
        assert d._stairs_first_target() is not None
        a.monsters = [(10, 30, JACKAL)]                        # 10 behind us, the '>' 6 ahead
        assert d._stairs_first_target() is not None
        a.monsters = [(14, 44, ANT)]                           # (speed 18) 4 off the middle of the path
        assert d._stairs_first_target() is None
        a.monsters = [(10, 52, ELF)]                           # an elf 6 beyond the '>' (we need 6): too close
        assert d._stairs_first_target() is None
        a.monsters = [(10, 56, ELF)]                           # 10 beyond: we are there first
        assert d._stairs_first_target() is not None
        a.monsters = [(10, 56, JACKAL)]
        assert d._stairs_first_target() is not None


def test_trap_door():
    with flags(**ON):
        a, d = scene(trap=(10, 46))
        t = d._stairs_first_target()
        assert t == (6, 10, 46, 'trap'), t
        d._dead_traps.add(((0, 12), (10, 46)))
        assert d._stairs_first_target() is None
    with flags(**dict(ON, STAIRS_FIRST_TRAPS=False)):
        a, d = scene(trap=(10, 46))
        assert d._stairs_first_target() is None
    with flags(**ON):
        a, d = scene(trap=(10, 46), down=(10, 50))             # the nearer one first
        assert d._stairs_first_target()[3] == 'trap'
        a.monsters = [(12, 47, JACKAL)]                        # next to the trap door: the '>' is clear? no, both
        assert d._stairs_first_target() is None


def test_go_quiet_and_escape():
    with flags(**ON):
        a, d = scene(down=(10, 45))
        t = d._stairs_first_target()
        d._stairs_first_go(t)                                  # quiet: walks the whole way
        assert (a.blstats.y, a.blstats.x) == (10, 45) and a.level.key() == (0, 12)
        d._stairs_first_go(d._stairs_first_target())           # on it: rest check, then down
        assert a.moves[-1] == '>' and a.level.key() == (0, 13) and d.rested
        assert any(s.startswith('STAIRS_FIRST stairs at (10, 45)') for s in a.logs)
        assert d._arrived[2] == ((0, 12), (10, 45))
        assert ((0, 12), (10, 45)) not in d._crowd_retreats
        a, d = scene(down=(10, 45))
        a.monsters = [(10, 30, JACKAL)]
        d._stairs_first_go(d._stairs_first_target(), escape=True)   # hostiles: one step per call
        assert (a.blstats.y, a.blstats.x) == (10, 41)
        a.blstats.x = 45
        d._stairs_first_go(d._stairs_first_target(), escape=True)
        assert a.moves[-1] == '>' and not d.rested and d._crowd_retreats[((0, 12), (10, 45))] == 1


def _dig_first_dive(a, d):
    d.prep_mid_level = lambda: False
    d._blind_dig_due = lambda: False
    d.digging_tool = lambda: Obj(object=None, text='a pick-axe')
    d.should_sweep_portal = lambda: False
    d._escape_next = lambda: ('dig', None)
    d.acted = []
    d._escape_act = lambda act: d.acted.append(act)
    return d


def test_dig_first_hook():
    with flags(**ON):
        a, d = scene(down=(10, 45))
        _dig_first_dive(a, d)
        a.monsters = [(10, 30, JACKAL)]
        assert d.dig_first().run(return_condition=True)
        assert (a.blstats.y, a.blstats.x) == (10, 41) and not d.acted
        a.monsters = [(10, 42, JACKAL)]                        # it caught up: the usual dig-out
        assert d.dig_first().run(return_condition=True)
        assert d.acted and (a.blstats.y, a.blstats.x) == (10, 41)
    with flags(**dict(ON, STAIRS_FIRST=False)):
        a, d = scene(down=(10, 45))
        _dig_first_dive(a, d)
        a.monsters = [(10, 30, JACKAL)]
        assert d.dig_first().run(return_condition=True)
        assert d.acted and (a.blstats.y, a.blstats.x) == (10, 40)   # flag off: digs as before


if __name__ == '__main__':
    tests = [v for k, v in sorted(globals().items()) if k.startswith('test_')]
    for t in tests:
        t()
        print('ok', t.__name__)
    print(f'{len(tests)} passed')
