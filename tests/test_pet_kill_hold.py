"""Unit tests (fakes, no NetHack game) for PET_KILL_PRAYER_HOLD in nhbot (research/ports4.md; DT6A 751f31d).

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_pet_kill_hold.py

After 'You hear the rumble of distant thunder...' (our pet killed by us: mon.c xkilled) every prayer but the certain-death
ones waits PET_KILL_PRAYER_HOLD_TURNS turns. The last tests document how this compares with the prayer model, which already
reads the same message.
"""
import contextlib
import json
import os
import re
import subprocess
import sys
import types

sys.path.insert(0, os.getcwd())

from nhbot import jf_config                        # noqa: E402
from nhbot.agent import Agent                      # noqa: E402
from nhbot.character import Character             # noqa: E402
from nhbot.dive_logic import DiveLogic             # noqa: E402
from nhbot.nhmodel.prayer import PrayerModel       # noqa: E402

THUNDER = 'You kill the poor little dog!  You hear the rumble of distant thunder...'
APPLAUSE = 'You kill the poor kitten!  You hear the studio audience applaud!'


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


class FakeAgent:
    """Enough of nhbot.agent.Agent for DiveLogic._pet_kill_hold and Agent.is_safe_to_pray."""
    PRAYER_FAILURE_WAIT = Agent.PRAYER_FAILURE_WAIT
    is_safe_to_pray = Agent.is_safe_to_pray
    _prayer_model_gate = Agent._prayer_model_gate
    _prayer_model_active = Agent._prayer_model_active
    _prayer_model_error = Agent._prayer_model_error
    _prayer_holds_ok = Agent._prayer_holds_ok

    def __init__(self, time=700, role=Character.TOURIST, alignment=1):
        self.blstats = types.SimpleNamespace(time=time, hitpoints=20, max_hitpoints=30, experience_level=4,
                                             hunger_state=1, prop_mask=0)
        self.character = types.SimpleNamespace(role=role, alignment=alignment)
        self._message_history = []
        self.message = ''
        self.prayer_hold_until = -1
        self.prayer_failed = False
        self.last_prayer_turn = None
        self.step_count = 0
        self.logs = []
        self.prayer_model = None

    def current_level(self):
        return types.SimpleNamespace(dungeon_number=0)

    def log(self, msg):
        self.logs.append(msg)

    def see(self, *messages):
        """One step per message (update_message_and_popup appends each step's message to the history)."""
        for m in messages:
            self.message = m
            self._message_history.append(m)
            self.step_count += 1


class FakeDive(DiveLogic):
    def __init__(self, agent):
        self.agent = agent


def hold(agent, dive=None):
    dive = dive or FakeDive(agent)
    with flags(PET_KILL_PRAYER_HOLD=True):
        dive._pet_kill_hold(agent.blstats.time)
    return dive


def test_flag_defaults():
    assert jf_config.PET_KILL_PRAYER_HOLD is False
    assert jf_config.PET_KILL_PRAYER_HOLD_TURNS == 3000


def test_update_calls_the_hook_only_under_the_flag():
    import inspect
    import nhbot.dive_logic as module
    text = open(inspect.getsourcefile(module)).read()
    start = text.index('    def update(self):')
    body = text[start:text.index('\n    def ', start + 10)]
    assert body.count('_pet_kill_hold(') == 1
    assert re.search(r'if jf_config\.PET_KILL_PRAYER_HOLD:\n\s+self\._pet_kill_hold\(turn\)', body)
    assert text.count('_pet_kill_hold(') == 2          # the call and the def


def test_thunder_holds_prayers():
    agent = FakeAgent(time=721)
    agent.see('You throw 2 darts.', THUNDER, 'You see here a little dog corpse.')
    hold(agent)
    assert agent.prayer_hold_until == 721 + 3000
    assert any(m.startswith('PET KILL') for m in agent.logs)


def test_applause_while_hallucinating():
    agent = FakeAgent(time=900)
    agent.see(APPLAUSE)
    hold(agent)
    assert agent.prayer_hold_until == 3900


def test_turns_are_configurable():
    agent = FakeAgent(time=900)
    agent.see(THUNDER)
    with flags(PET_KILL_PRAYER_HOLD_TURNS=600):
        hold(agent)
    assert agent.prayer_hold_until == 1500


def test_each_message_counts_once():
    agent = FakeAgent(time=700)
    agent.see(THUNDER)
    dive = hold(agent)
    agent.blstats.time = 800
    agent.see('You hit the jackal!')
    hold(agent, dive)
    assert agent.prayer_hold_until == 3700             # not moved to 3800 by the old thunder
    agent.blstats.time = 2000
    agent.see('You kill poor Slasher!  You hear the rumble of distant thunder...')
    hold(agent, dive)
    assert agent.prayer_hold_until == 5000


def test_a_longer_hold_is_kept():
    agent = FakeAgent(time=700)
    agent.prayer_hold_until = 9000                     # e.g. 'You murderer!' holds stacked up
    agent.see(THUNDER)
    hold(agent)
    assert agent.prayer_hold_until == 9000


def test_no_hold_without_the_message():
    agent = FakeAgent(time=700)
    agent.see('You kill the jackal!', 'You hear a nearby thunderclap.', 'The little dog is killed!')
    hold(agent)
    assert agent.prayer_hold_until == -1 and not agent.logs


def test_fresh_history_after_a_driver_restart():
    agent = FakeAgent(time=700)
    agent.see(*['x'] * 10)
    dive = hold(agent)
    agent._message_history = []                        # a new agent object took over: its history starts empty
    agent.see(THUNDER)
    hold(agent, dive)
    assert agent.prayer_hold_until == 3700


def test_is_safe_to_pray_holds_all_but_certain_death():
    agent = FakeAgent(time=700)
    agent.see(THUNDER)
    hold(agent)
    agent.blstats.time = 3699
    assert not agent.is_safe_to_pray(500)
    assert agent.is_safe_to_pray(100, certain_death=True)
    agent.blstats.time = 3700
    assert agent.is_safe_to_pray(500)


# ------------------------------------------------------------------ the prayer model already reads the message


def _model(agent, record):
    model = PrayerModel(agent)
    model.record = record
    model.timeout_kind, model.timeout_turn = 'pleased', 1     # long past: the timeout is no issue
    agent.prayer_model = model
    model.observe()
    return model


def _step(agent, model, time, message=''):
    agent.blstats.time = time
    agent.see(message)
    model.observe()


def test_model_without_the_hold_lawful_high_record():
    """A lawful hero with a high record: the model blocks prayers while Luck is -1 and allows them again once Luck has
    timed out (the next multiple of 600 turns), where pray.c answers them. The hold would keep them blocked."""
    agent = FakeAgent(time=700, role=Character.KNIGHT, alignment=2)
    model = _model(agent, record=30)
    _step(agent, model, 721, THUNDER)
    assert model.record == 15 and model.naughty() == 1.0
    assert not agent.is_safe_to_pray(500)
    _step(agent, model, 1200)
    assert model.naughty() == 0.0 and agent.is_safe_to_pray(500)
    # the hold, had it been on at T721, would keep this answerable prayer blocked until T3721
    agent.prayer_hold_until = 721 + jf_config.PET_KILL_PRAYER_HOLD_TURNS
    assert not agent.is_safe_to_pray(500)


def test_model_misses_a_neutral_heros_pet_malign():
    """A neutral hero (Tourist): the pet's malign (-9: an alignment-0 pet is coaligned) is not in the model, so with a
    record of 20 before the kill the model's estimate is 5 (prayers allowed after Luck times out) while pray.c sees -4."""
    agent = FakeAgent(time=700, role=Character.TOURIST, alignment=1)
    model = _model(agent, record=20)
    _step(agent, model, 721, THUNDER)
    assert model.record == 5
    _step(agent, model, 1200)
    assert model.naughty() == 0.0 and agent.is_safe_to_pray(500)   # the model would pray: pray.c p_type 1, it fails
    with flags(PET_KILL_PRAYER_HOLD=True):
        agent2 = FakeAgent(time=721, role=Character.TOURIST, alignment=1)
        model2 = _model(agent2, record=20)
        agent2.see(THUNDER)
        model2.observe()
        FakeDive(agent2)._pet_kill_hold(721)
        _step(agent2, model2, 1200)
        assert not agent2.is_safe_to_pray(500)         # the hold keeps it off until 3721
        _step(agent2, model2, 3721)
        assert agent2.is_safe_to_pray(500)


# ------------------------------------------------------------------ configuration


def test_jf_cfg_and_jf_role_cfg_reach_the_flag():
    code = ('import sys; sys.path.insert(0, "."); import roles; from nhbot import jf_config as n; '
            'print(n.PET_KILL_PRAYER_HOLD, n.PET_KILL_PRAYER_HOLD_TURNS); roles.apply("tou-hum-neu-mal"); '
            'print(n.PET_KILL_PRAYER_HOLD, n.PET_KILL_PRAYER_HOLD_TURNS)')

    def run(**env):
        full = {k: v for k, v in os.environ.items() if k not in ('JF_CFG', 'JF_ROLE_CFG')}
        full.update({k: json.dumps(v) for k, v in env.items()})
        return subprocess.run([sys.executable, '-c', code], env=full, capture_output=True, text=True,
                              check=True).stdout.split()

    assert run(JF_CFG={'PET_KILL_PRAYER_HOLD': True}) == ['True', '3000', 'True', '3000']
    assert run(JF_ROLE_CFG={'tou': {'jf_config.PET_KILL_PRAYER_HOLD': True,
                                    'jf_config.PET_KILL_PRAYER_HOLD_TURNS': 1200}}) == ['False', '3000', 'True', '1200']
    assert run(JF_ROLE_CFG={'wiz': {'jf_config.PET_KILL_PRAYER_HOLD': True}}) == ['False', '3000', 'False', '3000']


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
