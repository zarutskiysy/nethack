"""Unit tests (fakes, no NetHack game) for SHOP_MASK_FIX in nhbot (research/ports4.md; eL1fe bd8cb7c, competitor_scan4 C2b).

Run from the repo root:  /Users/semyon/Nethack/dev/.venv/bin/python tests/test_shop_mask.py

Map: a lit shop (floor rows 5-7, cols 10-14) with its doorway at (6, 15) and the shopkeeper just inside it at (6, 14). We
stand in the corridor (6, 16..30) and have never seen the wall squares beside the door, (5, 15) and (7, 15). The old fill
does not see the door as an 'entry' and floods the corridor; the fix stops at the door.
"""
import contextlib
import json
import os
import random
import subprocess
import sys
import types

import numpy as np

sys.path.insert(0, os.getcwd())

from nhbot import jf_config, utils                 # noqa: E402
from nhbot.agent import Agent                      # noqa: E402
from nhbot.combat import fight_heur                # noqa: E402
from nhbot.combat.fight_heur import FORCE_BOLT_MAX_RANGE   # noqa: E402
from nhbot.glyph import C, G, MON, SS              # noqa: E402
from nhbot.level import Level                      # noqa: E402

SHOPKEEPER = next(iter(G.SHOPKEEPER))
NEWT = MON.from_name('newt')


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


def paint(level, cells):
    """cells: {(y, x): glyph} remembered as agent.update_level does (floor/doors walkable, walls/closed doors not)."""
    for (y, x), g in cells.items():
        level.objects[y, x] = g
        level.seen[y, x] = True
        level.walkable[y, x] = g in G.FLOOR or g in G.DOOR_OPENED


def shop_map(door=SS.S_ndoor, walls_beside_door=False):
    cells = {}
    for x in range(9, 16):
        cells[(4, x)] = SS.S_hwall
        cells[(8, x)] = SS.S_hwall
    for y in range(5, 8):
        cells[(y, 9)] = SS.S_vwall
        cells[(y, 15)] = SS.S_vwall
        for x in range(10, 15):
            cells[(y, x)] = SS.S_room
    cells[(6, 15)] = door
    if not walls_beside_door:
        del cells[(5, 15)], cells[(7, 15)]
    for x in range(16, 31):
        cells[(6, x)] = SS.S_corr
    level = Level(0, 3)
    paint(level, cells)
    return level


class FakeShopAgent:
    _DIG_TOOL_REFUSED = Agent._DIG_TOOL_REFUSED
    _SHOP_DOORWAY = Agent._SHOP_DOORWAY
    _CORRIDOR = Agent._CORRIDOR

    def __init__(self, level, shopkeeper=(6, 14), pos=(6, 18), message=''):
        self.level = level
        self.message = message
        self.glyphs = np.full((C.SIZE_Y, C.SIZE_X), SS.S_stone, dtype=np.int16)
        self.glyphs[level.seen] = level.objects[level.seen]
        peaceful = np.zeros((C.SIZE_Y, C.SIZE_X), bool)
        if shopkeeper is not None:
            self.glyphs[shopkeeper] = SHOPKEEPER
            peaceful[shopkeeper] = True
        self.monster_tracker = types.SimpleNamespace(peaceful_monster_mask=peaceful)
        self.blstats = types.SimpleNamespace(y=pos[0], x=pos[1], time=500)

    def current_level(self):
        return self.level

    def neighbors(self, y, x, shuffle=True):
        return [(y + dy, x + dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if (dy or dx)]


def old_update_level_shops(agent):
    """integ's (v10c's) _update_level_shops shop fill, without the dig-tool and shop-type parts."""
    level = agent.current_level()
    shopkeepers = list(
        zip(*(utils.isin(agent.glyphs, G.SHOPKEEPER) & agent.monster_tracker.peaceful_monster_mask).nonzero()))
    for y, x in shopkeepers:
        wall_mask = utils.isin(level.objects, G.WALL)
        entry = ((utils.translate(wall_mask, 1, 0) & utils.translate(wall_mask, -1, 0)) |
                 (utils.translate(wall_mask, 0, 1) & utils.translate(wall_mask, 0, -1))) & \
            level.walkable
        walkable = level.walkable & ~entry
        mask = utils.bfs(y, x, walkable=walkable, walkable_diagonally=walkable, can_squeeze=False) != -1
        mask = utils.dilate(mask, radius=1)
        level.shop[mask] = True
        level.shop_interior[mask & ~utils.dilate(entry, radius=1, with_diagonal=False)] = True


def fill(level_fn, on):
    level = level_fn()
    with flags(SHOP_MASK_FIX=on):
        Agent._update_level_shops(FakeShopAgent(level))
    return level


# ------------------------------------------------------------------ _update_level_shops


def test_flag_defaults_off():
    assert jf_config.SHOP_MASK_FIX is False


def test_off_leaks_into_the_corridor():
    """The bug as it is (flag off): the whole corridor becomes shop floor."""
    level = fill(shop_map, False)
    assert level.shop[6, 16:31].all()
    assert level.shop_interior[6, 17:30].all()


def test_on_stops_at_the_doorway():
    level = fill(shop_map, True)
    assert level.shop[5:8, 10:15].all() and level.shop_interior[5:8, 10:14].all()
    assert level.shop[6, 15]                                   # the door itself: dilation of the floor next to it
    assert not level.shop[6, 16:].any() and not level.shop_interior[6, 15:].any()
    # the square inside the door (where the shopkeeper stands: shk.c costly_spot is false there) is no interior
    assert not level.shop_interior[6, 14]


def test_on_stops_at_an_open_door():
    for door in (SS.S_vodoor, SS.S_hodoor):
        level = fill(lambda: shop_map(door=door), True)
        assert not level.shop[6, 16:].any(), door
        old = fill(lambda: shop_map(door=door), False)
        assert old.shop[6, 16:31].all(), door                # the old fill leaked through an open door too


def test_on_equals_off_when_the_old_rule_already_works():
    """Walls beside the door seen (the door is an 'entry') or a closed door: both fills give the same masks."""
    for level_fn in (lambda: shop_map(walls_beside_door=True),
                     lambda: shop_map(door=SS.S_vcdoor),
                     lambda: shop_map(door=SS.S_vcdoor, walls_beside_door=True)):
        a, b = fill(level_fn, False), fill(level_fn, True)
        assert (a.shop == b.shop).all() and (a.shop_interior == b.shop_interior).all()
        assert not a.shop[6, 16:].any()


def test_off_matches_the_old_code_on_random_maps():
    rng = random.Random(7)
    glyph_pool = [SS.S_room, SS.S_room, SS.S_room, SS.S_corr, SS.S_litcorr, SS.S_ndoor, SS.S_vodoor, SS.S_hodoor,
                  SS.S_vcdoor, SS.S_vwall, SS.S_hwall, SS.S_tlcorn, SS.S_darkroom]
    for trial in range(40):
        cells = {}
        for y in range(2, 14):
            for x in range(3, 40):
                if rng.random() < 0.8:
                    cells[(y, x)] = rng.choice(glyph_pool)
        level_a, level_b = Level(0, 2), Level(0, 2)
        paint(level_a, cells)
        paint(level_b, cells)
        floor = [p for p, g in cells.items() if g == SS.S_room]
        shk = rng.choice(floor)
        with flags(SHOP_MASK_FIX=False):
            Agent._update_level_shops(FakeShopAgent(level_a, shopkeeper=shk, pos=shk))
        old_update_level_shops(FakeShopAgent(level_b, shopkeeper=shk, pos=shk))
        assert (level_a.shop == level_b.shop).all(), trial
        assert (level_a.shop_interior == level_b.shop_interior).all(), trial


# ------------------------------------------------------------------ _force_bolt_tail_safe


class FakeBoltAgent:
    def __init__(self, level, glyphs=None):
        self.glyphs = np.full((C.SIZE_Y, C.SIZE_X), SS.S_stone, dtype=np.int16) if glyphs is None else glyphs
        if glyphs is None:
            self.glyphs[level.seen] = level.objects[level.seen]
        self.monster_tracker = types.SimpleNamespace(peaceful_monster_mask=np.zeros((C.SIZE_Y, C.SIZE_X), bool))


def old_tail_safe(agent, level, shop, y0, x0, sy, sx, reach=FORCE_BOLT_MAX_RANGE):
    """integ's (v10c's) fight_heur._force_bolt_tail_safe."""
    objects = 0
    for k in range(1, reach + 1):
        y, x = y0 + sy * k, x0 + sx * k
        if not (0 <= y < level.walkable.shape[0] and 0 <= x < level.walkable.shape[1]):
            return True
        if shop is not None and shop[y, x]:
            return False
        if k > 1 and (agent.glyphs[y, x] in G.PETS or agent.monster_tracker.peaceful_monster_mask[y, x]):
            return False
        if agent.glyphs[y, x] in G.OBJECTS:
            objects += 1
            if objects >= 2:
                return False
        if not level.walkable[y, x] and level.seen[y, x]:
            return True
    return True


def tail(level, shop, y0, x0, sy, sx, on, agent=None):
    with flags(SHOP_MASK_FIX=on):
        return fight_heur._force_bolt_tail_safe(agent or FakeBoltAgent(level), level, shop, y0, x0, sy, sx)


def bolt_shop(level):
    """force_bolt_actions' tail mask: the dilated shop interior."""
    return utils.dilate(level.shop_interior, radius=1)


def test_tail_wall_stops_the_bolt():
    """A corridor ends one (unseen) rock square short of the shop's seen west wall. force_bolt_actions' tail mask is the
    shop interior (walls included) dilated once more, so it covers that rock square and the wall: the old check refused a
    bolt fired east along the corridor; with the fix the rock square does not refuse and the wall stops the bolt."""
    level = shop_map(walls_beside_door=True)
    paint(level, {(6, x): SS.S_corr for x in range(3, 8)})
    Agent._update_level_shops(FakeShopAgent(level))
    shop = bolt_shop(level)
    assert not shop[6, 7] and shop[6, 8] and shop[6, 9]
    assert not level.seen[6, 8] and level.objects[6, 9] in G.WALL
    # we stand at (6, 5), the target at (6, 6): the tail runs on east over (6, 7), rock (6, 8), the wall (6, 9)
    assert tail(level, shop, 6, 5, 0, 1, False) is False
    assert tail(level, shop, 6, 5, 0, 1, True) is True


def test_tail_corner_rock_does_not_refuse():
    """A diagonal line past the shop's top-left corner: the rock square (3, 8) outside the corner is in the tail mask."""
    level = shop_map(walls_beside_door=True)
    paint(level, {(0, 5): SS.S_corr, (1, 6): SS.S_corr, (2, 7): SS.S_corr})
    Agent._update_level_shops(FakeShopAgent(level))
    shop = bolt_shop(level)
    assert not shop[2, 7] and shop[3, 8] and not level.seen[3, 8] and level.objects[4, 9] in G.WALL
    assert tail(level, shop, 0, 5, 1, 1, False) is False
    assert tail(level, shop, 0, 5, 1, 1, True) is True


def test_tail_unseen_rock_in_the_mask_does_not_refuse():
    """A tail mask square on rock nobody has seen (no stock lies there) and nothing seen beyond it."""
    level = Level(0, 4)
    paint(level, {(y, 6): SS.S_corr for y in range(10, 16)})
    shop = np.zeros((C.SIZE_Y, C.SIZE_X), bool)
    shop[9, 6] = True
    assert not level.walkable[9, 6] and not level.seen[9, 6]
    assert tail(level, shop, 14, 6, -1, 0, False) is False
    assert tail(level, shop, 14, 6, -1, 0, True) is True


def test_tail_shop_floor_and_doors_still_refuse():
    # from the corridor straight west through the doorway into the shop floor: refused either way
    level = shop_map(walls_beside_door=True)
    Agent._update_level_shops(FakeShopAgent(level))
    for on in (False, True):
        assert tail(level, bolt_shop(level), 6, 20, 0, -1, on) is False, on
    # a closed shop door in the (undilated) mask: refused either way (the bolt breaks it open)
    level = shop_map(door=SS.S_vcdoor, walls_beside_door=True)
    Agent._update_level_shops(FakeShopAgent(level))
    shop = level.shop_interior.copy()
    assert not shop[6, 16] and shop[6, 15]
    for on in (False, True):
        assert tail(level, shop, 6, 20, 0, -1, on) is False, on
    # the same square as a seen wall: refused only without the fix
    paint(level, {(6, 15): SS.S_vwall})
    assert tail(level, shop, 6, 20, 0, -1, False) is False
    assert tail(level, shop, 6, 20, 0, -1, True) is True


def test_tail_off_matches_the_old_code_on_random_lines():
    rng = random.Random(11)
    pool = [SS.S_room, SS.S_corr, SS.S_ndoor, SS.S_vodoor, SS.S_vcdoor, SS.S_vwall, SS.S_hwall, SS.S_stone, -1]
    for trial in range(400):
        level = Level(0, 5)
        cells = {}
        for y in range(0, C.SIZE_Y):
            for x in range(0, 30):
                g = rng.choice(pool)
                if g != -1:
                    cells[(y, x)] = g
        paint(level, cells)
        glyphs = np.full((C.SIZE_Y, C.SIZE_X), SS.S_stone, dtype=np.int16)
        glyphs[level.seen] = level.objects[level.seen]
        for _ in range(6):
            glyphs[rng.randrange(C.SIZE_Y), rng.randrange(30)] = NEWT
        agent = FakeBoltAgent(level, glyphs=glyphs)
        shop = np.array([[rng.random() < 0.15 for _ in range(C.SIZE_X)] for _ in range(C.SIZE_Y)]) \
            if trial % 4 else None
        y0, x0 = rng.randrange(C.SIZE_Y), rng.randrange(30)
        sy, sx = rng.choice([(0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)])
        want = old_tail_safe(agent, level, shop, y0, x0, sy, sx)
        assert tail(level, shop, y0, x0, sy, sx, False, agent=agent) == want, trial


# ------------------------------------------------------------------ configuration


def _run(code, **env):
    full = dict(os.environ)
    for k in ('JF_CFG', 'JF_ROLE_CFG'):
        full.pop(k, None)
    full.update({k: json.dumps(v) for k, v in env.items()})
    return subprocess.run([sys.executable, '-c', code], env=full, capture_output=True, text=True, check=True,
                          cwd=os.getcwd()).stdout.split()


def test_jf_role_cfg_reaches_the_flag_per_role():
    code = ('import sys; sys.path.insert(0, "."); import roles, bot; from nhbot import jf_config; '
            'print(jf_config.SHOP_MASK_FIX); roles.apply(IDENT); print(jf_config.SHOP_MASK_FIX, '
            'bot._specialist(IDENT) or "nhbot")')
    cfg = {'wiz': {'jf_config.SHOP_MASK_FIX': True}}
    assert _run(code.replace('IDENT', '"wiz-elf-cha-mal"'), JF_ROLE_CFG=cfg) == ['False', 'True', 'nhbot']
    assert _run(code.replace('IDENT', '"val-dwa-law-fem"'), JF_ROLE_CFG=cfg) == ['False', 'False', 'nhbot']
    # wiz-hum-neu plays pf_s25p8 (bot.SPECIALISTS): roles.apply is never called for it in a real game
    assert _run(code.replace('IDENT', '"wiz-hum-neu-mal"'), JF_ROLE_CFG=cfg)[2] == 'adapter_pf_s25p8'
    assert _run(code.replace('IDENT', '"val-dwa-law-fem"'), JF_CFG={'SHOP_MASK_FIX': True})[0] == 'True'


if __name__ == '__main__':
    n = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            n += 1
            print('ok', name)
    print(f'{n} passed')
