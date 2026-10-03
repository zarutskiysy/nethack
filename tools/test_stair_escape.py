"""Unit tests (fakes, no game) for the middive flags STAIR_ESCAPE (+ STAIR_ESCAPE_DOWN) and AT_STAIRS
(nhbot/dive_logic.py retreat_upstairs, _escape_down_target, _post_prayer_engaged, _at_stairs_plan, _stair_escape_down).

run: /Users/semyon/Nethack/dev/.venv/bin/python /Users/semyon/Nethack/research/middive/test_stair_escape.py
"""
import contextlib
import os
import sys

import numpy as np

WT = os.environ.get('MIDDIVE_WT', '/Users/semyon/Nethack/middive')
sys.path.insert(0, WT)

from nhbot import jf_config  # noqa: E402
from nhbot.dive_logic import DiveLogic  # noqa: E402
from nhbot.glyph import MON, SS  # noqa: E402

ELF = MON.permonst(MON.from_name('Grey-elf'))
SOLDIER = MON.permonst(MON.from_name('soldier'))
NEWT = MON.permonst(MON.from_name('newt'))


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
    """Open level, Chebyshev BFS; go_to takes one step; '>'/'<' change the level."""

    def __init__(self, level, y, x, hp=50, maxhp=50, time=5000):
        self.level = level
        self.blstats = Obj(y=y, x=x, time=time, hitpoints=hp, max_hitpoints=maxhp, depth=level.level_number,
                           experience_level=7, hunger_state=1)
        self.monsters = []          # (y, x, permonst)
        self.last_prayer_turn = None
        self.prayer_failed = False
        self.logs, self.moves = [], []
        self.chase = True

    def current_level(self):
        return self.level

    def log(self, s):
        self.logs.append(s)

    def bfs(self):
        h, w = self.level.objects.shape
        yy, xx = np.mgrid[0:h, 0:w]
        return np.maximum(abs(yy - self.blstats.y), abs(xx - self.blstats.x))

    def get_visible_monsters(self):
        dis = self.bfs()
        return sorted((int(dis[y, x]), y, x, p, 0) for y, x, p in self.monsters)

    def go_to(self, y, x, max_steps=None, **kw):
        b = self.blstats
        b.y += int(np.sign(y - b.y))
        b.x += int(np.sign(x - b.x))
        b.time += 1
        self.moves.append(('step', b.y, b.x))
        if self.chase:   # the monsters follow, up to adjacent
            moved = []
            for my, mx, p in self.monsters:
                if max(abs(my - b.y), abs(mx - b.x)) > 1:
                    my, mx = my + int(np.sign(b.y - my)), mx + int(np.sign(b.x - mx))
                    if (my, mx) == (b.y, b.x):
                        my, mx = my - int(np.sign(b.y - my)), mx - int(np.sign(b.x - mx))
                moved.append((my, mx, p))
            self.monsters = moved

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
    d._retreat_blocked_until = -1
    d._avoid_stairs_until = {}
    d._crowd_retreats = {}
    d._arrived = None
    d._arrival_pending = None
    d._arrival_square = None
    d._stair_escape_arrival = None
    d._pit_at = None
    d._hp_history = []
    d._hurt_on_elbereth = -1
    d.castle = Obj(castle_key=None)
    d.in_valley = lambda: False
    d.xorn_buffer = lambda: False
    d._up_leads_to_medusa = lambda: False
    d._crowded_arrival = lambda: None
    d._dig_escape_action = lambda: None
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


def scene(depth=12, hp=50, me=(10, 40), down=None, up=None, medusa=None):
    lvl = FakeLevel((0, depth))
    if down is not None:
        lvl.objects[down] = SS.S_dnstair
    if up is not None:
        lvl.objects[up] = SS.S_upstair
    a = FakeAgent(lvl, *me, hp=hp)
    return a, make_dive(a, medusa)


def cond(d):
    return d.retreat_upstairs().check_condition()


def run_until_level_change(a, d, limit=20):
    key = a.level.key()
    for _ in range(limit):
        if a.level.key() != key:
            return True
        if not d.retreat_upstairs().run(return_condition=True):
            return False
    return a.level.key() != key


# ------------------------------------------------------------------ flags off: unchanged

def test_off_is_unchanged():
    with flags(STAIR_ESCAPE=False, AT_STAIRS=False):
        # hurt, an elf adjacent, only a '>' near: the old retreat knows only '<'
        a, d = scene(hp=10, down=(10, 43))
        a.monsters = [(10, 41, ELF)]
        assert not cond(d)
        # an answered prayer 5 turns ago at full HP with the elf adjacent and a '<' 8 away: no retreat (not in trouble)
        a, d = scene(hp=50, up=(10, 48))
        a.last_prayer_turn = a.blstats.time - 5
        a.monsters = [(10, 41, ELF)]
        assert not cond(d)
        # the old low-HP retreat to a '<' still works
        a, d = scene(hp=10, up=(10, 43))
        a.monsters = [(10, 41, ELF)]
        assert cond(d)
        assert run_until_level_change(a, d) and a.moves[-1] == '<'
        # AT_STAIRS off: no plan
        a, d = scene(hp=40, down=(10, 37))
        a.monsters = [(10, 47, ELF)]
        assert not cond(d)


# ------------------------------------------------------------------ STAIR_ESCAPE_DOWN

def test_down_when_hurt():
    with flags(STAIR_ESCAPE=True, STAIR_ESCAPE_DOWN=True):
        a, d = scene(hp=10, down=(10, 44))
        a.monsters = [(10, 41, ELF)]
        assert cond(d)
        assert run_until_level_change(a, d)
        assert a.moves[-1] == '>' and a.level.key() == (0, 13)
        assert d._stair_escape_arrival == ((0, 13), a.blstats.time)
        assert d._avoid_stairs_until[((0, 12), (10, 44))] > a.blstats.time   # not straight back down if we return
        assert d._crowd_retreats[((0, 12), (10, 44))] == 1                    # no crowd bounce back up
        assert any(s.startswith('STAIR_ESCAPE down') for s in a.logs)


def test_down_preferred_unless_up_much_closer():
    with flags(STAIR_ESCAPE=True, STAIR_ESCAPE_DOWN=True, STAIR_ESCAPE_DOWN_SLACK=3):
        a, d = scene(hp=10, down=(10, 45), up=(10, 42))     # '>' 5, '<' 2: within the slack -> down
        a.monsters = [(10, 39, ELF)]
        assert run_until_level_change(a, d) and a.moves[-1] == '>'
        a, d = scene(hp=10, down=(10, 47), up=(10, 41))     # '>' 7, '<' 1: up
        a.monsters = [(10, 39, ELF)]
        assert run_until_level_change(a, d) and a.moves[-1] == '<'


def test_never_onto_medusa():
    with flags(STAIR_ESCAPE=True, STAIR_ESCAPE_DOWN=True):
        # Medusa unknown: Dlvl 20 -> 21 could be hers (MEDUSA_MIN_DEPTH 21)
        a, d = scene(depth=20, hp=10, down=(10, 42))
        a.monsters = [(10, 41, ELF)]
        assert not cond(d)
        a, d = scene(depth=19, hp=10, down=(10, 42))
        a.monsters = [(10, 41, ELF)]
        assert cond(d)
        # Medusa known on Dlvl 15: from 14 no, from 13 yes, on/below her never
        for depth, want in ((13, True), (14, False), (15, False), (16, False)):
            a, d = scene(depth=depth, hp=10, down=(10, 42), medusa=(0, 15))
            a.monsters = [(10, 41, ELF)]
            assert cond(d) is want, depth


def test_min_depth_and_not_diving():
    with flags(STAIR_ESCAPE=True, STAIR_ESCAPE_DOWN=True, STAIR_ESCAPE_MIN_DEPTH=5):
        a, d = scene(depth=4, hp=10, down=(10, 42))
        a.monsters = [(10, 41, ELF)]
        assert not cond(d)
        a, d = scene(depth=12, hp=10, down=(10, 42))
        a.monsters = [(10, 41, ELF)]
        d.diving = False
        assert not cond(d)


def test_no_bounce_up_after_escape():
    with flags(STAIR_ESCAPE=True, STAIR_ESCAPE_DOWN=True, STAIR_ESCAPE_NO_BOUNCE=20):
        a, d = scene(hp=10, down=(10, 42))
        a.monsters = [(10, 41, ELF)]
        assert run_until_level_change(a, d)
        # arrived on Dlvl 13's '<' (the map shows us there: ARRIVAL_FIX's square), hurt, a soldier ant next to us
        d._arrival_square = (a.level.key(), (a.blstats.y, a.blstats.x))
        a.level.objects[a.blstats.y, a.blstats.x] = SS.S_upstair
        a.monsters = [(a.blstats.y, a.blstats.x + 1, MON.permonst(MON.from_name('soldier ant')))]
        assert not cond(d)
        a.blstats.time += 25    # after the window the old retreat is back
        assert cond(d)


# ------------------------------------------------------------------ post-prayer

def test_post_prayer_trigger():
    with flags(STAIR_ESCAPE=True, STAIR_ESCAPE_DOWN=True, STAIR_ESCAPE_PRAYED=40, STAIR_ESCAPE_REACH=15,
               STAIR_ESCAPE_PRAYED_HP=0.75):
        # full HP after the prayer, an elf adjacent, a '<' 10 away (beyond the old reach of 2): go
        a, d = scene(hp=50, up=(10, 50))
        a.last_prayer_turn = a.blstats.time - 5
        a.monsters = [(10, 41, ELF)]
        assert cond(d)
        assert run_until_level_change(a, d) and a.moves[-1] == '<' and a.level.key() == (0, 11)
        # a '>' 12 away instead: down
        a, d = scene(hp=50, down=(10, 52))
        a.last_prayer_turn = a.blstats.time - 5
        a.monsters = [(10, 41, ELF)]
        assert run_until_level_change(a, d) and a.moves[-1] == '>'
        # beyond STAIR_ESCAPE_REACH: no
        a, d = scene(hp=50, up=(10, 60))
        a.last_prayer_turn = a.blstats.time - 5
        a.monsters = [(10, 41, ELF)]
        assert not cond(d)
        # only a newt near at full HP: no; the same newt at 30/50: yes
        a, d = scene(hp=50, up=(10, 50))
        a.last_prayer_turn = a.blstats.time - 5
        a.monsters = [(10, 41, NEWT)]
        assert not cond(d)
        a.blstats.hitpoints = 30
        assert cond(d)
        # a failed prayer, or one too long ago: no
        a, d = scene(hp=50, up=(10, 50))
        a.monsters = [(10, 41, ELF)]
        a.last_prayer_turn = a.blstats.time - 5
        a.prayer_failed = True
        assert not cond(d)
        a.prayer_failed = False
        a.last_prayer_turn = a.blstats.time - 41
        assert not cond(d)


def test_post_prayer_respects_dig_escape_veto():
    with flags(STAIR_ESCAPE=True):
        # only Elbereth-respecters: the dig out under Elbereth (DIG_ESCAPE) still goes first
        a, d = scene(hp=30, up=(10, 50))
        a.last_prayer_turn = a.blstats.time - 5
        a.monsters = [(10, 41, NEWT)]
        d._dig_escape_action = lambda: ('dig', 'pick-axe')
        assert not cond(d)


# ------------------------------------------------------------------ AT_STAIRS

def test_at_stairs():
    with flags(AT_STAIRS=True, AT_STAIRS_RADIUS=8, STAIR_ESCAPE=False):
        # hurt, an elf 7 east, a '>' 3 west: go down
        a, d = scene(hp=40, down=(10, 37))
        a.chase = False   # (it stands off; the walk goes on from memory once it is out of range)
        a.monsters = [(10, 47, ELF)]
        plan = d._at_stairs_plan()
        assert plan is not None and plan[0] == (10, 37), plan
        assert cond(d)
        assert run_until_level_change(a, d) and a.moves[-1] == '>'
        # full HP and a lone elf: dig as usual
        a, d = scene(hp=50, down=(10, 37))
        a.monsters = [(10, 47, ELF)]
        assert d._at_stairs_plan() is None
        # ... but two of them: go
        a.monsters = [(10, 47, ELF), (11, 47, ELF)]
        assert d._at_stairs_plan() is not None
        # the '>' lies toward the elf: no
        a, d = scene(hp=40, down=(10, 43))
        a.monsters = [(10, 45, ELF)]
        assert d._at_stairs_plan() is None
        # the elf reaches us first (4 steps, the '>' 3): no
        a, d = scene(hp=40, down=(10, 37))
        a.monsters = [(10, 44, ELF)]
        assert d._at_stairs_plan() is None
        # already in our pit: the hole is the way out
        a, d = scene(hp=40, down=(10, 37))
        a.monsters = [(10, 47, ELF)]
        d._pit_at = ((0, 12), (10, 40))
        assert d._at_stairs_plan() is None
        # an Elbereth-respecter is no trigger; a soldier is
        a, d = scene(hp=40, down=(10, 37))
        a.monsters = [(10, 47, NEWT)]
        assert d._at_stairs_plan() is None
        a.monsters = [(10, 47, SOLDIER)]
        assert d._at_stairs_plan() is not None
        # never with the dig escape's veto in the way (it would dig a pit beside the coming elf)
        a.monsters = [(10, 47, ELF)]
        d._dig_escape_action = lambda: ('dig', 'pick-axe')
        assert cond(d)


if __name__ == '__main__':
    n = 0
    for name, f in sorted(globals().items()):
        if name.startswith('test_') and callable(f):
            f()
            n += 1
            print('ok', name)
    print(f'{n} tests passed')
