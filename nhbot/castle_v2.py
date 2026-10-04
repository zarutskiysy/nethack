"""castle_v2 (branch castle-v2; research/castle_v2.md): the Castle's tower-chest wand of wishing by the one route that
has produced it in our own replays -- the drawbridge crusher (vk's PASSTUNE_CRUSHER + CASTLE_INNER, ported OFF in
integ) -- switched on as one late-acting bundle, two fixes for what killed its lane in the vkc1 replay, and a
structured arrival census line.

NetHack 3.6.6 facts this rests on (NLE 1.3.0 src; castle.des in dat/):
* castle.des:46/139-144: the chest with the wand of wishing is on one of the 4 tower corners (04,02) (58,02) (04,14)
  (58,14); the towers open only onto the hallways (rows 03/13), and those only onto the throne room through the locked
  doors (32,04)/(32,12) (castle.des:60/73). NON_DIGGABLE:(00,00,62,16) and FLAGS:noteleport: no way round the throne
  room's 27 court monsters (castle.des:187-213) except phasing.
* The drawbridge (castle.des:77) opens only to the passtune (music.c do_play_instrument ~800: the 3x3 must hold the span
  or the portcullis), a wand of opening / knock (zap.c:3299-3306 bhit, 2842 zap_updown) -- never to a key, #force or
  #open (lock.c:473 'no lock on the drawbridge', 683 'no obvious way to open the drawbridge'). Only the tune, a wand of
  locking or wizard lock raise it again (zap.c:3308-3313); striking / force bolt destroy it (zap.c:3314-3318,
  dbridge.c:878 destroy_drawbridge: the span becomes moat, no more toggles); so only a tonal instrument makes the
  bridge a crusher (dbridge.c:769 close_drawbridge -> do_entity: every non-flyer, non-phaser on the span or in the
  portcullis dies, the kill is ours).
* engrave.c read_engr_at:340-345: a BURNED engraving reads 'Some text has been burned into the floor here.' -- the
  inventory parser only knew 'Something is ...' (dust, engraved), so a burned Elbereth read as no engraving at all;
  with castle_v2 active it is parsed (inventory.get_items_below_me).
"""

import json

import nle.nethack as nh

from . import jf_config

TONAL = frozenset({'tooled horn', 'frost horn', 'fire horn', 'wooden flute', 'magic flute', 'wooden harp',
                   'magic harp', 'bugle'})
DRUMS = frozenset({'leather drum', 'drum of earthquake'})
UNLOCK = frozenset({'skeleton key', 'lock pick', 'credit card'})
DIG_TOOLS = frozenset({'pick-axe', 'dwarvish mattock'})
SILENT = frozenset({'opening', 'locking', 'probing', 'undead turning', 'nothing'})   # engrave.c: no message
BLADE_SKILLS = ('dagger', 'knife', 'short sword', 'broadsword', 'long sword', 'two-handed sword', 'scimitar', 'saber',
                'axe')

# runtime state, per game (devrun/seqab play one game per process; DiveLogic.__init__ calls new_game() for hosts that
# play several). The bundle's jf_config values are NOT reset by new_game(): a later episode in the same process keeps
# them -- every bundle flag acts only in the castle zone or with a wand of wishing in hand -- and roles.apply() (which
# runs before the new DiveLogic) is never clobbered.
_state = {'active': False, 'turned_on': (), 'logged': set()}


def active():
    """True once the bundle has been applied in this game (the castle zone reached with CASTLE_V2 on)."""
    return _state['active']


def new_game():
    """A new game (DiveLogic.__init__): forget this module's per-game state. No jf_config change."""
    _state['active'] = False
    _state['turned_on'] = ()
    _state['logged'] = set()


def apply_bundle(agent=None, why=''):
    """CASTLE_V2: turn the crusher route's flags on (once per game). Returns True if it acted now."""
    if not jf_config.CASTLE_V2 or _state['active']:
        return False
    turned = []
    for name in jf_config.CASTLE_V2_BUNDLE:
        if hasattr(jf_config, name):
            if getattr(jf_config, name) is not True:
                turned.append(name)
            setattr(jf_config, name, True)
    _state['turned_on'] = tuple(turned)
    _state['active'] = True
    if agent is not None:
        agent.log(f'CASTLE_V2 bundle on ({why}): {",".join(turned) or "already on"}')
    return True


def in_castle_zone(dive, level):
    """The Dungeons of Doom at depth >= 25 below Medusa's level (or Medusa not seen: a trap door can skip her level --
    vk's LANDING_DIRECT makes the same call and verifies by ear), or the recognised castle. dungeon.def puts the castle
    at the bottom of a 25-29 level Dungeons and Medusa 1-4 above it, so nothing above Dlvl 25 can be the castle; 92% of
    dev arrivals (732 of the first 800 arrival logs) had seen Medusa's level first."""
    from .level import Level
    agent = dive.agent
    if level.dungeon_number != Level.DUNGEONS_OF_DOOM:
        return False
    key = level.key()
    castle = getattr(dive, 'castle', None)
    if castle is not None and castle.castle_key is not None and castle.castle_key == key:
        return True
    if agent.blstats.depth < 25:
        return False
    medusa = getattr(dive, 'medusa_level', None)
    return medusa is None or (tuple(medusa) != tuple(key) and int(medusa[1]) < int(level.level_number))


def on_update(dive, level, key):
    """DiveLogic.update hook (called only when CASTLE_V2 or CASTLE_CENSUS_LOG is on)."""
    agent = dive.agent
    if jf_config.CASTLE_V2 and not _state['active'] and in_castle_zone(dive, level):
        apply_bundle(agent, f'depth {agent.blstats.depth}, level {tuple(int(v) for v in key)}')
    if jf_config.CASTLE_CENSUS_LOG:
        castle = getattr(dive, 'castle', None)
        if castle is not None and castle.castle_key is not None and castle.castle_key == key:
            k = tuple(int(v) for v in key)
            if k not in _state['logged']:
                _state['logged'].add(k)
                try:
                    agent.log('CASTLE_V2 census ' + json.dumps(census(dive, level), sort_keys=True,
                                                               separators=(',', ':')))
                except Exception as e:   # diagnostics only: never let the log line cost a game
                    agent.log(f'CASTLE_V2 census failed: {e!r}')


# ------------------------------------------------------------------ the census

def _names(item):
    return {getattr(o, 'name', None) or '' for o in item.objs}


def _cat(item):
    return item.category


def wand_class(item, inv=None):
    """A wand's identity ('striking'), its engrave class ('silent' = opening/locking/probing/undead turning/nothing,
    'sleep/death', ...) or 'unknown' (several classes still possible)."""
    names = _names(item) - {''}
    if inv is not None:
        try:
            if inv.is_known_empty(item) or item.comment == 'EMPT':
                return 'empty'
        except Exception:
            pass
    if len(names) == 1:
        return next(iter(names))
    if names and names <= SILENT | {'secret door detection', 'create monster'}:
        return 'silent'
    if names == {'sleep', 'death'}:
        return 'sleep/death'
    if names <= {'teleportation', 'make invisible', 'cancellation'}:
        return 'vanish'
    return 'unknown'


def kit(agent):
    """Entry-relevant items at this moment: counts and flags (JSON-friendly)."""
    inv = agent.inventory
    out = {'tonal': [], 'tonal_sure': False, 'drum': False, 'wands': {}, 'scrolls': {}, 'potions_lev': 0,
           'potions_unknown': 0, 'rings': {}, 'rings_unknown': 0, 'boots': [], 'amulets': [], 'unlock': False,
           'dig_tool': False, 'marker': False, 'excalibur': False, 'blade': False, 'oilskin': False, 'mr': False,
           'magic_lamp_maybe': False}
    for it in list(inv.items):
        names = _names(it)
        text = (it.text or '')[:60]
        cat = _cat(it)
        if cat == nh.TOOL_CLASS:
            if names & TONAL:
                out['tonal'].append(text)
                if names <= TONAL:
                    out['tonal_sure'] = True
            if names & DRUMS and not names & TONAL:
                out['drum'] = True
            if names & UNLOCK:
                out['unlock'] = True
            if names & DIG_TOOLS:
                out['dig_tool'] = True
            if 'magic marker' in names:
                out['marker'] = True
            if 'magic lamp' in names:
                out['magic_lamp_maybe'] = True
        elif cat == nh.WEAPON_CLASS:
            if 'Excalibur' in text:
                out['excalibur'] = True
            if names & DIG_TOOLS:
                out['dig_tool'] = True
            sk = {getattr(o, 'skill', None) for o in it.objs}
            if any(isinstance(s, str) and s in BLADE_SKILLS for s in sk) or \
                    any(w in text for w in ('dagger', 'knife', 'sword', 'saber', 'scimitar', 'katana', 'axe')):
                out['blade'] = True
        elif cat == nh.WAND_CLASS:
            c = wand_class(it, inv)
            out['wands'][c] = out['wands'].get(c, 0) + 1
        elif cat == nh.SCROLL_CLASS:
            if it.is_unambiguous():
                n = it.object.name
                if n in ('earth', 'scare monster', 'teleportation', 'taming', 'magic mapping', 'fire', 'genocide',
                         'charging', 'remove curse'):
                    out['scrolls'][n] = out['scrolls'].get(n, 0) + int(it.count or 1)
            else:
                out['scrolls']['unknown'] = out['scrolls'].get('unknown', 0) + 1
        elif cat == nh.POTION_CLASS:
            if it.is_unambiguous():
                if it.object.name == 'levitation':
                    out['potions_lev'] += int(it.count or 1)
            elif 'levitation' in names:
                out['potions_unknown'] += 1
        elif cat == nh.RING_CLASS:
            if it.is_unambiguous():
                n = it.object.name
                if n in ('levitation', 'teleport control', 'polymorph control', 'conflict', 'free action',
                         'teleportation', 'invisibility'):
                    out['rings'][n] = out['rings'].get(n, 0) + 1
            else:
                out['rings_unknown'] += 1
        elif cat == nh.ARMOR_CLASS:
            if it.is_unambiguous():
                n = it.object.name
                if n in ('levitation boots', 'water walking boots', 'speed boots', 'jumping boots'):
                    out['boots'].append(n)
                if n == 'oilskin cloak':
                    out['oilskin'] = True
                if n in ('cloak of magic resistance', 'gray dragon scale mail', 'gray dragon scales') and it.equipped:
                    out['mr'] = True
            elif 'levitation boots' in names or 'water walking boots' in names:
                out['boots'].append('unknown')
        elif cat == nh.AMULET_CLASS:
            if it.is_unambiguous():
                n = it.object.name
                if n in ('amulet of life saving', 'amulet of magical breathing', 'amulet of reflection'):
                    out['amulets'].append(n)
    return out


def routes(agent, k):
    """The entry routes the kit makes possible (castle_v2.md section 2), whatever switches are on."""
    spells = set(getattr(agent.character, 'known_spells', {}) or {})
    w = k['wands']
    destroyer = bool(w.get('striking') or 'force bolt' in spells)
    opener = bool(w.get('opening') or 'knock' in spells)
    closer = bool(w.get('locking') or 'wizard lock' in spells)
    fill = bool(k['scrolls'].get('earth') or w.get('cold') or k['potions_lev'] or k['rings'].get('levitation') or
                'levitation boots' in k['boots'] or 'water walking boots' in k['boots'])
    return {
        'crusher': bool(k['tonal']) or (opener and closer),   # the bridge can be lowered AND raised again
        'opener_once': opener and not k['tonal'],
        'opener_maybe': bool(w.get('silent')) and not k['tonal'],
        'destroyer': destroyer,
        'destroy_fill': destroyer and fill,
        'lift': bool(k['potions_lev'] or k['rings'].get('levitation') or
                     'levitation boots' in k['boots'] or 'water walking boots' in k['boots']),
        'xorn': bool(w.get('polymorph')) and bool(k['rings'].get('polymorph control')),
        'wish': bool(w.get('wishing')),
    }


SWITCHES = ('CASTLE_V2', 'PASSTUNE_CRUSHER', 'CASTLE_INNER', 'CASTLE_PASSTUNE', 'CASTLE_WISH_FIRST', 'CASTLE_PASSAGE',
            'CASTLE_TREASURY', 'CFP_XORN', 'FRONT_DOOR', 'FRONT_V3', 'LANDING_DIRECT', 'TC_CASTLE_GAMBLE')


def lane(r):
    """The lane the castle code is expected to run first with the switches in force (the preempt order: the wish
    route, the crusher / passtune lanes, the xorn walk, the lift passage), or 'none' (the passage gives up: 'nothing
    that crosses water')."""
    if r['wish'] and jf_config.WISH_TELEPORT_ROUTE:
        return 'wish'
    if r['crusher'] and jf_config.PASSTUNE_CRUSHER:
        return 'crusher'
    if r['crusher'] and jf_config.CASTLE_PASSTUNE:
        return 'passtune'
    if r['xorn'] and jf_config.CFP_XORN:
        return 'xorn'
    if r['lift'] and jf_config.CASTLE_PASSAGE:
        return 'lift'
    return 'none'


def census(dive, level):
    agent = dive.agent
    bl = agent.blstats
    k = kit(agent)
    r = routes(agent, k)
    char = agent.character
    role = None
    try:
        rev = {v: n for n, v in char.name_to_role.items()}
        role = rev.get(char.role)
    except Exception:
        pass
    lnd = getattr(dive, '_landing_direct', {}).get(level.key(), {}) or {}
    medusa = getattr(dive, 'medusa_level', None)
    return {
        'v': 1, 'turn': int(bl.time), 'depth': int(bl.depth), 'level': [int(v) for v in level.key()],
        'xl': int(bl.experience_level), 'hp': int(bl.hitpoints), 'hpmax': int(bl.max_hitpoints),
        'pw': int(bl.energy), 'pwmax': int(bl.max_energy), 'ac': int(bl.armor_class),
        'pos': [int(bl.x) - 8, int(bl.y) - 3], 'role': role,
        'medusa': int(medusa[1]) if medusa is not None else None,
        'how': 'landing' if lnd.get('state') in ('direct', 'verified') else 'dig',
        'spells': sorted(getattr(char, 'known_spells', {}) or {}),
        'kit': k, 'routes': r, 'lane': lane(r), 'v2_active': active(),
        'switches': {s: bool(getattr(jf_config, s, False)) for s in SWITCHES},
    }


# ------------------------------------------------------------------ CASTLE_V2_BURN

def fire_wand(agent):
    """A known, not known-empty wand of fire (engrave.c zapwand WAN_FIRE: type BURN). Lightning is left out: it blinds
    the engraver (engrave.c: 'You are blinded by the flash!'), and the passtune lane waits out blindness."""
    inv = agent.inventory
    for it in list(inv.items):
        if it.category == nh.WAND_CLASS and it.is_unambiguous() and it.object.name == 'fire' and \
                it.comment != 'EMPT':
            try:
                if inv.is_known_empty(it):
                    continue
            except Exception:
                pass
            return it
    return None


def burn_due(agent, tries):
    """CASTLE_V2_BURN: burn the Elbereth now? (castle_v2 active, a fire wand, at most 2 tries on this square)."""
    return bool(jf_config.CASTLE_V2 and jf_config.CASTLE_V2_BURN and active() and tries < 2 and
                fire_wand(agent) is not None)


_WRITE_PROMPT = None


def burn_elbereth(agent, log=None):
    """CASTLE_V2_BURN: engrave Elbereth with the known wand of fire (castle_tune.PassTune._burn's prompt walk:
    'What do you want to write with?' -> the wand; 'Do you want to add to the current engraving?' -> n (a dust one is
    wiped first, engrave.c); 'What do you want to burn into the floor here?' -> Elbereth). True when the square then
    reads Elbereth (the burned-text parse is on while castle_v2 is active)."""
    import re
    from nle.nethack import actions as A
    global _WRITE_PROMPT
    if _WRITE_PROMPT is None:
        _WRITE_PROMPT = re.compile(r'What do you want to (burn|write|engrave|scrawl|add)')
    wand = fire_wand(agent)
    if wand is None:
        return False
    letter = agent.inventory.items.get_letter(wand)

    def gen():
        if 'What do you want to write with?' not in (agent.single_message or ''):
            yield A.Command.ESC
            return
        yield letter
        for _ in range(12):
            msg = agent.single_message or ''
            if 'Do you want to add to the current engraving?' in msg:
                yield 'n'
                continue
            if _WRITE_PROMPT.search(msg):
                yield from 'Elbereth'
                yield '\r'
                break
            if agent._observation['misc'][2]:
                yield ' '
                continue
            return
        for _ in range(6):
            if not agent._observation['misc'][2]:
                break
            yield ' '

    with agent.atom_operation():
        agent.step(A.Command.ENGRAVE, gen())
        agent.inventory.get_items_below_me()
    ok = (agent.inventory.engraving_below_me or '').lower() == 'elbereth'
    if log is not None:
        log(f'CASTLE_V2 burn Elbereth with {wand.text!r}: {"ok" if ok else "failed"} {(agent.message or "")[:120]!r}')
    return ok
