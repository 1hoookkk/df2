export const meta = {
  name: 'trench-listen-loop',
  description: 'Author bold, diverse TRENCH bodies from the E-mu filter-type vocabulary, drive + render on pink noise (and real material if given), gate against the $99-149 PREMIUM bar (drives the AGC, bold morph, distinctive, middle emerges, stable), and assemble a ranked comparison + audition page for the ear to pick.',
  whenToUse: 'Fire to generate a fresh audition set of premium candidate bodies for a cartridge. Re-fire with a keeper as seed to spin siblings/variations. The machine culls weak/broken/timid/dupes; the EAR chooses.',
  phases: [
    { title: 'Generate', detail: 'one agent per filter-type recipe, bold + KIN, via tools/voxbench' },
    { title: 'Verify', detail: 'adversarial premium gate: drives AGC, bold morph, middle emerges, stable' },
    { title: 'Synthesize', detail: 'distinctiveness pass + comparison grid + audition page + premium ranking' },
  ],
}

// ---- args -----------------------------------------------------------------
const A = (args && typeof args === 'object') ? args : {}
const DRIVE = A.drive || 3.0
const SOURCE_WAV = A.source_wav || ''          // optional real-material wav (808/vocal/drum)
const RUN = A.run_dir || 'dev/tmp/loop_run'

// ---- the recipe set: bold, diverse, spans the vocabulary + tame->violent ---
const ALL_RECIPES = [
  { name: 'hedz_ahee', kind: 'Hedz crosser (bandpass + paired ZEROS, carved + airy)',
    intent: 'ah -> ee, the decoded Talking-Hedz structure: anchors [2440,4500,9000] Hz; 2 crossers pinned to slots 4&5 that swap: crosser_a 730->270 (falls), crosser_b 1090->2290 (rises) = the talking. Q TIGHTENS radius r_broad 0.90 -> r_sharp 0.992. Use voxbench.bandpass / or tools.corner_words.hedz_body + corner_words().' },
  { name: 'hedz_ooee', kind: 'Hedz crosser (bandpass + ZEROS), big F2 flight',
    intent: 'oo -> ee: anchors [2440,4500,9000]; crosser_a 870->2290 (F2 flies up, the classic oo-ee), crosser_b 300->270; r_broad 0.90 -> r_sharp 0.993. A bold bright sweep.' },
  { name: 'contrary_eeah', kind: 'Contrary Bandpass (PEAK + DIP together, dramatic)',
    intent: 'ee -> ah via voxbench.contrary_bp: a peak that FALLS (2290->1090) and a dip that RISES (700->1800) - opposite motion = the contrary crossing. Add a 4P-LP body (lp4 ~3500) so it sits. Q drives peak/dip depth Q0~+12 -> Q100~+22.' },
  { name: 'swept31_ahee', kind: '6-Pole Lowpass + Swept EQ 3:1 (clean, bright, dramatic)',
    intent: 'ah -> ee: voxbench.lp6(4000) foundation + 3 swept_eq formants (oct_low=3,oct_high=1) F1 730->270, F2 1090->2290, F3 2440->3010, registered. Q gain +10 (Q0) -> +24 (Q100). No zeros - the clean counterpart.' },
  { name: 'resbody_eeah', kind: '4-Pole RESONANT Lowpass body + bandpass formants (bodied + carved)',
    intent: 'ee -> ah: a resonant 4P-LP body (two voxbench.lowpass at fc~1600, last q~2.0 = body bump) + 3 bandpass(formant) poles ee->ah (registered) so it carries zeros. Q drives gain/radius up. Fuller, aggressive.' },
  { name: 'tilt_tone', kind: 'Spectral Tilt (the new fractional-slope type - NON-vocal variety)',
    intent: 'a tone-tilt morph: voxbench.spectral_tilt(12, alpha) with Morph sliding alpha -0.7 (dark) -> +0.35 (bright), pivot 1100; Q100 pushes alpha to -1.0 / +0.6 (more extreme). Tame the bright extreme so max peak < ~28 dB. A whole-spectrum darken<->brighten - roster variety.' },
  { name: 'phaser_sweep', kind: 'Phaser (sliding NOTCH comb, swirly)',
    intent: '4 voxbench.phaser_notch notches that SLIDE across the morph (e.g. home [400,900,1800,3600] -> away [600,1300,2600,5200], registered to slots) over a gentle lp4(5000) body. Q = notch depth (Q0 shallow -> Q100 deep). Swirly comb character.' },
  { name: 'darktalk_ooah', kind: 'Dark talk (bandpass + ZEROS, oo->ah, intimate carved)',
    intent: 'oo -> ah on a dark body: bandpass(formant) poles oo(300,870,2240) -> ah(730,1090,2440) registered, + lp4(2800) dark foundation. Q tightens. Rounder, intimate, carved valleys.' },
]
const RECIPES = (A.recipes && Array.isArray(A.recipes))
  ? ALL_RECIPES.filter(r => A.recipes.includes(r.name))
  : ALL_RECIPES

// ---- schemas --------------------------------------------------------------
const BODY = {
  type: 'object', additionalProperties: false,
  required: ['name','built','types_used','recipe_summary','verify','body_path','glide_wav','escalation_wav','diagonal_wav','curve_png','notes'],
  properties: {
    name: { type: 'string' },
    built: { type: 'boolean', description: 'true if the 240-byte body + renders were produced' },
    types_used: { type: 'array', items: { type: 'string' } },
    recipe_summary: { type: 'string', description: 'the actual freqs/types/Q-range used' },
    verify: { type: 'object', description: 'the dict returned by voxbench.verify_body (stable, drives_agc, q_escalation_db, middle_emerges, has_zeros, max_peak_db, dominant_hz_home_mid_away, crest_dry, crest_driven)',
      additionalProperties: true },
    body_path: { type: 'string' }, glide_wav: { type: 'string' },
    escalation_wav: { type: 'string' }, diagonal_wav: { type: 'string' }, curve_png: { type: 'string' },
    notes: { type: 'string', description: 'what is bold/distinctive about it, and any concern' },
  },
}
const VERDICT = {
  type: 'object', additionalProperties: false,
  required: ['name','tier','stable','drives_agc','bold_morph','middle_emerges','premium_score','reasons'],
  properties: {
    name: { type: 'string' },
    tier: { type: 'string', enum: ['premium','usable','weak','broken'] },
    stable: { type: 'boolean' }, drives_agc: { type: 'boolean' },
    bold_morph: { type: 'boolean', description: 'home->away travels far / Q escalates hard - not a timid nudge' },
    middle_emerges: { type: 'boolean', description: 'the M50 is a genuine intermediate (registration worked), not a jump' },
    premium_score: { type: 'number', description: '0-100 worth-paying proxy (soft pre-sort, NOT a verdict - the ear decides)' },
    reasons: { type: 'string' },
  },
}
const SYNTH = {
  type: 'object', additionalProperties: false,
  required: ['comparison_png','audition_html','shortlist','summary'],
  properties: {
    comparison_png: { type: 'string' }, audition_html: { type: 'string' },
    shortlist: { type: 'array', items: { type: 'object', additionalProperties: true } },
    summary: { type: 'string' },
  },
}

// ---- prompts --------------------------------------------------------------
const LAWS = `
THE LAWS (from this session - enforce them):
- DRIVE THE AGC or the engine is asleep = clinical/thin/WEAK = not worth paying for. audition(drive=${DRIVE}).
- Q drives the escalation: Q0 = casual, Q100 = shout (peaks rise hard with Q). Lerp gain or tighten radius by q01.
- REGISTRATION: each voice keeps its SAME stage slot in both corners so the MIDDLE glides (a real intermediate), not jumps. The middle is the product.
- KIN corners: shared skeleton so the middle is coherent (not mush).
- BOLD: the morph must TRAVEL far (a journey), not a timid nudge - this has to be worth $99-149 AUD.
- ZEROS carve the valleys (bandpass/contrary/phaser have them; peaking-EQ/swept_eq do not).
`
const API = `
Use ONLY tools/voxbench.py (READ IT FIRST for the exact API). Run python as:
  cd C:/Users/hooki/df2 && PYTHONPATH=C:/Users/hooki/df2 python <script.py>
Key: from tools import voxbench as V. Primitives return ONE stage (5-tuple) except lp4/lp6/hp4 (LIST). A corner = exactly 6 stages. V.build_body({"M0_Q0":[...6...],"M100_Q0":[...],"M0_Q100":[...],"M100_Q100":[...]}).
V.audition(body, name, outdir, drive=${DRIVE}) -> (measure_rows, curve_png). V.verify_body(body, drive=${DRIVE}) -> metrics dict.
Do NOT reimplement any packed/encode/decode math. Output dir: ${RUN}/<name>.`

const genPrompt = (r) => `Author ONE premium TRENCH body, approach "${r.name}". This is for a cartridge that must be worth $99-149 AUD - make it BOLD and distinctive, not safe.

FILTER TYPE: ${r.kind}
RECIPE INTENT: ${r.intent}
${LAWS}
${API}

STEPS: (1) Read tools/voxbench.py. (2) Write ${RUN}/${r.name}.py implementing the 4 KIN corners per the recipe. (3) Run it: build_body -> audition(drive=${DRIVE}) -> verify_body. (4) Inspect verify metrics; if NOT stable, or drives_agc is false (too weak), or middle_emerges is false (registration broke), or max_peak > 40 (near blow-up), ITERATE (adjust freqs/gain/radius/fc) up to 4x until it is stable + drives the AGC + the middle emerges. Bold but not broken.

Return the BODY schema. Put the voxbench.verify_body dict verbatim in "verify". Absolute paths for body_path/glide_wav/escalation_wav/diagonal_wav (..._glide_casualQ.wav / ..._escalation_midM.wav / ..._diagonal.wav) / curve_png.`

const verifyPrompt = (body, r) => `Adversarially verify body "${r.name}" against the $99-149 PREMIUM bar. Be skeptical - default to a LOWER tier when unsure. The machine only culls broken/weak/timid/dupe; the ear makes the final call, so do not pass weak work through.

Body: ${JSON.stringify({name: body && body.name, recipe: body && body.recipe_summary, built: body && body.built})}
Independently RE-RUN the metrics yourself (do not just trust the generator):
  cd C:/Users/hooki/df2 && PYTHONPATH=C:/Users/hooki/df2 python -c "from tools import voxbench as V; from pathlib import Path; import json; print(json.dumps(V.verify_body(Path(r'${body && body.body_path}').read_bytes(), drive=${DRIVE})))"
Judge:
- broken: not stable / not finite / max_peak >= 45 / build failed.
- weak: stable but drives_agc=false (AGC asleep = clinical/thin) OR q_escalation_db < ~6 (Q does nothing) OR the morph is timid (home/away dominant freqs barely move). Weak is NOT worth paying for - cull it.
- usable: stable, drives the AGC, real escalation, middle emerges - a solid pack body.
- premium: all of usable PLUS a bold, characterful journey (big morph travel, carved or strongly voiced, the middle clearly the product).
premium_score 0-100 = your worth-paying proxy (soft pre-sort, not a gate).
Return the VERDICT schema.`

// ---- run ------------------------------------------------------------------
log(`trench-listen-loop: ${RECIPES.length} recipes, drive x${DRIVE}${SOURCE_WAV ? `, real source ${SOURCE_WAV}` : ', pink noise'}`)

const pairs = await pipeline(
  RECIPES,
  (r) => agent(genPrompt(r), { schema: BODY, phase: 'Generate', label: `gen:${r.name}` }),
  (body, r) => body && body.built
      ? agent(verifyPrompt(body, r), { schema: VERDICT, phase: 'Verify', label: `verify:${r.name}` }).then(v => ({ body, verdict: v }))
      : null,
)

const kept = pairs.filter(Boolean).filter(p => p.verdict && p.verdict.tier !== 'broken' && p.verdict.tier !== 'weak')
const culled = pairs.filter(Boolean).filter(p => !(p.verdict && p.verdict.tier !== 'broken' && p.verdict.tier !== 'weak'))
log(`kept ${kept.length}/${pairs.filter(Boolean).length} (culled weak/broken: ${culled.map(c => c.body && c.body.name).join(', ') || 'none'})`)

phase('Synthesize')
const synthPrompt = `Assemble the GAIN-STAGED audition set from the KEPT candidates (weak/broken already culled). KEPT = ${JSON.stringify(kept.map(p => ({ name: p.body.name, tier: p.verdict.tier, score: p.verdict.premium_score, body_path: p.body.body_path, verify: p.body.verify })))}.

This is an INSERT FX judged on the PRE-FILTER DRIVE LADDER (the workflow's spine): clean input = max resonance, slam = density, crush = bit-grit. Write a python script under ${RUN} using tools/voxbench (READ voxbench.py first), then:

1) DRIVE-LADDER RENDERS (the verdict): for each kept body, render it up the ladder on REAL bass material via V.audition_fx. Do BOTH a reese and an 808:
     from tools import voxbench as V
     from pathlib import Path
     b = Path(body_path).read_bytes()
     V.audition_fx(b, name, r'${RUN}/'+name, source_name='reese')   # -> clean/slam/slammed/crush WAVs
     V.audition_fx(b, name, r'${RUN}/'+name, source_name='808')
   ${SOURCE_WAV ? `ALSO render on the REAL user source: V.audition_fx(b, name, dir, source_name='user', source=open(r'${SOURCE_WAV}','rb').read()) - skip gracefully if it will not load (must be 39062.5 Hz float32 mono raw/wav) and note it.` : ''}
2) DISTINCTIVENESS pass: load each kept body240, compare their MIDDLE (M50 Q0) curves; flag near-duplicate pairs (a $99-149 pack needs RANGE). Note dupes in the summary (do not delete).
3) COMPARISON GRID: one PNG (${RUN}/COMPARISON.png) - a panel per kept body (home/MID/away Q0 + MID Q100), consistent axes, title = name + tier + score.
4) AUDITION PAGE: ${RUN}/audition.html - one card per kept body ordered by premium_score desc: name, tier, score, a one-line musical why, the curve, and a DRIVE-LADDER row of <audio controls> (reese clean|slam|slammed|crush, then 808 clean|slam|slammed|crush${SOURCE_WAV ? ', then user-source ladder' : ''}) with relative paths. NO DSP/pole/zero/EMU vocabulary on the page (producer surface rules). Clean dark style; the point is hearing each body's RANGE from clean-resonant to slammed-dense.

Return the SYNTH schema: comparison_png, audition_html (absolute path), shortlist (ranked [{name,tier,score,why}] - favour bodies with RANGE across the ladder), summary (what the pack covers clean->slammed, any dupes, what is missing for a full premium cartridge).`

const synth = await agent(synthPrompt, { schema: SYNTH, phase: 'Synthesize', label: 'synthesize' })

return {
  generated: pairs.filter(Boolean).length,
  kept: kept.map(p => ({ name: p.body.name, tier: p.verdict.tier, score: p.verdict.premium_score })),
  culled: culled.map(p => ({ name: p.body && p.body.name, tier: p.verdict && p.verdict.tier, why: p.verdict && p.verdict.reasons })),
  comparison_png: synth.comparison_png,
  audition_html: synth.audition_html,
  shortlist: synth.shortlist,
  summary: synth.summary,
}
