# Full P2K Vocabulary Study

Study-only. This mines the 50 P2K families and all 200 variant bodies through the shipped packed path. It does not write packed words, coefficients, or exact corner tables.

## Scope

- Source bodies: `ref/p2k_variants/P2k_*/variant_*.bin`
- Count: 50 skins, 200 variant bodies
- Runtime path: `pyruntime/trench_ffi.py` calling `C:\Users\hooki\df2\target\release\trench_core.dll`
- Object read: 4 corners x 6 rows x 5 packed u16 words = 240 bytes
- Grid read: 5x5 MORPH x SECONDARY for every variant body
- Corners in this report: HOME = M0/S0, AWAY = M1/S0, PUSH HOME = M0/S1, PUSH AWAY = M1/S1
- Combined check: variant0 concatenation match = `True`; combined CSVs were treated as comparison material because their own header says the raw-byte decode is unverified.

## Biggest Move Types

- **high bank collapse**: 25 skins. High rows or high cuts fall into mouth/bite instead of simply opening upward.
- **remote-cut violence**: 13 skins. Cuts sit far from their poles and move as kill rows.
- **talking vowel glide**: 7 skins. Mouth rows move against vowel/formant rails while low/body rows keep the frame.
- **shelf/cliff frame**: 3 skins. A broad keep/kill frame dominates, with character rows inside it.
- **comb/phaser field**: 2 skins. Several rows make repeated notches or close pole-zero tears.

Blunt read: the language is not "six EQ bands." It is rows that keep, kill, sweep, tighten, collapse, or hold a frame while another row does the talking. The zeros matter as much as the poles. A lot of the violence comes from the cut moving separately from the peak.

## Biggest Row Roles

- **remote cut**: 453 row reads at HOME across the family/variant set. kills a distant band against a peak
- **air kill**: 164 row reads at HOME across the family/variant set. cuts the top hard
- **air cap**: 142 row reads at HOME across the family/variant set. keeps or exposes the top
- **bite**: 113 row reads at HOME across the family/variant set. adds the speaking edge
- **mouth**: 107 row reads at HOME across the family/variant set. carries vowel/body identity
- **blade**: 27 row reads at HOME across the family/variant set. tight high-radius row
- **shelf**: 25 row reads at HOME across the family/variant set. broad rising or falling frame
- **frame**: 24 row reads at HOME across the family/variant set. real-root or broad frame row
- **color row**: 18 row reads at HOME across the family/variant set. smaller local row
- **cliff**: 10 row reads at HOME across the family/variant set. dark falling frame
- **broad frame**: 6 row reads at HOME across the family/variant set. large-span row that shapes the whole response
- **low anchor**: 1 row reads at HOME across the family/variant set. keeps weight low while other rows move

Stage index matters. The same stage number often keeps its job across variants, but it is not a fixed semantic lane. Frequency-sorted views in `skin_summaries.csv` show many places where the row order and the audible order part ways.

## Pole And Zero Corner Language

For each skin family, the short read is:

| skin | move | HOME -> AWAY -> PUSH HOME -> PUSH AWAY | row jobs | build read | standouts |
|---|---|---|---|---|---|
| P2k_000 | high bank collapse | HOME dark shelf -> AWAY comb field -> PUSH HOME hard dark cliff -> PUSH AWAY comb field | S1:cliff; S2:air kill; S3:air cap; S4:air cap; S5:air cap; S6:air cap | likely table assisted | 3 row swaps; middle is violent; very notchy middle; huge Morph move; fixed low keep; rank swaps |
| P2k_001 | high bank collapse | HOME dark shelf -> AWAY dark shelf -> PUSH HOME bite window -> PUSH AWAY dark shelf | S1:air cap; S2:air cap; S3:air cap; S4:air cap; S5:air cap; S6:air kill | likely table assisted | 4 row swaps; middle is violent; huge Morph move; rank swaps |
| P2k_002 | high bank collapse | HOME dark shelf -> AWAY hard dark cliff -> PUSH HOME hard dark cliff -> PUSH AWAY hard dark cliff | S1:remote cut; S2:air kill; S3:air cap; S4:air cap; S5:air kill; S6:air cap | likely table assisted | 8 row swaps; middle is violent; many remote cuts; rank swaps |
| P2k_003 | high bank collapse | HOME hard dark cliff -> AWAY dark shelf -> PUSH HOME comb field -> PUSH AWAY comb field | S1:air kill; S2:air cap; S3:air cap; S4:air cap; S5:air cap; S6:air cap | likely table assisted | 12 row swaps; middle is violent; huge Morph move; huge Push move; rank swaps |
| P2k_004 | high bank collapse | HOME hard dark cliff -> AWAY dark shelf -> PUSH HOME bite window -> PUSH AWAY comb field | S1:air kill; S2:air cap; S3:air cap; S4:air cap; S5:air cap; S6:air cap | likely table assisted | 12 row swaps; middle is violent; huge Morph move; huge Push move; rank swaps |
| P2k_005 | remote-cut violence | HOME dark shelf -> AWAY violent frame -> PUSH HOME hard dark cliff -> PUSH AWAY comb field | S1:remote cut; S2:remote cut; S3:mouth; S4:remote cut; S5:air kill; S6:bite | likely table assisted | 2 row swaps; middle is violent; huge Morph move; many remote cuts; rank swaps |
| P2k_006 | high bank collapse | HOME dark shelf -> AWAY dark shelf -> PUSH HOME dark shelf -> PUSH AWAY comb field | S1:shelf; S2:remote cut; S3:air kill; S4:air cap; S5:air cap; S6:remote cut | likely table assisted | middle is violent; huge Morph move; huge Push move; many remote cuts; fixed low keep |
| P2k_007 | remote-cut violence | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME hard dark cliff -> PUSH AWAY hard dark cliff | S1:bite; S2:air kill; S3:air kill; S4:air kill; S5:air kill; S6:air kill | clearly table/grid driven | 3 row swaps; middle is violent; huge Morph move; huge Push move; many remote cuts; rank swaps |
| P2k_008 | high bank collapse | HOME comb field -> AWAY dark shelf -> PUSH HOME dark shelf -> PUSH AWAY dark shelf | S1:remote cut; S2:bite; S3:cliff; S4:air cap; S5:air cap; S6:air cap | likely table assisted | middle is violent; huge Morph move; fixed low keep |
| P2k_009 | talking vowel glide | HOME dark shelf -> AWAY violent frame -> PUSH HOME dark shelf -> PUSH AWAY comb field | S1:mouth; S2:air kill; S3:mouth; S4:remote cut; S5:mouth; S6:remote cut | likely table assisted | 4 row swaps; middle is violent; many remote cuts; rank swaps |
| P2k_010 | talking vowel glide | HOME dark shelf -> AWAY comb field -> PUSH HOME dark shelf -> PUSH AWAY comb field | S1:mouth; S2:mouth; S3:bite; S4:bite; S5:bite; S6:air kill | likely table assisted | middle is violent; very notchy middle |
| P2k_011 | high bank collapse | HOME hard dark cliff -> AWAY violent frame -> PUSH HOME dark shelf -> PUSH AWAY comb field | S1:remote cut; S2:remote cut; S3:air kill; S4:air cap; S5:air cap; S6:cliff | likely table assisted | 7 row swaps; middle is violent; huge Morph move; huge Push move; many remote cuts; fixed low keep; rank swaps |
| P2k_012 | remote-cut violence | HOME dark shelf -> AWAY comb field -> PUSH HOME dark shelf -> PUSH AWAY comb field | S1:remote cut; S2:mouth; S3:bite; S4:bite; S5:air cap; S6:air kill | likely table assisted | 1 row swaps; middle is violent; many remote cuts |
| P2k_013 | talking vowel glide | HOME dark shelf -> AWAY comb field -> PUSH HOME dark shelf -> PUSH AWAY dark shelf | S1:remote cut; S2:mouth; S3:mouth; S4:bite; S5:bite; S6:air kill | likely table assisted | 1 row swaps; middle is violent; very notchy middle; many remote cuts |
| P2k_014 | high bank collapse | HOME hard dark cliff -> AWAY mouth window -> PUSH HOME comb field -> PUSH AWAY bright shelf | S1:remote cut; S2:remote cut; S3:mouth; S4:mouth; S5:air kill; S6:air cap | likely table assisted | 9 row swaps; middle is violent; huge Morph move; huge Push move; many remote cuts; rank swaps |
| P2k_015 | comb/phaser field | HOME bite window -> AWAY comb field -> PUSH HOME bite window -> PUSH AWAY comb field | S1:shelf; S2:mouth; S3:bite; S4:air cap; S5:air kill; S6:air cap | likely table assisted | middle is violent; very notchy middle |
| P2k_016 | high bank collapse | HOME violent frame -> AWAY dark shelf -> PUSH HOME dark shelf -> PUSH AWAY comb field | S1:remote cut; S2:remote cut; S3:air kill; S4:air cap; S5:air cap; S6:mouth | likely table assisted | 3 row swaps; middle is violent; many remote cuts; rank swaps |
| P2k_017 | remote-cut violence | HOME comb field -> AWAY comb field -> PUSH HOME comb field -> PUSH AWAY mouth window | S1:shelf; S2:frame; S3:remote cut; S4:air cap; S5:air kill; S6:air cap | likely table assisted | 2 row swaps; huge Morph move; many remote cuts; fixed low keep; rank swaps |
| P2k_018 | high bank collapse | HOME comb field -> AWAY hard dark cliff -> PUSH HOME comb field -> PUSH AWAY hard dark cliff | S1:shelf; S2:remote cut; S3:air kill; S4:air cap; S5:air cap; S6:air cap | likely table assisted | 4 row swaps; middle is violent; very notchy middle; huge Morph move; many remote cuts; rank swaps |
| P2k_019 | high bank collapse | HOME comb field -> AWAY dark shelf -> PUSH HOME bite window -> PUSH AWAY mouth window | S1:remote cut; S2:remote cut; S3:mouth; S4:air cap; S5:broad frame; S6:bite | likely table assisted | 4 row swaps; middle is violent; very notchy middle; huge Morph move; huge Push move; many remote cuts; rank swaps |
| P2k_020 | high bank collapse | HOME comb field -> AWAY dark shelf -> PUSH HOME comb field -> PUSH AWAY dark shelf | S1:remote cut; S2:remote cut; S3:mouth; S4:air cap; S5:bite; S6:bite | likely table assisted | middle is violent; very notchy middle; many remote cuts |
| P2k_021 | talking vowel glide | HOME dark shelf -> AWAY dark shelf -> PUSH HOME hard dark cliff -> PUSH AWAY hard dark cliff | S1:remote cut; S2:mouth; S3:mouth; S4:bite; S5:bite; S6:air kill | likely table assisted | middle is violent; very notchy middle; huge Push move; many remote cuts |
| P2k_022 | talking vowel glide | HOME dark shelf -> AWAY dark shelf -> PUSH HOME dark shelf -> PUSH AWAY hard dark cliff | S1:bite; S2:bite; S3:bite; S4:bite; S5:remote cut; S6:air kill | likely table assisted | middle is violent; very notchy middle; huge Push move; many remote cuts |
| P2k_023 | high bank collapse | HOME mouth window -> AWAY comb field -> PUSH HOME comb field -> PUSH AWAY comb field | S1:remote cut; S2:air kill; S3:air kill; S4:air cap; S5:shelf; S6:air cap | likely table assisted | 1 row swaps; very notchy middle; many remote cuts |
| P2k_024 | remote-cut violence | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME hard dark cliff -> PUSH AWAY hard dark cliff | S1:bite; S2:air kill; S3:air kill; S4:air kill; S5:air kill; S6:air kill | clearly table/grid driven | 4 row swaps; middle is violent; huge Morph move; many remote cuts; rank swaps |
| P2k_025 | shelf/cliff frame | HOME comb field -> AWAY dark shelf -> PUSH HOME hard dark cliff -> PUSH AWAY dark shelf | S1:shelf; S2:remote cut; S3:bite; S4:air cap; S5:air cap; S6:air cap | impossible to tell | 5 row swaps; middle is violent; very notchy middle; rank swaps |
| P2k_026 | shelf/cliff frame | HOME comb field -> AWAY hard dark cliff -> PUSH HOME hard dark cliff -> PUSH AWAY hard dark cliff | S1:air cap; S2:air cap; S3:air cap; S4:air cap; S5:air cap; S6:air kill | impossible to tell | middle is violent; very notchy middle; huge Morph move; huge Push move |
| P2k_027 | remote-cut violence | HOME dark shelf -> AWAY comb field -> PUSH HOME hard dark cliff -> PUSH AWAY comb field | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:air kill; S6:bite | likely table assisted | middle is violent; huge Morph move; many remote cuts |
| P2k_028 | remote-cut violence | HOME dark shelf -> AWAY dark shelf -> PUSH HOME dark shelf -> PUSH AWAY mouth window | S1:remote cut; S2:remote cut; S3:mouth; S4:frame; S5:air kill; S6:bite | likely table assisted | 1 row swaps; middle is violent; huge Push move; many remote cuts; fixed low keep |
| P2k_029 | high bank collapse | HOME hard dark cliff -> AWAY violent frame -> PUSH HOME comb field -> PUSH AWAY mouth window | S1:remote cut; S2:remote cut; S3:air kill; S4:air cap; S5:air cap; S6:frame | likely table assisted | 8 row swaps; middle is violent; huge Morph move; huge Push move; many remote cuts; fixed low keep; rank swaps |
| P2k_030 | talking vowel glide | HOME hard dark cliff -> AWAY comb field -> PUSH HOME hard dark cliff -> PUSH AWAY comb field | S1:remote cut; S2:mouth; S3:mouth; S4:bite; S5:bite; S6:air kill | likely table assisted | middle is violent; huge Morph move; many remote cuts |
| P2k_031 | high bank collapse | HOME dark shelf -> AWAY violent frame -> PUSH HOME hard dark cliff -> PUSH AWAY dark shelf | S1:air kill; S2:air kill; S3:air cap; S4:air cap; S5:air cap; S6:remote cut | likely table assisted | 9 row swaps; middle is violent; huge Morph move; huge Push move; many remote cuts; rank swaps |
| P2k_032 | remote-cut violence | HOME dark shelf -> AWAY dark shelf -> PUSH HOME hard dark cliff -> PUSH AWAY bite window | S1:air kill; S2:air cap; S3:air cap; S4:air cap; S5:air cap; S6:air kill | likely table assisted | middle is violent; very notchy middle; huge Morph move; huge Push move; many remote cuts |
| P2k_033 | remote-cut violence | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle is violent; very notchy middle; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_034 | remote-cut violence | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME comb field -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle is violent; very notchy middle; huge Morph move; huge Push move; many remote cuts |
| P2k_035 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:air kill; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle is violent; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_036 | high bank collapse | HOME mixed frame -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:air kill; S2:remote cut; S3:remote cut; S4:air kill; S5:color row; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle is violent; huge Morph move; huge Push move; many remote cuts |
| P2k_037 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:air kill; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_038 | remote-cut violence | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle is violent; huge Morph move; huge Push move; many remote cuts |
| P2k_039 | comb/phaser field | HOME comb field -> AWAY mixed frame -> PUSH HOME comb field -> PUSH AWAY mixed frame | S1:blade; S2:blade; S3:remote cut; S4:low anchor; S5:remote cut; S6:remote cut | clearly table/grid driven | 5 row swaps; unstable packed grid points; middle is violent; huge Morph move; huge Push move; many remote cuts; fixed low keep; rank swaps |
| P2k_040 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle is violent; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_041 | remote-cut violence | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle is violent; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_042 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:air kill; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; very notchy middle; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_043 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:air kill | clearly table/grid driven | unstable packed grid points; middle is violent; very notchy middle; huge Morph move; huge Push move; many remote cuts |
| P2k_044 | remote-cut violence | HOME bright shelf -> AWAY mixed frame -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:remote cut; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle is violent; huge Morph move; huge Push move; many remote cuts |
| P2k_045 | high bank collapse | HOME hard dark cliff -> AWAY mixed frame -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:color row; S4:remote cut; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle is violent; huge Morph move; huge Push move; many remote cuts; fixed low keep |
| P2k_046 | talking vowel glide | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME dark shelf -> PUSH AWAY mixed frame | S1:blade; S2:remote cut; S3:mouth; S4:blade; S5:mouth; S6:blade | clearly table/grid driven | 5 row swaps; unstable packed grid points; middle is violent; very notchy middle; huge Morph move; huge Push move; many remote cuts; rank swaps |
| P2k_047 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:air kill; S4:air kill; S5:remote cut; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle is violent; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_048 | high bank collapse | HOME hard dark cliff -> AWAY hard dark cliff -> PUSH HOME mixed frame -> PUSH AWAY mixed frame | S1:remote cut; S2:remote cut; S3:air kill; S4:remote cut; S5:air kill; S6:remote cut | clearly table/grid driven | unstable packed grid points; middle sags hard; middle loses peak; huge Morph move; huge Push move; many remote cuts |
| P2k_049 | shelf/cliff frame | HOME dark shelf -> AWAY hard dark cliff -> PUSH HOME bright shelf -> PUSH AWAY mixed frame | S1:frame; S2:frame; S3:air kill; S4:air kill; S5:air kill; S6:air kill | clearly table/grid driven | unstable packed grid points; middle is violent; very notchy middle; huge Morph move; huge Push move; many remote cuts; fixed low keep |

## Table Matches

- **likely table assisted**: 29 skins.
- **clearly table/grid driven**: 19 skins.
- **impossible to tell**: 2 skins.

The strongest table signal is the recovered radius rail. Frequency tables line up in patches, especially vowel/mouth values, tube-like ladders, and modal ratios, but the full set does not look like a single textbook table was pasted in. The better read is: grid/compiler rails plus by-ear shaping.

Top repeated rails:

- pole around near-DC (~2 Hz) (sub): 330 endpoint hits across 17 skins
- zero around near-DC (~2 Hz) (sub): 325 endpoint hits across 17 skins
- pole around 780 Hz (mouth): 179 endpoint hits across 31 skins
- zero around 780 Hz (mouth): 175 endpoint hits across 31 skins
- zero around 785 Hz (mouth): 133 endpoint hits across 30 skins
- pole around 785 Hz (mouth): 129 endpoint hits across 27 skins
- zero around 4130 Hz (tear): 50 endpoint hits across 28 skins; near tube oo_25cm:p6
- zero around 8250 Hz (air): 50 endpoint hits across 28 skins; near tube oo_10cm:p5
- zero around 17950 Hz (air): 50 endpoint hits across 26 skins
- zero around 16500 Hz (air): 48 endpoint hits across 27 skins
- pole around 3790 Hz (tear): 43 endpoint hits across 24 skins; near tube oo_18cm:p4
- zero around 790 Hz (mouth): 43 endpoint hits across 24 skins
- zero around 9650 Hz (air): 43 endpoint hits across 16 skins
- zero around 134 Hz (low): 41 endpoint hits across 19 skins
- zero around 8875 Hz (air): 41 endpoint hits across 9 skins; near tube oo_10cm:p5

## What Stands Out

- There are many fixed or repeated cut rails. Some act like kill switches for air or bite rather than local notches.
- Several skins have middles that are more musical than the corners because the packed grid blends rows into a new mouth or bite frame.
- Several skins have bad or dangerous middles: high span, many notches, or a hard peak loss. Endpoint-only judging would miss that.
- Row swaps are real. A serialized row can cross another row in audible frequency order while still keeping its job as the same row.
- Push is often a stress move. It sharpens, kills, collapses, or shifts the cut; it is not just "Morph 2."
- The simple factory-looking families are the most grid-like. The stranger musical families look table-assisted and then hand-shaped.

## Were These Made By Ear Or Table

- **Clearly table/grid driven** means the skin is dense with repeated rails, radius-table hits, and simple family scaling.
- **Likely table assisted** means it follows rails or formant/tube/modal values but still has row choices that look tuned.
- **Likely by-ear sculpted** means weak table matches and odd row/cut choices that read as taste moves.
- **Impossible to tell** means the numbers do not support a stronger call.

The count is in `row_motion_vocab.json` under `construction_read_counts`. The useful answer is not one or the other. The set reads like a compiler/index system with by-ear finishing on the families that matter.

No skin gets a strong "by-ear only" call. The study can see grid rails, radius rails, or table-adjacent frequencies almost everywhere. That does not mean the sounds were not tuned by hand; it means the packed numbers do not support a clean by-ear-only claim.

## What Forge Should Steal

- Move families: high bank collapse, talking vowel glide, remote-cut violence, shelf/cliff frame, comb/phaser field, bass acid sweep, wide sweep bank, push reshaper.
- Foundation frames: low keep, dark cliff, bright shelf, mouth window, comb field.
- Cut roles: local canyon, remote kill, air kill, fixed rail cut, cut walks away.
- Push behavior: tighten, move the cut only, collapse highs, turn a mixed frame into bite.
- By-ear controls: protect the low keep while sweeping mouth/bite; move zero and pole separately with a visible before/after; judge center and diagonal; let Push be stress/tightness.

Do not steal the skins. Steal the moves.

## If We Target Cubes Next, Here Is Exactly What To Inspect And Why

1. Read `ref/p2k_variants/combined/cubes_raw_bytes.csv` as raw cube byte shapes, not decoded Hz.
2. Compare cube byte positions against the 200 decoded P2K variants to find which bytes behave like frequency rails, radius rails, and cut rails.
3. Check whether cube routing bytes select rows, corners, or whole skin families; that tells us whether cubes are row programs or bank selectors.
4. Run only byte-pattern and packed-runtime correlation first. Do not build a cube authoring surface until the row/corner mapping is proven.
5. Use `ref/x3_menu/raw_tables/` only as a side comparison for repeated rail/index behavior.

## Files Written

- `skin_summaries.csv`
- `row_motion_vocab.json`
- `frequency_rails.csv`
- `table_match_report.csv`
- `plots/move_family_counts.png`
- `plots/row_role_heatmap.png`
- `plots/frequency_rails_top.png`
- `plots/skin_family_metric_map.png`
