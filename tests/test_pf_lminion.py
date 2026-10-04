"""Unit tests (fakes, no NetHack game) for LMINION_ELBERETH in pf_s25p8 (research/ports4.md; competitor_scan4 C4).

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_pf_lminion.py

Port of nhbot's LMINION_ELBERETH (dive_logic._lawful_minion and its two uses): lawful minions (the A class, M2_MINION)
melee through Elbereth (monmove.c onscary: is_lminion), so the dive must not count them as scared.
"""
import contextlib
import json
import os
import subprocess
import sys
import types

import nle.nethack as nh

sys.path.insert(0, os.getcwd())

from pf_s25p8 import jf_config                     # noqa: E402
from pf_s25p8 import dive_logic as DL              # noqa: E402
from pf_s25p8.dive_logic import DiveLogic          # noqa: E402
from pf_s25p8.glyph import MON                     # noqa: E402

A_CLASS = ('couatl', 'Aleax', 'Angel', 'ki-rin', 'Archon')


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


def permonst(name):
    return nh.permonst(MON.id_from_name(name))


ALL_MONS = [nh.permonst(i) for i in range(nh.NUMMONS)]


class FakeAgent:
    def __init__(self, hp=10, max_hp=60, time=20000):
        self.blstats = types.SimpleNamespace(hitpoints=hp, max_hitpoints=max_hp, time=time, y=10, x=10)
        self.character = types.SimpleNamespace(prop=types.SimpleNamespace(blind=False, polymorph=False))
        self.inventory = types.SimpleNamespace(engraving_below_me='')
        self.step_count = 0
        self.prayer_failed = False
        self.logs = []
        self.actions = []
        self.near = []

    def current_level(self):
        return types.SimpleNamespace(dungeon_number=0, key=lambda: (0, 20))

    def can_engrave(self):
        return True

    def log(self, msg):
        self.logs.append(msg)

    def engrave(self, text):
        self.actions.append(('engrave', text))
        self.step_count += 1

    def search(self):
        self.actions.append(('search',))
        self.step_count += 1

    def get_visible_monsters(self):
        return self.near


class FakeDive(DiveLogic):
    """DiveLogic's own elbereth methods on a hand-made state (DiveLogic.__init__ is not run)."""

    def __init__(self, agent):
        self.agent = agent
        self._elbereth_resting = False
        self._hurt_on_elbereth = -10 ** 9
        self._hold_squares = set()

    def shot_recently(self):
        return False

    def _fast_hp_loss(self):
        return False

    def _dig_escape_action(self):
        return None


def near(*names):
    return [(1, 10, 11 + i, permonst(n), MON.from_name(n)) for i, n in enumerate(names)]


def rest_decision(names, on):
    agent = FakeAgent()
    agent.near = near(*names)
    dive = FakeDive(agent)
    with flags(LMINION_ELBERETH=on):
        gen = dive.elbereth_rest().strategy()
        return next(gen)


def old_melee_ignores(dive, mon):
    """integ's (v10c's) pf_s25p8 DiveLogic._melee_ignores_elbereth."""
    mlet = getattr(mon, 'mlet', '')
    cls = ord(mlet) if isinstance(mlet, str) and len(mlet) == 1 else -1
    name = getattr(mon, 'mname', '')
    if name == 'unknown':
        return dive.agent.blstats.time - dive._hurt_on_elbereth <= 3
    return cls == MON.S_HUMAN or name == 'minotaur'


def test_flag_defaults_off():
    assert jf_config.LMINION_ELBERETH is False
    from nhbot import jf_config as nhbot_cfg
    assert nhbot_cfg.LMINION_ELBERETH is True          # the source engine has it on


def test_lawful_minion_is_the_a_class():
    minions = sorted(p.mname for p in ALL_MONS if DiveLogic._lawful_minion(p))
    assert set(A_CLASS) <= set(minions), minions
    assert set(minions) - set(A_CLASS) <= {'high priest'}, minions   # an @ already: counted as an ignorer anyway
    for name in ('jackal', 'minotaur', 'soldier ant', 'titan', 'shopkeeper'):
        assert not DiveLogic._lawful_minion(permonst(name)), name
    assert not DiveLogic._lawful_minion(types.SimpleNamespace(mname='unknown'))   # no mflags2: not a minion


def test_same_helper_as_nhbot():
    from nhbot.dive_logic import DiveLogic as NhbotDive
    for p in ALL_MONS:
        assert DiveLogic._lawful_minion(p) == NhbotDive._lawful_minion(p), p.mname


def test_melee_ignores_off_is_the_old_function():
    dive = FakeDive(FakeAgent())
    unknown = types.SimpleNamespace(mname='unknown', mlet='I')
    with flags(LMINION_ELBERETH=False):
        for p in ALL_MONS + [unknown]:
            assert dive._melee_ignores_elbereth(p) == old_melee_ignores(dive, p), p.mname
        dive._hurt_on_elbereth = dive.agent.blstats.time - 1
        assert dive._melee_ignores_elbereth(unknown) is old_melee_ignores(dive, unknown) is True


def test_melee_ignores_on_adds_the_minions_only():
    dive = FakeDive(FakeAgent())
    with flags(LMINION_ELBERETH=True):
        for p in ALL_MONS:
            want = old_melee_ignores(dive, p) or p.mname in A_CLASS
            assert dive._melee_ignores_elbereth(p) == want, p.mname
        # an unseen attacker keeps its own rule (no mflags2 to read)
        unknown = types.SimpleNamespace(mname='unknown', mlet='I')
        assert dive._melee_ignores_elbereth(unknown) is False


def test_rest_next_to_an_archon():
    """Archon is the one A not in RANGED_MONSTERS: the old rest held Elbereth next to it."""
    assert 'Archon' not in DL.RANGED_MONSTERS and 'couatl' in DL.RANGED_MONSTERS
    assert rest_decision(['Archon'], False) is True
    assert rest_decision(['Archon'], True) is False
    assert rest_decision(['soldier ant', 'Archon'], True) is False


def test_rest_otherwise_unchanged():
    for names in (['soldier ant'], ['soldier ant', 'jackal'], ['couatl'], ['Aleax', 'soldier ant'], ['minotaur'],
                  ['newt']):
        assert rest_decision(names, False) == rest_decision(names, True), names
    assert rest_decision(['soldier ant'], True) is True
    assert rest_decision(['couatl'], False) is False      # RANGED_MONSTERS already kept it off the rest


def test_jf_cfg_reaches_the_flag():
    code = ('import sys; sys.path.insert(0, "."); from pf_s25p8 import jf_config as j; from nhbot import jf_config as n; '
            'print(j.LMINION_ELBERETH, n.LMINION_ELBERETH)')
    env = dict(os.environ, JF_CFG=json.dumps({'LMINION_ELBERETH': True}))
    env.pop('JF_ROLE_CFG', None)
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True).stdout
    assert out.split() == ['True', 'True'], out


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
