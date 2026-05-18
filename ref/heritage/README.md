# ref/heritage

Genuine E-mu Emulator X **Filter** template XML — primary-source vendor
files, the `<designer-section>` arrays behind FRAME_BANK.md Tier 2.

- **Origin:** `Emulator X Family / Templates (2) / Filter / *.xml` — the
  clean vendor factory set (69 templates), no user-authored experiments.
- **Use:** reference / measurement basis. Never shipped in df2.
- `heritage_designer_sections.json` is regenerated from these XML by
  `tools/extract_designer_sections.py` (`heritage-designer-sections-v2`).
  It supersedes the old NotebookLM-derived JSON
  (`extracted_from: tests/fixtures/notebooklm`), which is NOT carried.

To regenerate after adding/changing XML:

    python tools/extract_designer_sections.py ref/heritage ref/heritage/heritage_designer_sections.json

Note: debug/scratch templates are deliberately excluded. Anything named
`hedz*`, `tb*`, `morph*q*`, bare numbers (`100`, `50`, `3`), or short
junk strings (`d`, `w`, `sd`, `ssssss`) is a debug preset — not vendor
material, not a calibration target. They live only in the fuller
`Templates/Filter` set and are not carried.
