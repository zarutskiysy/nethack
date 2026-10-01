# Changes over the parent engine (pf_s25p)

- **Force bolt for Wizards** (`FORCE_BOLT`): the engine never cast force bolt in fights. Wizards now cast it
  at the best hostile on a clear straight line (adjacent: preferred over melee).
- **Spell direction fix**: `Agent.cast` sent the compass string as keystrokes (`'s'` is not a direction key,
  `'n'` is south-east), so every aimed cast was wasted; only self-cast (`'.'`) heals worked.
