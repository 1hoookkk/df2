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

Note: the user's own MorphDesigner authoring (`hedz.xml`, `tb.xml`,
`morph0q100.xml`, `morph100q100.xml`, `hedz0.xml`) lives only in the
fuller `Templates/Filter` set, not here. Carry those separately into a
`user_authored/` subfolder if they are needed as calibration targets.
