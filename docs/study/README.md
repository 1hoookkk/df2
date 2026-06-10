# STUDY ONLY — clean-room reference analysis

Everything in this folder is **reference-derived analysis of the E-mu P2K filter
types**, promoted out of `dev/tmp/` so it survives temp wipes. It exists to teach
the grammar (section roles, rails, zero behavior, move families) for authoring
**originals**.

**Never copy coefficients, packed bytes, names, or preset tables from these files
into shipping bodies.** (Per the clean-room law in `CLAUDE.md`.)

## Contents

- `P2K_atlas.md` / `P2K_atlas.json` — all 50 types decoded in real format
  (4 corners × 6 sections, pole/zero Hz + radius per row).
- `p2k_full_vocabulary_report.md` + `frequency_rails.csv` + `row_motion_vocab.json`
  — row-role taxonomy (remote cut, air kill, mouth, bite…), the five move
  families, the shared rails (~2 Hz sub, 780–785 Hz mouth, 3790–4130 Hz tear,
  8250/9650/16500/17950 Hz air kills).
- `p2k_reference_fundamentals_report.md` / `_summary.json` — per-reference
  structure: tilts, spans, zero offsets, anchor+mover stats.
- `p2k_reference_grammar_summary.json` — zero grammar: 58.5% of zeros within
  1 oct of their pole (local tear), 28.2% remote (>1.5 oct kill rails); every
  sampled row carries a zero; S6 zero pinned at r=1.000.
- `zero_dominance_report.json` — ablation: poles ≈59% of morph motion,
  zeros ≈22%, gain <3%.
- `P2K_FAMILY_REVERSE_ENGINEERING.md` — clean-room family study notes.
