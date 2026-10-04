"""Unit tests (fakes, no NetHack game) for KNI_FEYE_TELE in pf_s25p8 (research/ports4.md; daglar bcc73f3 / eL1fe bd8cb7c).

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_kni_feye.py

fight2 asks Agent._feye_tele_on() whether FEYE_TELE's rule set (never melee a visible floating eye except blindfolded or
boxed in) is on. Before this port that was 'FEYE_TELE and not FEYE_FIX and telepathic'; with KNI_FEYE_TELE a Knight gets
it from the start of the game.
"""
import contextlib
import inspect
import itertools
import os
import sys
import types

sys.path.insert(0, os.getcwd())

from pf_s25p8 import jf_config                    # noqa: E402
from pf_s25p8.agent import Agent                  # noqa: E402
from pf_s25p8.character import Character          # noqa: E402


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


def fake(role, telepathic):
    return types.SimpleNamespace(character=types.SimpleNamespace(role=role, telepathic=telepathic))


ROLES = [None, Character.KNIGHT, Character.VALKYRIE, Character.BARBARIAN, Character.WIZARD]


def old_rule(agent):
    return jf_config.FEYE_TELE and not jf_config.FEYE_FIX and agent.character.telepathic


def test_flag_defaults_off():
    assert jf_config.KNI_FEYE_TELE is False


def test_off_is_the_old_expression():
    """KNI_FEYE_TELE off: the helper returns exactly the old inline expression (same value, same type) for every role,
    telepathy and FEYE_TELE / FEYE_FIX setting."""
    for role, tele, ft, ff in itertools.product(ROLES, (False, True), (False, True), (False, True)):
        with flags(KNI_FEYE_TELE=False, FEYE_TELE=ft, FEYE_FIX=ff):
            a = fake(role, tele)
            got, want = Agent._feye_tele_on(a), old_rule(a)
            assert got is want or got == want and type(got) is type(want), (role, tele, ft, ff, got, want)


def test_on_knight_without_telepathy():
    with flags(KNI_FEYE_TELE=True, FEYE_TELE=True, FEYE_FIX=False):
        assert Agent._feye_tele_on(fake(Character.KNIGHT, False)) is True
        assert Agent._feye_tele_on(fake(Character.KNIGHT, True)) is True


def test_on_other_roles_unchanged():
    with flags(KNI_FEYE_TELE=True, FEYE_TELE=True, FEYE_FIX=False):
        for role in ROLES:
            if role == Character.KNIGHT:
                continue
            assert not Agent._feye_tele_on(fake(role, False)), role
            assert Agent._feye_tele_on(fake(role, True)), role


def test_on_needs_feye_tele_and_no_feye_fix():
    """The donor's rule keeps FEYE_TELE's preconditions: with FEYE_TELE off or FEYE_FIX on (FEYE_FIX filters every eye
    melee by itself) a Knight is not switched to the FEYE_TELE rules."""
    with flags(KNI_FEYE_TELE=True, FEYE_TELE=False, FEYE_FIX=False):
        assert not Agent._feye_tele_on(fake(Character.KNIGHT, False))
    with flags(KNI_FEYE_TELE=True, FEYE_TELE=True, FEYE_FIX=True):
        assert not Agent._feye_tele_on(fake(Character.KNIGHT, False))
        assert not Agent._feye_tele_on(fake(Character.KNIGHT, True))


def _method_source(module, name):
    """The text of `def name(self...)` in the module file, up to the next method (fight2 is wrapped by decorators
    that hide its code from inspect)."""
    text = open(inspect.getsourcefile(module)).read()
    start = text.index(f'    def {name}(self')
    ends = [i for i in (text.find('\n    def ', start + 10), text.find('\n    @', start + 10)) if i != -1]
    return text[start:min(ends)]


def test_fight2_uses_the_helper():
    import pf_s25p8.agent as agent_module
    src = _method_source(agent_module, 'fight2')
    assert 'yielded = False' in src and 'FEYE_TELE boxed in' in src   # the right method
    assert src.count('feye_tele = self._feye_tele_on()') == 1
    assert 'self.character.telepathic' not in src


def test_jf_cfg_reaches_the_flag():
    """JF_CFG is read at import, and only for names defined above the reader (globals())."""
    import json
    import subprocess
    code = ('import sys; sys.path.insert(0, "."); from pf_s25p8 import jf_config as j; '
            'from nhbot import jf_config as n; print(j.KNI_FEYE_TELE, hasattr(n, "KNI_FEYE_TELE"))')
    env = dict(os.environ, JF_CFG=json.dumps({'KNI_FEYE_TELE': True}))
    out = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, check=True).stdout
    assert out.split() == ['True', 'False'], out


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
