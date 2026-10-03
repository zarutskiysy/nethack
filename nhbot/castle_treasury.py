"""CASTLE_TREASURY (jf_config; imported from vlomshakov f84a81b's castle_treasury.py, elite scan F075): while we are a
wall-walker on the castle level (CFP_XORN / POLY_XORN), a bounded detour through the walls to the four tower cells
before the trap door: the castle's wand of wishing is in a chest in one of them.

NetHack 3.6.6 dat/castle.des: CONTAINER:('(',"chest"),not_trapped,$place[0] { OBJECT:('/',"wishing") } with
$place = { (04,02),(58,02),(04,14),(58,14) } shuffled, a burned Elbereth and a cursed scroll of scare monster on the
same square, two soldiers per tower (03/05 and 57/59 of rows 02 and 14). Nothing else puts a chest in a tower, so a
wand in a tower chest IS the wand of wishing (mkobj.c: rnd(3) charges). mksobj() locks a chest 4 times in 5.

Opening a locked chest, best first:
  * a skeleton key / lock pick / credit card (lock.c pick_lock: 'In what direction?' '.', then 'There is a chest
    here; unlock it?' -> y; an occupation);
  * #force with the wielded weapon (lock.c doforce): a blade pries at 2x its large-monster damage per turn (a long
    sword 24%) and breaks 1 time in ~125 per failed turn -- never an artifact (obj_resists 99); a blunt weapon or a
    pick-axe bashes at 2x its die (d3: 6%) and wrecks the box 1 time in 3 (breakchestlock: its wand drops to the
    floor). A sword in the pack is wielded first;
  * kick it from a neighbouring square (dokick.c: the lock breaks 1 kick in 5).
The wand is identified by one zap: its wish is WISH_TELEPORT_ROUTE's (SPARE_WISHES -> power.wish_text ->
tele_route.route_wish: with WISH_CHARGING_FIRST '2 blessed scrolls of charging', else the ring of teleport control),
and the route does the rest (tele_route: a wall-walker may use it with CASTLE_TREASURY on). vlomshakov's ascension
wish list is NOT imported: it switched that route off.

Budgets: 240 actions / 1500 steps / 400 turns, HP >= 45% (and >= 15); trap-door squares are never on the way; a
monster on the way ends the detour (the xorn walk goes around it). Any failure hands back to the trap-door walk.
"""

import re

import nle.nethack as nh
from nle.nethack import actions as A

from . import jf_config
from . import objects as O
from .exceptions import AgentChangeStrategy, AgentFinished, AgentPanic
from .glyph import SS
from .strategy import Strategy

TOWERS = ((4, 2), (4, 14), (58, 2), (58, 14))   # castle map (x, y)
# Only the east towers, and only the first one checked: harness oct3 (all four, 27 xorn games) found no wand and cut
# Valley arrivals 18 -> 13 of 30 -- each west tower costs a moat crossing next to a corner shark (castle.des sharks at
# (05,00)/(05,16)/(57,00)/(57,16)) and its two soldiers, from a ~38 HP xorn form. An east tower is ~20 steps off the
# trap-door walk and can be entered from the castle's own corridor (its closed door is no obstacle to a wall-walker)
SEARCH = ((58, 2), (58, 14))
MAX_TOWERS = 1
MOAT_COST = 60                  # vs 20 on the trap-door walk: the corridor way in, not the corner moat
MAX_ACTIONS = 240
MAX_STEPS = 1500
MAX_TURNS = 400
MAX_STALL = 10
MAX_OPEN_TRIES = 30
MIN_HP = 15
MIN_HP_FRACTION = 0.45
UNLOCKERS = ('skeleton key', 'lock pick', 'credit card')
_DIR = {(-1, 0): 'n', (1, 0): 's', (0, 1): 'e', (0, -1): 'w', (-1, 1): 'ne', (-1, -1): 'nw', (1, 1): 'se',
        (1, -1): 'sw'}

# ---- CASTLE_WISH_FIRST (jf_config; research/castle_wish.md): the wand before the trap door, all four towers
WISH_MAX_ACTIONS = 700
WISH_MAX_STEPS = 5000
WISH_MAX_TURNS = 1500           # a #force is an occupation of up to 50 turns per action (lock.c forcelock)
WISH_MIN_HP = 5                 # the form's HP: at 0 we only return to our own form (polyself.c rehumanize)
WISH_MIN_HP_FRACTION = 0.2
WISH_MAX_FIGHTS = 60
WISH_FOOT_MAX_ACTIONS = 600
WISH_MAX_BLIND_WAITS = 30
WISH_MAX_UNLOCK_TRIES = 10      # then #force (a key that keeps failing -- a cursed one, clumsy fingers -- isn't retried)
SOLDIER_NAMES = ('soldier', 'sergeant', 'lieutenant', 'captain')
# chest square -> (hallway row, tower door, the tower square inside the door, tower interior); castle.des: the tower
# doors (07,03)/(55,03)/(07,13)/(55,13) are closed, not locked, and each hallway (row 03 / row 13, x 08..54) joins its
# two towers -- on foot the other tower of the same hallway is in reach (the hallways' doors to the throne room are
# locked: (32,04)/(32,12))
TOWER_INFO = {
    (4, 2): (3, (7, 3), (6, 3), frozenset((x, y) for x in range(2, 7) for y in (2, 3))),
    (58, 2): (3, (55, 3), (56, 3), frozenset((x, y) for x in range(56, 61) for y in (2, 3))),
    (4, 14): (13, (7, 13), (6, 13), frozenset((x, y) for x in range(2, 7) for y in (13, 14))),
    (58, 14): (13, (55, 13), (56, 13), frozenset((x, y) for x in range(56, 61) for y in (13, 14))),
}
_FLOOR_GLYPHS = frozenset((SS.S_room, SS.S_darkroom))


def wish_first():
    return bool(getattr(jf_config, 'CASTLE_WISH_FIRST', False))


def _search():
    return TOWERS if wish_first() else SEARCH


def _max_towers():
    return len(TOWERS) if wish_first() else MAX_TOWERS


class TreasuryState:
    def __init__(self, turn, step):
        self.started_turn = turn
        self.started_step = step
        self.visited = set()        # tower cells checked (no chest, or its chest had no wand)
        self.open_tries = {}        # tower cell -> opening attempts
        self.target = None
        self.actions = 0
        self.same_position = 0
        self.kick_target = None     # tower cell whose locked chest we stepped off to kick
        self.wield_failed = False   # our form couldn't wield the sword: #force with what we hold
        self.acquired_glyph = None
        self.acquired = False
        self.identified = False
        self.done = False
        self.reason = ''
        # CASTLE_WISH_FIRST
        self.fights = 0
        self.blind_waits = 0
        self.foot_actions = 0
        self.noted = set()          # towers whose status was logged
        self.foot_target = None     # the tower chest we walk to on foot


def _log(castle, message):
    castle.agent.log(f'CASTLE TREASURY {message}')


def _finish(castle, state, reason):
    state.done = True
    state.reason = reason
    _log(castle, f'{reason}; back to the trap-door walk')
    return False


def _is_wishing(item):
    return item.category == nh.WAND_CLASS and item.is_unambiguous() and item.object.name == 'wishing'


def _wands(items, glyph=None):
    return [i for i in items if i.category == nh.WAND_CLASS and (glyph is None or glyph in i.glyphs)]


def _identify_acquired(castle, state):
    """One zap names the wand: a wand of wishing asks for the wish at once (NODIR; the route's text answers it)."""
    agent = castle.agent
    inv = agent.inventory
    wand = next(iter(_wands(inv.items, state.acquired_glyph)), None)
    if wand is None:
        return _finish(castle, state, 'the tower wand is no longer carried')
    if not _is_wishing(wand):
        letter = inv.items.get_letter(wand)
        agent._last_wand_use_step = agent.step_count   # tele_route._wand_source: this wish comes from a wand
        _log(castle, f'zapping {wand.text!r} ({letter}) to name it')
        with agent.atom_operation():
            agent.step(A.Command.ZAP)
            if 'What do you want to zap?' in agent.single_message:
                agent.type_text(letter)
            if 'In what direction?' in agent.single_message:
                agent.step(A.Command.ESC)
        _log(castle, f'zap -> {(agent.message or "")[:160]!r}')
        inv.items.update(force=True)
        wand = next(iter(_wands(inv.items, state.acquired_glyph)), None)
    state.identified = wand is not None and _is_wishing(wand)
    _finish(castle, state, f'wand of wishing in the pack: {wand.text!r}' if state.identified else
            'wand taken; the zap did not name it wishing')
    return True


def _blade(item):
    """A weapon #force pries with (lock.c is_blade: dagger..saber skills), and its chance per turn (2x large die)."""
    obj = item.objs[0] if item.objs else None
    if not isinstance(obj, O.Weapon) or not (O.P_DAGGER <= obj.sub <= O.P_SABER) or obj.sub == O.P_PICK_AXE:
        return None
    try:
        return 2 * int(obj.ldam)
    except (TypeError, ValueError):
        return None


def _artifact(item):
    """An artifact's display name is capitalised ('the blessed rustproof +1 Excalibur'); a 'named'/'called' part isn't."""
    text = re.split(r' (?:named|called) ', item.text or '')[0]
    return any(c.isupper() for c in text)


def _can_force_with(item):
    """lock.c doforce: a wielded weapon (or weapon-tool) with skill dagger..lance but not flail; blunt ones bash."""
    obj = item.objs[0] if item.objs else None
    sub = getattr(obj, 'sub', None)
    if not isinstance(obj, (O.Weapon, O.WepTool)) or not isinstance(sub, int):
        return False
    return O.P_DAGGER <= abs(sub) <= O.P_LANCE and abs(sub) != O.P_FLAIL


def _force_chance(item):
    """lock.c doforce: xlock.chance = 2 * oc_wldam (percent per turn), blade or blunt."""
    obj = item.objs[0] if item.objs else None
    try:
        return 2 * int(obj.ldam)
    except (AttributeError, TypeError, ValueError):
        return 0


def unlock_tool(agent):
    """The best unlocking tool carried (skeleton key > lock pick > credit card), or None."""
    tools = [i for i in agent.inventory.items if i.is_unambiguous() and i.object.name in UNLOCKERS]
    return min(tools, key=lambda i: UNLOCKERS.index(i.object.name)) if tools else None


def apply_unlocker(agent, tool):
    """lock.c pick_lock on the box under us: apply, 'In what direction?' '.', 'There is a chest here; unlock it?' (a
    lock pick: 'pick its lock?') y -- then an occupation (picklock) until it opens or is interrupted."""
    letter = agent.inventory.items.get_letter(tool)

    def responses():
        if 'What do you want to use or apply?' not in agent.single_message:
            return
        yield letter
        for _ in range(3):
            msg = agent.single_message or ''
            if 'In what direction?' in msg or 'direction' in msg.lower():
                yield '.'
                continue
            if ('unlock it?' in msg or 'pick its lock?' in msg) and '[yn' in msg:
                yield 'y'
                return
            return

    with agent.atom_operation():
        agent.step(A.Command.APPLY, responses())


def _open(castle, state, chest):
    """One step toward opening the locked chest under us: unlock, else #force (a sword wielded first), else kick."""
    agent = castle.agent
    inv = agent.inventory
    pos = castle._pos()
    n = state.open_tries.get(pos, 0)
    if n >= MAX_OPEN_TRIES:
        state.visited.add(pos)
        return _finish(castle, state, f'the tower chest at {pos} stayed locked ({n} tries)')
    state.open_tries[pos] = n + 1
    tool = unlock_tool(agent)
    if tool is not None and not (wish_first() and n >= WISH_MAX_UNLOCK_TRIES):
        apply_unlocker(agent, tool)
        _log(castle, f'unlock try {n + 1} at {pos} with {tool.text!r}: {(agent.message or "")[-120:]!r}')
        return True
    wielded = inv.items.main_hand
    # an artifact last among equals: artifact.c touch_artifact blasts a wielder whose alignment record went negative
    # (oct5on s4: 'You are blasted by Excalibur's power!', 4d10 off a 38-HP xorn form)
    swords = sorted((i for i in inv.items if _blade(i) is not None and i.status != i.CURSED),
                    key=lambda i: (-_blade(i), _artifact(i)))
    if swords and not state.wield_failed and (wielded is None or _blade(wielded) is None) and \
            not (wielded is not None and wielded.status == wielded.CURSED):
        if not _wield(castle, state, swords[0]):
            state.wield_failed = True   # (then #force with what we hold)
        return True
    if wish_first() and not state.wield_failed and (wielded is None or not _can_force_with(wielded)) and \
            not (wielded is not None and wielded.status == wielded.CURSED):
        # CASTLE_WISH_FIRST: no blade, and what we hold can't #force (nothing, a bow, a whip, a unicorn horn): wield
        # what can -- the dive's pick-axe bashes (lock.c: 2x its large die per turn, d3 -> 6%; a success wrecks the
        # box 1 time in 3 and each object in it shatters 1 time in 3, so the wand survives 8 times in 9), which beats
        # kicking from off the refuge square
        bashers = sorted((i for i in inv.items if _can_force_with(i) and i.status != i.CURSED and not i.equipped),
                         key=lambda i: (-_force_chance(i), _artifact(i)))
        if bashers:
            if not _wield(castle, state, bashers[0]):
                state.wield_failed = True
            return True
    if wielded is not None and _can_force_with(wielded):
        with agent.atom_operation():
            agent.step(A.Command.FORCE)
            for _ in range(2):
                msg = agent.single_message or ''
                if 'force its lock?' in msg or 'force the lock' in msg:
                    agent.type_text('y')
                    break
                if '--More--' in msg:
                    agent.step(A.TextCharacters.SPACE)
                    continue
                break
        _log(castle, f'#force try {n + 1} at {pos} with {wielded.text!r}: {(agent.message or "")[-140:]!r}')
        inv.items.update(force=True)
        return True
    return _kick(castle, state, pos)


def _wield(castle, state, item):
    """Wield a sword to pry with. inventory.wield() refuses in any polymorphed form (its TODO); a xorn has hands
    (harness oct4on s4/s18: 30 refused wields, the locked chest left alone)."""
    agent = castle.agent
    inv = agent.inventory
    letter = inv.items.get_letter(item)
    _log(castle, f'wielding {item.text!r} ({letter}) to pry the lock')
    with agent.atom_operation():
        agent.step(A.Command.WIELD)
        if 'What do you want to wield' not in (agent.single_message or ''):
            if agent._observation['misc'][0] or agent._observation['misc'][1]:
                agent.step(A.Command.ESC)
            return False
        agent.type_text(letter)
    inv.items.update(force=True)
    held = inv.items.main_hand
    ok = held is not None and inv.items.get_letter(held) == letter
    _log(castle, f'wield -> {(agent.message or "")[-100:]!r} ({"ok" if ok else "failed"})')
    return ok


def _kick(castle, state, pos):
    """No key, no weapon to force it with: step off the chest (a wall-walker can stand in the wall beside it); the next
    step kicks back at it (dokick.c: the lock breaks 1 kick in 5) and then walks onto it to look again."""
    agent = castle.agent
    from .castle_logic import to_bot
    cy, cx = (int(v) for v in to_bot(*pos))
    dirs = list(_DIR.items())
    if wish_first():
        dirs = sorted(dirs, key=lambda kv: _kick_square_rank(_to_map(cy + kv[0][0], cx + kv[0][1])))
    for (dy, dx), d in dirs:
        if castle._monster_at(*_to_map(cy + dy, cx + dx)):
            continue
        agent.direction(d)
        if (int(agent.blstats.y), int(agent.blstats.x)) != (cy, cx):
            state.kick_target = pos
            return True
    return _finish(castle, state, 'no square to kick the tower chest from')


def _to_map(y, x):
    from .castle_logic import to_map
    return to_map(y, x)


def _kick_square_rank(p):
    """CASTLE_WISH_FIRST: where to stand to kick the tower chest -- the tower's own floor first, then a wall square
    with no moat beside it, a moat-side wall last (the corner sharks (05,00)/(57,00)/(05,16)/(57,16) bite into it)."""
    from .castle_logic import map_char
    mx, my = (int(v) for v in p)
    ch = map_char(mx, my)
    moat_side = any(map_char(mx + dx, my + dy) == '}' for dx in (-1, 0, 1) for dy in (-1, 0, 1))
    return (ch != '.', moat_side)


def _glyph_at(agent, p):
    from .castle_logic import to_bot
    y, x = (int(v) for v in to_bot(*p))
    glyphs = agent.glyphs
    if not (0 <= y < glyphs.shape[0] and 0 <= x < glyphs.shape[1]):
        return None
    return int(glyphs[y, x])


def tower_status(castle, chest):
    """CASTLE_WISH_FIRST: what the map shows on a tower's chest square. 'object': something lies there (the wand's
    tower shows the cursed scare monster scroll on top of the chest); 'floor': seen bare -- that tower's chest is
    elsewhere; 'soldier': a hostile soldier stands on it -- no scare monster scroll there (monmove.c onscary: the
    scroll scares @ too, and only peacefuls may step on it); None: not seen (or we stand on it)."""
    agent = castle.agent
    if tuple(int(v) for v in castle._pos()) == tuple(chest):
        return None
    from .castle_logic import to_bot
    cy, cx = (int(v) for v in to_bot(*chest))
    for m in agent.get_visible_monsters():
        if (int(m[1]), int(m[2])) == (cy, cx):
            return 'soldier' if getattr(m[3], 'mname', '') in SOLDIER_NAMES else None
    g = _glyph_at(agent, chest)
    if g is None:
        return None
    if nh.glyph_is_object(g):
        return 'object'
    if g in _FLOOR_GLYPHS:
        return 'floor'
    return None


def _note_towers(castle, state):
    """Count the towers the map already rules out as checked; return the ones whose chest square shows an object."""
    out = set()
    for t in _search():
        if t in state.visited:
            continue
        st = tower_status(castle, t)
        if st in ('floor', 'soldier'):
            state.visited.add(t)
            if state.target == t:
                state.target = None
            _log(castle, f'tower {t}: {"seen bare" if st == "floor" else "a soldier on its chest square"}, '
                         f'not the wand tower')
        elif st == 'object':
            out.add(t)
            if t not in state.noted:
                state.noted.add(t)
                _log(castle, f'tower {t}: an object on its chest square')
    return out


def _inspect(castle, state):
    agent = castle.agent
    inv = agent.inventory
    pos = castle._pos()
    if wish_first() and agent.character.prop.blind and state.blind_waits < WISH_MAX_BLIND_WAITS:
        # blind, the look may be skipped (inventory._blind_look_skip: the floor reads as empty) -- wait for sight on
        # the refuge square rather than call this tower checked
        state.blind_waits += 1
        agent.search()
        return True
    inv.get_items_below_me()
    below = list(inv.items_below_me)
    loose = _wands(below)
    if loose and inv.items.free_slots() >= 1:
        # a bashed box scattered its contents (breakchestlock): the wand lies here
        glyph = loose[0].glyphs[0]
        before = sum(i.count for i in _wands(inv.items, glyph))
        inv.pickup(loose[0])
        inv.items.update(force=True)
        if sum(i.count for i in _wands(inv.items, glyph)) > before:
            state.acquired, state.acquired_glyph = True, glyph
            _log(castle, f'picked up the wand at tower {pos}')
            return True
    chests = [i for i in below if i.is_unambiguous() and i.object.name in ('chest', 'large box')]
    if len(chests) != 1:
        state.visited.add(pos)
        state.target = None
        _log(castle, f'tower {pos}: {len(chests)} chests here')
        return True
    chest = chests[0]
    inv.check_container_content(chest)
    if chest.content is None:
        return _finish(castle, state, 'could not look into the tower chest')
    if chest.content.locked:
        return _open(castle, state, chest)
    wands = [i for i in chest.content.items if i.category == nh.WAND_CLASS]
    if not wands:
        state.visited.add(pos)
        state.target = None
        _log(castle, f'tower {pos}: its chest holds no wand')
        return True
    if inv.items.free_slots() < 1:
        return _finish(castle, state, 'no inventory slot for the tower wand')
    wand = next((i for i in wands if _is_wishing(i)), wands[0])
    glyph = wand.glyphs[0]
    before = sum(i.count for i in _wands(inv.items, glyph))
    inv.use_container(chest, [], [wand])
    inv.items.update(force=True)
    if sum(i.count for i in _wands(inv.items, glyph)) <= before:
        return _finish(castle, state, '#loot did not put the tower wand in the pack')
    state.acquired, state.acquired_glyph = True, glyph
    _log(castle, f'took the wand from the chest at tower {pos}')
    return True


def _on_refuge(castle, state, pos):
    """On an unchecked tower chest square: if it is the wand's, the scare monster scroll there stops every melee
    attacker (monmove.c distfleeck/onscary) -- keep working whatever the HP."""
    return wish_first() and tuple(int(v) for v in pos) in TOWER_INFO and pos not in state.visited


def _common(castle, state):
    """Steps shared by the xorn walk and the walk on foot: name the wand we took, kick back at the chest we stepped
    off, inspect the unchecked chest square we stand on. None: nothing of that applied."""
    from .castle_logic import to_bot
    agent = castle.agent
    bl = agent.blstats
    if state.acquired:
        return _identify_acquired(castle, state)
    pos = castle._pos()
    kt, state.kick_target = state.kick_target, None
    if kt is not None:
        ky, kx = (int(v) for v in to_bot(*kt))
        if max(abs(ky - int(bl.y)), abs(kx - int(bl.x))) == 1:
            agent.kick(ky, kx)
            _log(castle, f'kicked the chest at {kt}: {(agent.message or "")[-120:]!r}')
            return True
    if pos in _search() and pos not in state.visited:
        return _inspect(castle, state)
    return None


def _over_budget(castle, state):
    agent = castle.agent
    bl = agent.blstats
    if wish_first():
        max_actions, max_steps, max_turns = WISH_MAX_ACTIONS, WISH_MAX_STEPS, WISH_MAX_TURNS
    else:
        max_actions, max_steps, max_turns = MAX_ACTIONS, MAX_STEPS, MAX_TURNS
    return state.actions >= max_actions or agent.step_count - state.started_step >= max_steps or \
        bl.time - state.started_turn >= max_turns


def _low_hp(castle, state):
    bl = castle.agent.blstats
    if wish_first():
        if _on_refuge(castle, state, castle._pos()):
            return False
        return bl.hitpoints < max(WISH_MIN_HP, WISH_MIN_HP_FRACTION * bl.max_hitpoints)
    return bl.hitpoints < max(MIN_HP, MIN_HP_FRACTION * bl.max_hitpoints)


def _fight(castle, state, p, why):
    """CASTLE_WISH_FIRST: hit what stands on our next square (F + direction: no displacing, no walking into it)."""
    from .castle_logic import to_bot
    agent = castle.agent
    state.fights += 1
    if state.fights > WISH_MAX_FIGHTS:
        return _finish(castle, state, f'{WISH_MAX_FIGHTS} fights on the way')
    y, x = to_bot(*p)
    d = agent.calc_direction(agent.blstats.y, agent.blstats.x, y, x)
    if state.fights == 1 or state.fights % 10 == 0:
        _log(castle, f'fighting the monster at {p} ({why}), fight {state.fights}')
    with agent.atom_operation():
        agent.step(A.Command.FIGHT)
        agent.direction(d)
    return True


def step(castle):
    """True iff the treasury acted this step; False hands back to the trap-door walk at once."""
    from . import castle_cross
    from .castle_logic import map_char

    agent = castle.agent
    state = getattr(castle, '_treasury', None)
    if state is not None and state.done:
        return False
    if agent.current_level().key() != castle.castle_key or not castle_cross.wallwalker(agent):
        if state is not None:
            if wish_first() and agent.current_level().key() == castle.castle_key:
                # CASTLE_WISH_FIRST: the form ran out -- foot_strategy carries on inside a tower
                return False
            _finish(castle, state, 'left the castle or the wall-walking form')
        return False
    if state is None:
        if any(_is_wishing(i) for i in agent.inventory.items):
            return False   # a wand of wishing already: no detour
        state = castle._treasury = TreasuryState(agent.blstats.time, agent.step_count)
        _log(castle, 'to the towers for the wand of wishing' + (' (all four: CASTLE_WISH_FIRST)' if wish_first()
                                                                  else ''))
    bl = agent.blstats
    # the wand in the pack is named first: the HP and budget checks below used to end the detour with it unnamed
    # (WISH_TELEPORT_ROUTE only acts on a known wand of wishing). integ: gated by CASTLE_WISH_FIRST -- castle-wish
    # shipped it always-on as a bug fix, but integ keeps v10c's order with every new flag off
    if not state.acquired or not wish_first():
        if _low_hp(castle, state):
            return _finish(castle, state, f'HP {bl.hitpoints}/{bl.max_hitpoints}')
        if _over_budget(castle, state):
            return _finish(castle, state, 'budget spent')
    state.actions += 1
    try:
        done = _common(castle, state)
        if done is not None:
            return done
        pos = castle._pos()
        search = _search()
        seen = _note_towers(castle, state) if wish_first() else set()
        remaining = set(search) - state.visited
        if not remaining or len(state.visited & set(search)) >= _max_towers():
            return _finish(castle, state, f'tower(s) {sorted(state.visited)} checked, no wand')
        if state.target in remaining:
            goals = {state.target}
        else:
            goals = (seen & remaining) or remaining
        blocked = set(castle_cross.TRAPDOORS)
        if wish_first():
            # sea monsters are routed around, not fought (they submerge; their bites drown a breathing hero)
            for m in agent.get_visible_monsters():
                mp = castle_cross.castle_to_map(m[1], m[2])
                if map_char(*mp) == '}':
                    blocked.add(tuple(int(v) for v in mp))
        path = castle_cross._xorn_path(castle, pos, goals=goals, blocked=blocked, moat_cost=MOAT_COST,
                                       moat_side_cost=20)
        if not path or len(path) < 2:
            return _finish(castle, state, 'no way to a tower')
        state.target = path[-1]
        nxt = path[1]
        y, x = castle_cross.to_bot(*nxt)
        if castle._monster_at(*nxt):
            if not wish_first():
                return _finish(castle, state, f'a monster on the way at {nxt}')
            if tuple(nxt) in TOWER_INFO and tower_status(castle, nxt) == 'soldier':
                state.visited.add(nxt)
                state.target = None
                _log(castle, f'tower {nxt}: a soldier on its chest square, not the wand tower')
                return True
            return _fight(castle, state, nxt, f'on the way to tower {state.target}')
        if state.actions == 1 or state.actions % 10 == 0:
            _log(castle, f'at {pos}, {len(path) - 1} steps to tower {path[-1]}')
        agent.direction(agent.calc_direction(bl.y, bl.x, y, x))
        after = castle._pos()
        state.same_position = state.same_position + 1 if after == pos else 0
        if state.same_position >= MAX_STALL:
            _finish(castle, state, f'stalled at {after}')
        return True
    except (AgentChangeStrategy, AgentFinished):
        raise
    except AgentPanic:
        _finish(castle, state, 'panic in the container or on the way')
        raise
    except Exception as exc:
        # an optional detour must not end a live game: the recovery loop cancels any menu, the walk resumes
        _finish(castle, state, f'failed: {type(exc).__name__}: {exc}')
        raise AgentPanic('castle treasury failed') from exc


# ---------------------------------------------------------------------------------------------- on foot

def _tower_of(p):
    """The chest square of the tower whose interior (or door) p is in, else None."""
    p = tuple(int(v) for v in p)
    for chest, (row, door, inside, room) in TOWER_INFO.items():
        if p in room or p == door:
            return chest
    return None


def _on_hallway(p):
    x, y = (int(v) for v in p)
    return y in (3, 13) and 8 <= x <= 54


def foot_waypoints(pos, chest):
    """Squares to walk through, in order, from pos (a tower interior, its door or a hallway square) to the chest square
    of `chest`'s tower: out of our tower by its door, along the hallway (straight: no diagonal steps through a door),
    in by the other door. None: that tower isn't on our hallway."""
    pos = tuple(int(v) for v in pos)
    row, door, inside, room = TOWER_INFO[chest]
    if pos in room:
        return [chest]
    here = _tower_of(pos)
    out = []
    if here is not None:
        hrow, hdoor, hinside, hroom = TOWER_INFO[here]
        if hrow != row:
            return None
        if pos != hdoor:
            out.append(hinside)
            out.append(hdoor)
        out.append((hdoor[0] + (1 if hdoor[0] < 32 else -1), row))   # the hallway square beside our door
    elif not (_on_hallway(pos) and pos[1] == row):
        return None
    out += [(door[0] + (1 if door[0] < 32 else -1), row), door, inside, chest]
    return out


def _foot_target(castle, state):
    pos = castle._pos()
    here = _tower_of(pos)
    cands = [c for c in TOWER_INFO if c not in state.visited and foot_waypoints(pos, c) is not None]
    if not cands:
        return None
    # our own tower first, then the nearer one
    return min(cands, key=lambda c: (c != here, abs(c[0] - int(pos[0]))))


def _foot_ready(castle):
    from . import castle_cross
    if not wish_first():
        return False
    agent = castle.agent
    state = getattr(castle, '_treasury', None)
    if state is None or state.done or castle.castle_key is None or agent.current_level().key() != castle.castle_key:
        return False
    if castle_cross.wallwalker(agent):
        return False   # the xorn walk has it
    front = getattr(getattr(castle, 'dive', None), 'front', None)
    if front is not None and getattr(front, 'phase', None) == 'wand' and not getattr(front, 'done', True):
        return False   # FRONT_V3's own tower walk
    pos = castle._pos()
    if state.acquired:
        return True
    return _tower_of(pos) is not None or (_on_hallway(pos) and state.foot_target is not None)


def _foot_step(castle):
    """One step on foot inside the castle's towers (CASTLE_WISH_FIRST)."""
    from .castle_logic import to_bot
    agent = castle.agent
    state = castle._treasury
    state.foot_actions += 1
    if not state.acquired and state.foot_actions > WISH_FOOT_MAX_ACTIONS:
        return _finish(castle, state, 'on foot: budget spent')
    try:
        done = _common(castle, state)
        if done is not None:
            return done
        if state.done:
            return False
        _note_towers(castle, state)
        target = _foot_target(castle, state)
        state.foot_target = target
        if target is None:
            return _finish(castle, state, f'on foot: no unchecked tower in reach of {castle._pos()}')
        pos = tuple(int(v) for v in castle._pos())
        way = foot_waypoints(pos, target)
        nxt_goal = next((w for w in way if w != pos), None)
        if nxt_goal is None:
            return _inspect(castle, state)
        # one square toward the next waypoint (rooms are open floor, the hallway a straight corridor)
        sx = (nxt_goal[0] > pos[0]) - (nxt_goal[0] < pos[0])
        sy = (nxt_goal[1] > pos[1]) - (nxt_goal[1] < pos[1])
        if (pos in (TOWER_INFO[c][1] for c in TOWER_INFO) or nxt_goal in (TOWER_INFO[c][1] for c in TOWER_INFO)) \
                and sx and sy:
            sy = 0   # never diagonally into or out of a doorway
        nxt = (pos[0] + sx, pos[1] + sy)
        if castle._monster_at(*nxt):
            y, x = to_bot(*nxt)
            if nh.glyph_is_pet(int(agent.glyphs[y, x])):
                agent.direction(agent.calc_direction(agent.blstats.y, agent.blstats.x, y, x))   # swap places
                return True
            if nxt in TOWER_INFO and tower_status(castle, nxt) == 'soldier':
                state.visited.add(nxt)
                _log(castle, f'tower {nxt}: a soldier on its chest square, not the wand tower')
                return True
            return _fight(castle, state, nxt, f'on foot to tower {target}')
        if state.foot_actions == 1 or state.foot_actions % 10 == 0:
            _log(castle, f'on foot at {pos} to tower {target} via {nxt_goal}')
        y, x = to_bot(*nxt)
        agent.direction(agent.calc_direction(agent.blstats.y, agent.blstats.x, y, x))
        after = tuple(int(v) for v in castle._pos())
        if after == pos:
            msg = agent.message or ''
            if 'This door is locked' in msg:
                with agent.atom_operation():
                    agent.step(A.Command.KICK)
                    agent.direction(agent.calc_direction(agent.blstats.y, agent.blstats.x, y, x))
            state.same_position += 1
            if state.same_position >= 3 * MAX_STALL:
                return _finish(castle, state, f'on foot: stalled at {after} ({msg[:60]!r})')
        else:
            state.same_position = 0
        return True
    except (AgentChangeStrategy, AgentFinished):
        raise
    except AgentPanic:
        _finish(castle, state, 'on foot: panic in the container or on the way')
        raise
    except Exception as exc:
        _finish(castle, state, f'on foot failed: {type(exc).__name__}: {exc}')
        raise AgentPanic('castle treasury (on foot) failed') from exc


def foot_strategy(dive):
    """CASTLE_WISH_FIRST: our wall-walking form ran out inside a castle tower (or on its hallway on the way to the
    other tower): walk on to the unchecked tower chests in reach and take the wand (the same inspect/open/zap steps)."""
    def f():
        castle = getattr(dive, 'castle', None)
        if castle is None or not _foot_ready(castle):
            yield False
            return
        yield True
        n = 0
        while n < 300 and _foot_ready(castle):
            n += 1
            before = castle.agent.step_count
            if not _foot_step(castle):
                break
            if castle.agent.step_count == before:
                n += 4   # a decision without a move (a tower ruled out): bounded
    return Strategy(f)
