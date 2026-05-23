# P2K Calibration Diary — What Makes a Good Filter

Learned from systematic analysis of 11 P2K reference bodies (33 P2K skins,
11 with full calibration breakdowns). This is the forge's design knowledge.

## Four Design Archetypes

### 1. Cooperative Formant Morphing (Fuzzi Face, Ooh-to-Eee)
- Stages aligned, minimal fighting (cancellation -0.7 to -19.8 dB = reinforcement)
- Smooth vowel transitions across entire morph/Q space
- Low c4 values (0.01–0.17), high radii (0.99+)
- Ooh-to-Eee: only 3 stages, 7.6 dB cancellation at worst
- Fuzzi Face: ALL corners cooperate, c4 range 0.0025–0.3342
- **When to use**: clean vocal morphs, transparent vowel synthesis

### 2. Aggressive Spectral Coloration (Meaty Gizmo, Talking Hedz)
- Extreme Anchor peaks (78–81 dB individual) cancelled by 40–62 dB
- High stage count (6), diverse c4 (0.02–0.98)
- Talking Hedz: stable c4 across corners (0.51–0.56), cancellation 31–45 dB
- Meaty Gizmo: M0_Q0 anchor at 59 Hz, radius 0.999, peak +83.1 dB → cascade +24.4
- **When to use**: bold character, presence, identity-defining bodies

### 3. Selective Fighters (BassBox 303, Radio Craze, Freak Shifta)
- Fight in some corners, cooperate in others
- Radio Craze: M0_Q0 cooperates (-22.5 dB), rest fight
- BassBox 303: M100_Q100 cooperates (-19.0 dB), M100_Q0 fights (+52 dB)
- c4 varies by corner position — response adapts to morph/Q
- **When to use**: bodies that transform between transparent and colored

### 4. Anchor-Dominant (Ear Bender, Razor Blades)
- Strong Anchor stage (radius 0.98–0.99, c4 0.15–0.77)
- Consistent 20–38 dB cancellation at all corners
- Ear Bender M100_Q0: anchor at 45 Hz, radius 0.997, peak +78.1 dB
- **When to use**: bass-centric filtering with formant coloration above

## Universal Rules (observed across all 11 bodies)

### DC Floor
All bodies maintain +12 to +13 dB at 50 Hz in cascade output.
This is the universal gain-staging strategy with boost=4.0.

### c4 Per Corner
c4 is tuned per-corner to maintain consistent loudness floor.
Higher Q corners typically use lower c4 to compensate for natural boost.
- Talking Hedz: c4 very stable (0.51–0.56) — shared numerator structure
- Ooh-to-Eee: c4 tracks Q (0.0146 at Q0, 0.0437 at Q50, 0.1671 at Q100)
- Fuzzi Face: c4 extremely low across all corners (0.0025–0.3342)

### Radius Ranges by Role
| Role | Typical radius | Minimum observed | Maximum observed |
|------|---------------|-----------------|-----------------|
| Anchor | 0.945–0.999 | 0.945 (Radio Craze) | 0.999 (Talking Hedz) |
| LowMid | 0.857–0.998 | 0.857 (Ear Bender) | 0.998 (Millennium) |
| FormantBite | 0.857–0.999 | 0.354 (Meaty Gizmo anomaly) | 0.999 (Talking Hedz) |
| Air | 0.760–0.998 | 0.484 (Ear Bender anomaly) | 0.998 (Early Rizer) |
| HF/Nyquist | 0.250–0.998 | 0.250 (Radio Craze) | 0.998+ |

### Pole Frequency Shifts Across Morph
Some stages radically change role across morph:
- BassBox 303 S0: 79 Hz (Anchor) → 5093 Hz (Air) — 64x shift, complete identity change
- Early Rizer S4: 6177 Hz (HF) → 2475 Hz (FormantBite) — spectral rebalancing
Others stay anchored:
- Talking Hedz S5: 199 Hz → 157 Hz — stable anchor, slight tightening
- Talking Hedz S0: 9321 Hz → 10158 Hz — stable HF boundary

### Cancellation Budget
| Category | Cancellation range | Bodies |
|----------|-------------------|--------|
| Heavy fighters (>35 dB) | 35–62 dB | Meaty Gizmo, Ear Bender, Talking Hedz |
| Moderate fighters (15–35 dB) | 15–35 dB | Razor Blades, Early Rizer, Millennium |
| Mixed (varies by corner) | -22 to +52 dB | BassBox 303, Radio Craze, Freak Shifta |
| Full cooperators (<0 dB) | -20 to -0.7 dB | Fuzzi Face, Ooh-to-Eee |

## Corner Response Patterns

### M0_Q0 (resting state)
- Typical dip at 1–3 kHz (formant notch)
- Peak at 200–500 Hz (presence)
- HF collapse (-50 to -80 dB at 19 kHz)

### M0_Q100 (Q-boosted, low morph)
- Midrange emphasis shifts higher (500–1000 Hz boost)
- Smoother HF falloff
- Some bodies show +20 to +40 dB peaks at 1–2 kHz

### M100_Q0 (morphed, low Q)
- Most variable corner — bodies diverge most here
- Some peak at 3–5 kHz (formant shift)
- Cancellation often extreme (maximum spectral work)

### M100_Q100 (fully engaged)
- Most aggressive spectral shaping
- +30 to +50 dB at 500–2000 Hz common
- Nyquist region highly sensitive (-30 to +30 dB swings)

## What Makes the Best Bodies

1. **Story**: talkingness varies across morph/Q — body opens, peaks, transforms
2. **Counterpoint**: stages fight OR cooperate deliberately, not randomly
3. **Cancellation budget**: 30–45 dB cancellation = aggressive character; <5 dB = transparent
4. **Stable DC floor**: +12 dB at 50 Hz regardless of morph/Q position
5. **Role diversity**: Anchor + LowMid + FormantBite minimum; Air and HF as needed
6. **c4 discipline**: shared or slowly varying c4 across corners for consistent loudness
7. **Radical morph shifts**: at least one stage changes role across morph for identity transformation

## What Makes Bad Bodies

1. **No cancellation and no cooperation**: stages placed independently, no interaction
2. **All stages at similar frequencies**: no spectral spread, no role differentiation
3. **Flat talkingness**: same vocal character everywhere — no story
4. **c4 = 1.0 everywhere**: no gain shaping, raw resonance — blowup risk
5. **No anchor**: missing sub-bass spectral mass — thin, weightless
6. **All peaks, no notches**: commodity EQ shape, not filter character
7. **Identity preserved everywhere**: preservation > 80% across all transitions — boring
