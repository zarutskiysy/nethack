# Changes over the parent engine (pf_s25p)

- **Force bolt for Wizards** (`FORCE_BOLT`): the engine never cast force bolt in fights. Wizards now cast it
  at the best hostile on a clear straight line (adjacent: preferred over melee).
- **Spell direction fix**: `Agent.cast` sent the compass string as keystrokes (`'s'` is not a direction key,
  `'n'` is south-east), so every aimed cast was wasted; only self-cast (`'.'`) heals worked.
- **Identity router** as in daglar-dragomirov/nethacker@e29eb82 (the verified-tier leader): Healers (pf_hg, pf_hh),
  human Priests (pf_pa) and Samurai (pf_v35) play specialist engines; everyone else plays nhbot with DIVE_XL 8
  (nhbot is then identical to e29eb82's pf_base apart from the changes listed here).
- `roles.py`: per-identity overrides of engine settings (only for nhbot identities).
