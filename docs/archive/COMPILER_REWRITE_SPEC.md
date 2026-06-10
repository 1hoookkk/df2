# COMPILER_REWRITE_SPEC.md — df2 / TRENCH forward-compiler rewrite

**Single authoritative spec. Transcribe directly into code.** Two coupled changes:

1. **Musical-intent compiler** that emits **FLAT-ENDED, balanced sections** (peaking bell / low-body / notch) honoring the **LOG morph** — replacing the constant-numerator all-pole resonator that craters the cascade.
2. **One-owner unification**: collapse the 3 forward-compiler copies (WASM `lib.rs`, Python `forge_author_server.py`, plus the implicit param contract) into a single `trench-core/src/compiler.rs`, FFI-exported, called by everyone. `packed.js` stays decode/plot-only.

Evidence tags throughout: **OBSERVED** (proven through the shipped engine/DLL or read in live source) · **INFERRED** · **UNVERIFIED — BUILD-TIME CHECK** (the implementer must run the named test before trusting). Constants: `SR = 39062.5`, `TAU = 2π`, `MAX_RADIUS = 0.999999999999999`.

---

## 1. Goal & the bug being fixed

### 1a. The crater (corner-collapse)
The current section primitive is a **constant-numerator all-pole resonator**:

```
biquad = [g, 0, 0, a1, a2],  g = max(1 - r², 1e-4) * gain   (lib.rs:165-167)
```

An all-pole section rolls off **−12 dB/oct above its pole**. Six of them in series **compound** the rolloff into a crater.

**OBSERVED** (`dev/tmp/flat_sections_verify.py` through the shipped `trench_core.dll` via `packed_probe`): a 6× all-pole stack (poles 150‒11000 Hz, r 0.99‒0.995) spans **215.25 dB** across 40 Hz‒18 kHz, bottoming at **−270.3 dB near Nyquist**, `max_pole_r = 0.995`. That is the "100 dB swing / raw resonators" the brief reported — measured larger, ~215 dB.

**OBSERVED — mechanism corrected (mark this):** the crater is **NOT minifloat underflow**. `allpole_g_underflow.py` shows `g = (1−r²)·gain` encodes to **< 0.01 %** error at all r up to 0.9999 (e.g. g = 0.0002 → word `0x1a36` → decodes 0.000200). The minifloat is innocent. **The crater is purely the all-pole transfer-FUNCTION SHAPE.** The fix is therefore the section *shape*, not the codec.

### 1b. The static-snapshot problem
Today's lane authoring places per-corner snapshots with ad-hoc `brighten × 2^(spread·0.62)` algebra (`law_author.py`) and a hardcoded synthetic away-pole `pf × 1.7` (`studio.js:1231`, labeled empirical, no formula). Travel is specified in **Hz deltas and magic multipliers**, but the runtime morph interpolates **packed minifloat CODES** — so the interior trajectory is **logarithmic**, and Hz-delta authoring fights the engine. The intent model (§3) fixes this by specifying all travel in **octaves**, which is exactly what the log morph delivers.

### 1c. What "done" looks like
- One forward compiler (`trench-core/src/compiler.rs`); WASM, Python, DLL run the **same Rust object code** for params→240 bytes.
- Sections are flat-ended (peak/low-body/notch); a 6-section cascade holds within **~7‒47 dB**, no crater (§2 verified).
- Bodies authored from **musical intent** (anchor/mover/tearer/bloomer + octave travel + contrary motion), travel in octaves over the log morph.
- WASM == Python == trench-core proven **bit-identical** over 240 bytes (§6), retiring the 0.014 dB tolerance that hid the live clamp drift.

---

## 2. The section model — flat-ended biquad TYPES

Replace the all-pole-only branch with **three section types**, each a full biquad `[b0,b1,b2,a1,a2]` already `a0`-normalized, packed via the **existing** `biquad_to_words` (do not add a 4th packing path). Add a `type_id` to the section: **0 = PEAK, 1 = LOW-BODY, 2 = NOTCH**.

RBJ helper (all forms): `w0 = TAU*fc/SR; cw = cos(w0); sw = sin(w0); alpha = sw/(2*Q)`.

### Type 0 — PEAKING bell (RBJ peaking EQ)
0 dB at DC and Nyquist, `+gain_db` bump at `fc` with `Q`. The mover/tearer/bloomer primitive: off-resonance it returns to 0 dB, so cascaded bells **sum their bumps and never crater**.

```
A  = 10^(gain_db/40)
b0 = 1 + alpha*A;   b1 = -2*cw;   b2 = 1 - alpha*A
a0 = 1 + alpha/A;   a1 = -2*cw;   a2 = 1 - alpha/A
return [b0/a0, b1/a0, b2/a0, a1/a0, a2/a0]
```

### Type 1 — LOW-BODY controlled pole-zero shelf
Boost `gain_db` at DC, **unity above the corner**. A matched-radius pole+zero pair (NOT the bare resonator, NOT textbook RBJ low-shelf). All coeffs O(1) (b0 ≈ 0.3‒1.0).

```
A   = 10^(gain_db/20)                                  # linear DC boost
wp  = TAU*fc/SR
rp  = min(exp(-pi*(fc/max(0.3,Q))/SR), 0.9992)         # Q ~ 0.7-0.9 typical
a1  = -2*rp*cos(wp);  a2 = rp*rp
rz  = rp                                               # matched radius
den_dc = 1 + a1 + a2;  den_ny = 1 - a1 + a2
K   = A * den_dc / den_ny
s   = 1 + rz*rz;  t = s*(K-1)/(K+1)                    # t = target b1n
cwz = clamp(-t/(2*rz), -1, 1)
b1n = -2*rz*cwz;  b2n = rz*rz
b0  = den_ny / (1 - b1n + b2n)                         # forces H(Nyquist)=unity
return [b0, b0*b1n, b0*b2n, a1, a2]
# H(DC)=10^(gain_db/20), H(Nyq)=1.
```

> **REJECTED:** bare pole + high zero — was a runaway resonator giving +60 dB. The matched-pair solve above is the correct one.
> **OBSERVED — claim corrected:** the brief's "textbook RBJ low-shelf dies in minifloat" was **not reproduced** — RBJ low-shelf round-trips to < 0.01 dB at fc ≥ 20 Hz, drifts only 0.06 dB at fc = 10 Hz. The controlled pole-zero shelf is still preferred (exact unity-above-corner + exact DC boost, O(1) coeffs), but minifloat death is **not** the reason. Avoid sub-20 Hz shelf corners regardless.

### Type 2 — NOTCH variable depth (`depth_db ≤ 0`)
Matched-angle zero pair (radius `rz`) inside a pole pair (radius `rp` from Q). Unity at DC and Nyquist; controllable null depth at `fc`.

```
wc  = TAU*fc/SR
rp  = min(exp(-pi*(fc/max(0.5,Q))/SR), 0.999)
rz  = clamp(1 - (1-rp)*10^(depth_db/20), 0, 0.99999)
a1  = -2*rp*cos(wc);  a2 = rp*rp
b1n = -2*rz*cos(wc);  b2n = rz*rz
b0  = (1 + a1 + a2)/(1 + b1n + b2n)                    # forces H(DC)=unity
return [b0, b0*b1n, b0*b2n, a1, a2]
# depth at fc ~= 20*log10((1-rz)/(1-rp)).
```

### Packing (UNCHANGED — the existing path)
```
c4 = b0;  c0 = b1/b0 + 2;  c1 = 1 - b2/b0;  c2 = a1 + 2;  c3 = 1 - a2
w0 = encode((c0-c1)/4); w1 = encode(c1); w2 = encode((c2-c3)/4); w3 = encode(c3); w4 = encode(c4/4)
```
All three forms give `b0 > 0` (verified), satisfying the `c4 != 0` guard. They slot into the **pole+zero branch** of `stage_biquad` — PEAK and NOTCH need the full `b1,b2` numerator (the current all-pole branch zeros them; that is the bug).

### Recommended frame layout
Section 0 = LOW-BODY anchor; sections 1‒5 = PEAKING bells and/or NOTCH canyons. Section index = morph pairing (sacred, §3).

### VERIFIED evidence (mark OBSERVED)
**Minifloat round-trip** (encode→decode through shipped core, worst |dB| over 20 Hz‒18 kHz):

| section | params | worst error |
|---|---|---|
| PEAK | fc 1200, Q 4, +12 dB | **0.0031 dB** |
| PEAK | fc 5000, Q 8, +15 dB | **0.0072 dB** (worst bell) |
| LOW-BODY | fc 40‒120, +9/+12/+15 dB | **≤ 0.002 dB**; DC boost within 0.03 dB, Nyq 0.00 dB |
| NOTCH | fc 2000, Q 6, −30 dB | **0.0010 dB** |
| NOTCH | fc 800, Q 4, −18 dB | **0.0012 dB** |

All candidates < 0.01 dB — **minifloat is faithful.**

**6-section cascade corner spread** (240-byte body, `packed_probe` at morph=0,q=0, summed section dB over 40 Hz‒18 kHz):

| cascade | spread | floor |
|---|---|---|
| RAW all-pole ×6 (current bug) | **215.25 dB**, bottoms −270.3 dB @18 kHz | crater |
| pure peaking bells ×6 (Q 3, +8 dB) | **7.22 dB** | 0.02 dB — NO collapse |
| 5 bells + 1 low-body | **46.57 dB** | 0.01 dB |
| mixed low + bells + notches | **56.63 dB** | the −10 dB bin is the intended −24 dB notch, not a crater |

**Crater eliminated: 215 dB → 7‒47 dB.** (Scripts: `dev/tmp/flat_sections_verify.py`, `lowbody_fixed.py`, `allpole_g_underflow.py`, ran through `C:\Users\hooki\df2\target\release\trench_core.dll`.)

### UNVERIFIED — BUILD-TIME CHECKS (run before shipping flat sections)
- **Mid-morph flatness:** only the **four grid corners** were probed. Whether `lerp_u16` between a flat-bell Frame A and flat-bell Frame B stays flat at morph ∈ (0,1) is **NOT swept**. Test: sweep morph 0→1 at q=0 and q=1, assert interior cascade spread stays within the corner envelope (no crater appearing between corners).
- **Driven chain:** the full **AGC → Mackie → QSound** audition of these sections was **not run** (bare-cascade magnitude only). Test: render through `forge_engine_process` and judge by ear/plot.
- **lib.rs was not modified/rebuilt** for these forms — this is design + proof, not yet code.

---

## 3. The musical intent model

### Founding fact — LOG morph (OBSERVED, re-verified through the real codec)
Morph interpolates packed minifloat **CODES**, so the interior frequency trajectory is **logarithmic**. A pole 400→4000 Hz at r=0.99, packed then morph-lerped then decoded back:

```
morph 0.00 -> 400.0 Hz
morph 0.25 -> 718.1 Hz
morph 0.50 -> 1274.1 Hz   (geometric mean 1265; linear mean would be 2200)  <-- LOG curve
morph 0.75 -> 2195.5 Hz
morph 1.00 -> 4000.1 Hz
```

**Consequence:** ALL travel is specified in **octaves/semitones**, never Hz deltas — equal morph steps = equal octave steps. This is why the old `pf × 1.7` and `brighten` algebra (§1b) must go.

### Intent spec shape
A body = `{ foundation_hz, sections:[6 role-cards] }`. **Section index i is the morph pairing** (section i across all 4 corners) and is **SACRED** — a card owns one slot for life; the compiler iterates sections in fixed order inside the corner loop.

Each card:
```
{ role, type_id,                       # type_id selects §2 form (0 peak/1 low-body/2 notch)
  pole_A_hz, travel_oct,               # B = A * 2^travel_oct
  r_lo, r_hi,                          # Q axis: broad -> sharp
  gain_db (or gain),
  zero: { A_hz, travel_oct, depth } | null }
```

The 4 corners are the cross-product of the two authored axes:
- **morph** picks pole frequency A(0)→B(1), **log** placement.
- **Q** picks radius `r_lo(0)→r_hi(1)`, broad→sharp, **frequency unchanged**.

Corner order (canonical packed): `M0_Q0, M100_Q0, M0_Q100, M100_Q100` → `(morph,qsel)` = `(0,0),(1,0),(0,1),(1,1)`.

### Roles → axis behavior (the whole vocabulary)
- **ANCHOR** — held sub. `travel_oct = 0` (pole_B = pole_A): morph does NOT move it. Booms uncut = LOW-BODY or all-pole, **zero = null**. r near rim at BOTH Q levels (`r_lo 0.9985, r_hi 0.9995`) so it stays weight-bearing while upper sections sharpen. Highest gain. **E-mu's law verbatim:** high resonance up top without losing bass power down low.
- **MOVER** — travels a big interval (`travel_oct = 1.5‒3`). Because morph is log, it **glides at constant octaves/morph** (a vocal-formant sweep). Q sharpens in place. Usually all-pole, or a companion zero traveling WITH the pole (`zero.travel_oct = travel_oct`).
- **TEARER** — **CONTRARY MOTION.** Pole rises `+d` oct (`travel_oct = +d`); its zero/notch falls `−d` oct (`zero.travel_oct = −d`), so they **CROSS at the geometric midpoint at morph=0.5**. The crossing is the "tear": a peak climbing into a notch descending through it. Zero mandatory and deep (`depth ~0.95‒0.985`).
- **BLOOMER** — broad+quiet at A → near-rim high-Q scream at B. Rides the **Q axis** primarily: `r_lo` low (~0.80) → `r_hi` very high (~0.9992). Couple a small pole travel so morph re-tunes the scream. All-pole so nothing masks the rim peak. Peak height ~ `1/(1-r)`: r 0.80 → ~5×, r 0.999 → ~1000× (the bloom gap).

### Q sharpens without moving frequency (OBSERVED)
Pole = `r·e^(jθ)`. θ (center Hz) is set ONLY by `pole_hz` via `a1 = -2r·cos(2πf/SR)`. Going `r_lo→r_hi` raises r (Q ≈ 1/(2(1−r))) while θ is recomputed at the SAME f. Confirmed: every Q0/Q100 pair in the worked grid shares identical pole_hz.

### Honoring the law
Poles come from **fit/tables** (LPC capture, formant rails, physical models) — the card carries **measured** `pole_A_hz`, never invented. Zeros are first-class and **per-section** (anchor zero=null so the sub booms; tearer zero deep+contrary) — **never a uniform zero rule**. Clean-room: roles + octave travel are an original grammar; zero copied P2K coefficients/names/bytes.

### Exact intent → (6 sections × 4 corners) mapping
Per role, per corner `(morph ∈ {0,1}, qsel ∈ {0,1})`:
```
pole_hz = pole_A_hz * 2^(travel_oct * morph)            # log placement (proven trajectory)
r       = r_lo + (r_hi - r_lo) * qsel                   # broad->sharp, freq unchanged
if zero present:
    zero_hz    = zero_A_hz * 2^(zero_travel_oct * morph)  # tearer: zero_travel_oct = -travel_oct
    zero_depth = depth                                   # >0.0001 to engage zero branch
else: zero off (all-pole)
```
Helpers: `oct(f,n)=f*2^n`; semitones `2^(st/12)`; Q→r `clamp(exp(-pi*max(8,f/Q)/SR),0.5,MAX_RADIUS)`.

The `(pole_hz, r, gain, zero_hz, zero_depth, type_id)` then compiles to a biquad via the §2 form for `type_id` (or, for legacy all-pole roles, via `stage_biquad`), then to 5 words via `biquad_to_words`, packed per §4 layout.

Pseudocode:
```
cmap = [(0,0),(1,0),(0,1),(1,1)]            # packed corner order
for (morph,qsel) in cmap:
  for card in spec.sections[0..6]:           # fixed section index
    pf = oct(card.pole_A_hz, card.travel_oct*morph)
    r  = card.r_lo + (card.r_hi - card.r_lo)*qsel
    if card.zero: zf = oct(card.zero.A_hz, card.zero.travel_oct*morph); zd = card.zero.depth
    else: zf = 0; zd = 0
    bq = section_biquad(card.type_id, pf, r, card.gain_db, zf, zd)   # §2 forms
    emit biquad_to_words(bq)
```

### Worked "tear" body (foundation 55 Hz) — full numbers
Cards `(pole_A, travel_oct, r_lo, r_hi, gain, zero_A, zero_travel_oct, depth)`:
```
S0 anchor : 55,   0.00, 0.9985, 0.9995, 1.00, none                  (held sub, booms uncut)
S1 lowbody: 130, +0.20, 0.97,   0.992,  0.60, none                  (foundation companion)
S2 mover  : 520, +2.00, 0.94,   0.992,  0.50, none                  (formant 520->2080, +2 oct glide)
S3 tearer : 700, +1.00, 0.95,   0.9985, 0.45, zero 1400, -1.00, 0.97  (pole up 1 oct, zero down 1 oct, CROSS @ ~990)
S4 bloomer: 3000,+0.22, 0.80,   0.9992, 0.30, none                  (broad/quiet A -> near-rim scream B)
S5 aircap : 6000,+0.26, 0.85,   0.97,   0.22, zero 4500, +0.10, 0.60 (companion notch riding up)
```

Resulting 6×4 grid `pole_hz / r / zero_hz` (RAN through the codec — OBSERVED):
```
anchor   M0Q0 55.0/.9985/--    M100Q0 55.0/.9985/--    M0Q100 55.0/.9995/--    M100Q100 55.0/.9995/--
lowbody  M0Q0 130/.9700/--     M100Q0 150/.9700/--     M0Q100 130/.9920/--     M100Q100 150/.9920/--
mover    M0Q0 520/.9400/--     M100Q0 2080/.9400/--    M0Q100 520/.9920/--     M100Q100 2080/.9920/--
tearer   M0Q0 700/.9500/1400   M100Q0 1400/.9500/700   M0Q100 700/.9985/1400   M100Q100 1400/.9985/700
bloomer  M0Q0 3000/.8000/--    M100Q0 3500/.8000/--    M0Q100 3000/.9992/--    M100Q100 3500/.9992/--
aircap   M0Q0 6000/.8500/4500  M100Q0 7200/.8500/4800  M0Q100 6000/.9700/4500  M100Q100 7200/.9700/4800
```

**Contrary-motion crossing (OBSERVED):** tearer pole 700→1400, zero 1400→700, swept through packed interpolation:
```
morph 0.0 -> pole 700.0  / zero 1400.0
morph 0.5 -> pole 1002.4 / zero 994.2   (gmean(700,1400)=990)  <-- CROSS at log midpoint = the tear
morph 1.0 -> pole 1400.0 / zero 700.0
```

**Stability (OBSERVED):** all 4 corners of this body `max_pole_radius < 1.0` — M0_Q0/M100_Q0 = 0.99850, M0_Q100/M100_Q100 = 0.99950, all STABLE. **Q-axis purity:** every M_*_Q0 / M_*_Q100 pair shares identical pole_hz.

**UNVERIFIED — BUILD-TIME CHECK:** the dB magnitude plot and drive-chain render of this exact body were not produced; the trajectory + stability numbers ARE measured. Build it through the new compiler, plot, and confirm the tear reads on the response surface and passes the live score (§6).

---

## 4. The one-owner architecture

### Current state (OBSERVED in live source)
- Forward path duplicated: `forge-web-wasm/src/lib.rs:132-175` (Rust→WASM) **and** `tools/forge_author_server.py:33-50` (Python "exact mirror").
- `forge-web/js/packed.js` = **decode only** (plotting) — already correct.
- `forge-web-wasm` **already depends on** trench-core (`Cargo.toml:10`) and imports `trench_core::minifloat::encode` (`lib.rs:1`).
- trench-core already owns the inverse side: `minifloat::encode/decode/lerp_u16/kernel_to_biquad/stage_words_to_kernel`, `PackedCorners::interpolate*` (minifloat.rs), and the runtime.
- **The only thing trench-core does NOT own is the FORWARD direction.** That is the whole migration.

### DRIFT FOUND (OBSERVED — the smoking gun)
The two "identical mirrors" already disagree. WASM clamps `rp`/`cut_depth` to **MAX_RADIUS = 0.999999999999999** (`lib.rs:107,155,159`). Python clamps to **0.9999** (`forge_author_server.py:36-37`). Any radius in `(0.9999, 0.999999999999999]` packs to **different bytes** in WASM vs Python. The 0.014 dB parity tolerance is wide enough to **hide** this — it is a real semantic divergence, fixed by construction when one owner replaces both.

### (a) NEW module `trench-core/src/compiler.rs`
Register `pub mod compiler;` in `trench-core/src/lib.rs` after `pub mod cascade;`. Canonical constants live here ONCE:
```
AUTHORING_SR = 39062.5;  TAU = 2*PI;  MAX_RADIUS = 0.999999999999999;  // supersedes Python 0.9999
POLE_R_MIN = 0.5;  GAIN_MIN = 0.05;  GAIN_MAX = 4.0;
FREQ_MIN = 20.0;  FREQ_MAX = SR*0.49 (=19140.625);
ZERO_DEPTH_THRESH = 0.0001;  GAIN_FLOOR = 1e-4;  ZNORM_FLOOR = 1e-9;
```
Public fns:
1. `pub fn stage_biquad(p: &[f64;7]) -> [f64;5]` — byte-for-byte the body of `lib.rs:148-175` (all-pole vs pole+zero branch, clamps, DC-normalize gain). Param order **canonical**: `[on, pole_hz, pole_r, gain, zero_on, zero_hz, zero_depth]`. Document this order in a doc-comment as the single source of the contract.
2. `pub fn biquad_to_words(b: [f64;5]) -> [u16;5]` — body of `lib.rs:132-146` (c0..c4 recombination → `minifloat::encode`).
3. `pub fn section_biquad(type_id: i32, fc: f64, r: f64, gain_db: f64, zero_hz: f64, zero_depth: f64) -> [f64;5]` — the **flat-ended §2 forms** (0 peak / 1 low-body / 2 notch). (`stage_biquad` remains for legacy all-pole/raw param authoring and for byte-exact migration parity; `section_biquad` is the new musical-intent path. Both live in the one owner.)
4. `pub fn pack_corner(params: &[[f64;7];6]) -> [u16;30]` and `pub fn pack_body(params: &[[f64;7];24]) -> [u8;240]` — the 4×6 corner loop (`lib.rs:181-191`), LSB-first u16, corner order `M0_Q0,M100_Q0,M0_Q100,M100_Q100`. Owns the **layout** too.

> Keep `encode` as the single owner — `compiler::biquad_to_words` calls `crate::minifloat::encode`; do not reimplement.

### (b) FFI exports in `trench-core/src/ffi.rs`
Append after `trench_packed_probe` (it ends at **line 311** — OBSERVED):
```
pub unsafe extern "C" fn trench_compile_stage(params:*const f64, out_words:*mut u16) -> i32
    // reads 7 f64, writes 5 u16; rc 0 / -1 null
pub unsafe extern "C" fn trench_compile_body(params:*const f64, n_params:usize, out_body:*mut u8) -> i32
    // reads 168 f64 (24 stages x 7), writes 240 bytes; rc 0 / -1 null / -4 if n_params != 168
```
(Per-stage export mirrors how Python loops stage-by-stage so /score can read per-row words; body export is the one-shot /bake path.)

### (c) `pyruntime/trench_ffi.py` wrapper
In `_load()`, bind guarded by `try/except AttributeError` + a `_compile_ok` flag (exactly like `_agc_ok`/`_fit_ok`) so an **old DLL degrades loudly**:
```
lib.trench_compile_stage.argtypes = [POINTER(c_double), POINTER(c_uint16)]; .restype = c_int
lib.trench_compile_body.argtypes  = [POINTER(c_double), c_size_t, POINTER(c_uint8)]; .restype = c_int
def compile_stage(p7):  a=(c_double*7)(*map(float,p7)); o=(c_uint16*5)(); rc=lib.trench_compile_stage(a,o); assert rc==0; return list(o)
def compile_body(p168): a=(c_double*168)(*map(float,p168)); o=(c_uint8*240)(); rc=lib.trench_compile_body(a,c_size_t(168),o); assert rc==0; return bytes(o)
```
Raise `"stale build; cargo build --release -p trench-core"` if `not _compile_ok`.

### (d) `forge-web-wasm/src/lib.rs` — delete-and-delegate (no new dependency)
- Change import: `use trench_core::compiler::{stage_biquad, biquad_to_words};` (drop unused `encode`). Or import `pack_body`.
- **DELETE** local `fn stage_biquad` (148-175) and `fn biquad_to_words` (132-146).
- **DELETE** local consts `SR`(100), `TAU`(101), `MAX_RADIUS`(107) — use `trench_core::compiler::AUTHORING_SR` etc. **Keep** `STAGES/CORNERS/PARAMS_PER_STAGE/PARAM_LEN/BODY_LEN` (they describe WASM memory layout).
- `forge_pack_params` (177-195): keep its corner loop calling the trench-core fns, **or** (cleaner) call `trench_core::compiler::pack_body` over the PARAMS slice and memcpy into BODY.
- The WASM C-ABI surface (`forge_pack_params`, `forge_params_ptr`, `forge_body_ptr`, engine fns) is **UNCHANGED** → `studio.js` needs no edit.

### (e) Python server `forge_author_server.py`
DELETE local `stage_biquad`(33-43) and `biquad_to_words`(45-50). In `pack()`, build the flat 168-f64 vector from `corner_params()` (already yields `[on,pf,pr,gain,zon,zhz,zdepth]` per lane per corner) and call `t.compile_body(params168)`. Keep a `t.compile_stage` path only if `/score` needs per-row words.

### (f) `packed.js` stays plot-only — CONFIRMED (OBSERVED)
`packed.js` contains ONLY decode-side fns (`decodeWord, lerpU16, stageWordsToKernel, kernelToBiquad, wordsAt, biquadDbCoeffs, packedDb`) + byte/hex helpers. **No** `stage_biquad`, **no** `biquad_to_words`. It is not a forward compiler and **must not become one**. The browser's authoritative packing goes through WASM; `packed.js` is the policed decode mirror ("plot == engine to 0.0000 dB"). Do not add an encoder there.

**Net result:** forward compiler in exactly ONE place. WASM, Python /bake, and the DLL execute the identical Rust object code for params→bytes. `packed.js` stays a decode-only plot mirror, policed by the parity test.

---

## 5. Implementation order (avoid a half-migrated state)

**Owner first → consumers after. Never edit two consumers before the owner compiles green.** Run all cargo from **PowerShell** (gotcha #2 below).

**Step 0 — clear the deck.**
- KILL any running uvicorn / Python holding `trench_core.dll` memory-mapped (`forge_author_server.py`, audition tools). On Windows the DLL is locked while loaded; cargo link fails *file-locked* otherwise (gotcha #1).
- Ensure MSVC `link.exe` shadows git-bash's MinGW `link.exe` — run cargo from **PowerShell**, not git-bash, or put MSVC first on PATH (gotcha #2).

**Step 1 — trench-core owner (defines truth).**
- Add `compiler.rs` (§4a) + `pub mod compiler;` + the two `ffi.rs` exports (§4b).
- `cargo build --release -p trench-core` → `target/release/trench_core.dll`.
- Add `trench-core/tests/compiler_parity.rs` (§6 Test 1) and `cargo test -p trench-core compiler_parity`. **The golden 240-byte fixture is frozen here — this is the source of truth before any consumer migrates.**

**Step 2 — Python (same DLL, no rebuild → fastest feedback).**
- Edit `trench_ffi.py` bindings (§4c) + `forge_author_server.py` (delete locals, call `compile_body`).
- Run Test 2 against the just-built DLL.

**Step 3 — WASM (separate target + manual copy = riskiest, validated last).**
- Edit `lib.rs` (delete locals, import compiler) (§4d).
- `cargo build --release --target wasm32-unknown-unknown`
- **COPY** `target/wasm32-unknown-unknown/release/forge_web_wasm.wasm` → `forge-web/wasm/forge_web_wasm.wasm` (manual; `FORGE_STUDIO_HANDOFF.md:82-84`; easy to forget — Test 3 catches a missed copy).
- Run Test 3.

**Step 4 — intent layer + cleanup.**
- Add `section_biquad` (§2 flat forms) to `compiler.rs` if not yet in Step 1; wire the studio/intent author to emit `(role, type_id, octave travel, contrary zero)` cards → 168-f64 vector → `compile_body`.
- Run Test 4 (decode/plot mirror) + Test 5 (retire old 0.014 dB gate). Restart the server.

**Rationale:** trench-core first (truth) → Python second (shares the exact DLL, no rebuild) → WASM last (separate build + manual copy is the silent-drift hole). The `_compile_ok` guard makes a stale DLL raise loudly instead of falling back.

---

## 6. Parity & acceptance tests

**THRESHOLD CHANGE:** all three now execute the same Rust object code → target **BIT-IDENTICAL** bytes (Hamming distance 0 over 240). **Retire the 0.014 dB tolerance** — it was a crutch for two diverging implementations. dB is now only a secondary sanity check (expect exactly 0.0000 dB).

The golden vectors MUST cover: all-pole branch; pole+zero branch; the `cut_depth ≤ 0.0001` boundary; **radius in `(0.9999, MAX_RADIUS]`** (locks the drift fix); `gain` at GAIN_MIN/MAX clamps; `freq` at FREQ_MAX clamp; `on=0` passthrough; and a near-MAX_RADIUS all-pole stage (freezes the encoder's underflow-edge behavior). For the flat sections: at least one PEAK, one LOW-BODY, one NOTCH at the §2 verified params.

**Test 1 — Rust unit (`trench-core/tests/compiler_parity.rs`).**
Command: `cargo test -p trench-core compiler_parity`
Expected: N ≥ 20 param vectors → `pack_body` bytes **==** committed golden 240-byte fixture. PASS freezes canonical bytes.

**Test 2 — Python↔Rust FFI parity** (`dev/tmp/compile_parity.py`).
Command: `python dev/tmp/compile_parity.py` (against freshly restarted server's DLL)
Expected: for the SAME N vectors, `trench_ffi.compile_body(p) == golden fixture` byte-for-byte. Proves the DLL the server loads == canonical bytes.

**Test 3 — WASM↔golden parity** (node harness loading the shipped `.wasm`).
Command: `node dev/tmp/wasm_parity.mjs`
Expected: write N vectors into PARAMS via `forge_params_ptr`, call `forge_pack_params`, read 240 from `forge_body_ptr`, **==** golden fixture byte-for-byte. Catches a stale `.wasm` that wasn't recopied (must load the file in `forge-web/wasm/`, not the freshly built one).

**Test 4 — decode/plot mirror (the ONE dB test; polices packed.js).**
Command: `python dev/tmp/plot_mirror.py` (decode each body via `trench_packed_interpolate` at the 4 corners AND via packed.js `wordsAt/stageWordsToKernel`, magnitude over a log freq grid).
Expected: `max |dB_rust − dB_js| == 0.0000` ("plot == engine" invariant). Keep packed.js `Math.fround` mirror or this reports false deltas (the f32 lerp).

**Test 5 — retire the old gate.**
Repoint `dev/tmp/emu_tensioning/parity_test.py` at the golden fixture with a **0-byte** threshold, or delete it once Tests 1‒3 are green. No stale 0.014 dB gate may remain to mask future drift.

**Acceptance — no-crater body.**
Command: build a 6-section body (1 LOW-BODY anchor + 5 PEAK bells), `packed_probe` at the 4 corners, sum section dB over 40 Hz‒18 kHz.
Expected: cascade spread **≤ ~50 dB**, floor **≥ −1 dB** (no −270 dB crater). (RAW all-pole would show 215 dB — that is the regression guard.)

**Acceptance — "tear" body passes live score.**
Command: compile the §3 worked tear body through the new compiler; POST to `/score` (and audition through the drive chain).
Expected: all 4 corners `max_pole_radius < 1.0` (STABLE — already OBSERVED for the trajectory); contrary-motion pole/zero cross at morph≈0.5 (pole≈1002, zero≈994 — OBSERVED); **live score gates pass** (UNVERIFIED — BUILD-TIME CHECK: run `/score` and confirm).

---

## 7. Risks / open questions

### Minifloat traps
- **Underflow edge (the real hazard):** `biquad_to_words` encodes `c4/4 = b0/4`; `encode(v ≤ 2^-15)` → `0x0000` (denormal floor). For an all-pole stage near MAX_RADIUS, `b0 = max(1-r²,1e-4)*gain` can land in denormal range and a small per-section gain can push `c4/4` to 0 → **dead stage mid-morph**. Mitigation: keep `b0/4 ≳ 2e-3` before encode; distribute peak loudness with the `gain^(1/6)` trick (forge-web/CLAUDE.md), not one tiny-gain screamer; bloomers keep gain high enough that the rim peak survives. The golden vectors MUST include a near-MAX_RADIUS all-pole stage so the edge behavior is frozen (one owner → wrong identically everywhere, visible in golden bytes, not a per-impl surprise). **Note:** for the §2 flat forms this is NOT a problem — they keep b0 ≈ O(0.3‒1.0) (verified) and round-trip < 0.01 dB.
- **encode() denormal/normal seam asymmetry** (minifloat.rs:50-79) rounds differently near the 0xFFF/0x1000 boundary. Already one owner (can't drift between consumers) — golden fixture must exercise small c-coeffs near the seam so any future `encode` edit is caught as a byte change.
- **Contrary-motion denominator blowup:** pole+zero `g = (1+a1+a2)/(1+nb1+nb2)`. Zero approaching DC or `(1+nb1+nb2)→0` → g explodes → word saturates `0xFFFF`. Keep tearer zeros away from DC/Nyquist; `depth < ~0.99`. Crossing itself is safe; verify a zero landing exactly on the pole freq doesn't null the whole section.
- **lerp_u16 WRAPS, not clamps** (minifloat.rs:88-94): large word jumps A→B can overflow the i16 delta and wrap → garbage interior pole mid-morph even with clean endpoints. Bound travel in octaves; split big jumps across sections. **Always sweep morph 0..1 and watch the interior, not just the 4 corners.**
- **NOTCH depth saturation:** `depth_db` very negative drives `rz→1`; clamped at 0.99999, so depths beyond ~−50 dB become uncontrollable.
- **High-r quantization:** `c2=a1+2`, `c3=1-a2` must stay in `[0,1]` for the `(c2-c3)/4` and `c3` words; r→1.0 pushes `a1→−2 (c2→0)`, `a2→1 (c3→0)` and the encoder clamps to 0x0000, quantizing the pole away. Verified OK to r=0.9999; r→1.0 loses the pole.

### UNVERIFIED (must run a build-time check)
- **Whole §4 unification is design + plan — nothing here was compiled/run.** It rests on OBSERVED source facts (dependency, single-owner forward path, packed.js decode-only, the 0.9999-vs-MAX_RADIUS drift) but the migration itself and all of §6 are UNVERIFIED until executed.
- **Mid-morph flatness** of flat-bell A→B (§2) — only grid corners probed.
- **Driven-chain audition** (AGC→Mackie→QSound) of the flat sections and the tear body (§2, §3) — bare magnitude only.
- **Tear body live-score pass** (§6) — trajectory + stability OBSERVED; the score gate itself not run.

### Contracts the byte-parity tests CANNOT protect (flag to owner)
- **Param-order handshake** `[on,pole_hz,pole_r,gain,zero_on,zero_hz,zero_depth]` is still an implicit contract between `studio.js` (writes raw f64 by index), the WASM PARAMS layout, and Python `corner_params()`. Moving math to Rust does NOT make JS type-safe. If `studio.js` reorders, all three read garbage **identically** (consistent but wrong) — parity tests feed the same vectors to all three and cannot catch it. Mitigation: doc-comment the order on `compiler::stage_biquad` as canonical; optional `SectionParams` struct (deferred).
- **Corner order** `M0_Q0,M100_Q0,M0_Q100,M100_Q100` appears in `lib.rs` loop, `packed.js` keys, `forge_author_server` keys, `trench_ffi`. `pack_body` owns it for the forward path; a reorder in a decode consumer vs the compiler mis-pairs corners — caught by Test 4 (rust-decode vs js-decode magnitude compare) as a nonzero dB delta.
- **f32 vs f64 in interpolation** (decode-side, unchanged): `trench_packed_interpolate` casts morph/q to f32; `lerp_u16` uses f32; `packed.js` uses `Math.fround`. Do NOT "simplify" the fround or Test 4 reports false deltas.

### Needs owner's ear / taste
- Does the tear read musically on the response surface and through the drive chain? Does the bloomer's r 0.80→0.9992 scream without thinning the anchor sub (E-mu's law)? Frame-pairing keep/kill — AI never approves a finished body; the ear confirms last.
- Section type mix per role (PEAK vs NOTCH for tearer resolution) and travel intervals are taste calls within the verified-safe envelope.
