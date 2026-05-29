"""voxbench — the TRENCH body-authoring bench (the synthesized filter-type
vocabulary + the listen-loop laws as code). ONE owner of build/render/measure;
nobody re-implements the packed math (decode/interp go through trench_ffi, the
FFI owner). Promoted from dev/tmp/voxlab/harness.py 2026-05-29.

THE VOCABULARY (E-mu filter types, each emits packed u16 stages):
  lowpass/lp4/lp6 · highpass/hp4 · bandpass · contrary_bp · swept_eq ·
  spectral_tilt · phaser_notch · formant (peaking-EQ).
A corner = exactly 6 stages (list of 5-tuples). A body = 4 KIN corners
(M0_Q0, M100_Q0, M0_Q100, M100_Q100).

THE LAWS (verified this session, enforced by verify_body):
  * DRIVE THE AGC or the engine is asleep/clinical/weak (audition drive~3-4).
  * Q drives the escalation: Q0 = casual, Q100 = shout (peaks rise with Q).
  * REGISTRATION: each voice keeps its slot -> the MIDDLE glides (intermediate),
    not jumps. The middle is the product.
  * KIN corners: shared skeleton so the middle is coherent.
  * ZEROS carve the valleys (bp / contrary / phaser); peaking-EQ does not.
  * Validate with the simple magnitude curve + measured peaks/lowmid/hi/slope.
  * The EAR picks; the machine only culls broken (stability / sane peaks).
"""
import struct, os, math, wave
from pathlib import Path
import numpy as np
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.corner_words import peak_eq_words, bp, lp, edge, notch, pas
from pyruntime.encode import raw_to_encoded, EncodedCoeffs
from pyruntime.packed_interp import coeffs_to_words
from pyruntime.freq_response import freq_points, cascade_response_db
from pyruntime import trench_ffi

AUTH_SR = 39062.5
LABELS = ["M0_Q0", "M100_Q0", "M0_Q100", "M100_Q100"]
BUTTER_6POLE_Q = (0.51764, 0.70711, 1.93185)
BUTTER_4POLE_Q = (0.54120, 1.30656)
MAX_EQ_DB = 24.0   # E-mu Swept-EQ caps at 24 dB boost/cut

# ---- filter-type primitives (each returns ONE stage = 5 words) -------------
def _sp(sp):
    ec = raw_to_encoded(sp); return coeffs_to_words(ec.c0, ec.c1, ec.c2, ec.c3, ec.c4)

def formant(freq, bw, gain_db):
    """Parametric peaking-EQ formant: flat 0 dB baseline + a bump (NO zeros)."""
    return peak_eq_words(freq, bw, gain_db)

def lowpass(fc, q=0.70711):
    w0 = 2*math.pi*fc/AUTH_SR; al = math.sin(w0)/(2*q); cw = math.cos(w0)
    b0=(1-cw)/2; b1=1-cw; b2=(1-cw)/2; a0=1+al; a1=-2*cw; a2=1-al
    b0/=a0; b1/=a0; b2/=a0; a1/=a0; a2/=a0
    return coeffs_to_words(b1/b0+2.0, 1.0-b2/b0, a1+2.0, 1.0-a2, b0)

def highpass(fc, q=0.70711):
    w0 = 2*math.pi*fc/AUTH_SR; al = math.sin(w0)/(2*q); cw = math.cos(w0)
    b0=(1+cw)/2; b1=-(1+cw); b2=(1+cw)/2; a0=1+al; a1=-2*cw; a2=1-al
    b0/=a0; b1/=a0; b2/=a0; a1/=a0; a2/=a0
    return coeffs_to_words(b1/b0+2.0, 1.0-b2/b0, a1+2.0, 1.0-a2, b0)

def lp6(fc):  return [lowpass(fc, q) for q in BUTTER_6POLE_Q]   # 36 dB/oct
def lp4(fc):  return [lowpass(fc, q) for q in BUTTER_4POLE_Q]   # 24 dB/oct
def hp4(fc):  return [highpass(fc, q) for q in BUTTER_4POLE_Q]
def bandpass(freq, radius=0.95): return _sp(bp(freq, radius))   # pole + paired zero
def passthrough(): return _sp(pas())

def octave_to_q(octaves):
    n = 2.0 ** octaves
    return math.sqrt(n) / (n - 1.0)

def swept_eq(center, gain_db, oct_low=1.0, oct_high=1.0, flo=200.0, fhi=4000.0):
    """Swept-EQ band: bw interpolates oct_low (at flo) -> oct_high (at fhi)."""
    t = (math.log2(max(center, flo)) - math.log2(flo)) / (math.log2(fhi) - math.log2(flo))
    t = max(0.0, min(1.0, t))
    octaves = oct_low + (oct_high - oct_low) * t
    return peak_eq_words(center, center/octave_to_q(octaves),
                         max(-MAX_EQ_DB, min(MAX_EQ_DB, gain_db)))

def contrary_bp(peak_f, dip_f, peak_db=18.0, dip_db=18.0, peak_oct=1.0, dip_oct=1.0):
    """Contrary Bandpass: a PEAK and a DIP together (2 stages). Move peak_f/dip_f
    in OPPOSITE directions across the morph for the contrary crossing."""
    return [peak_eq_words(peak_f, peak_f/octave_to_q(peak_oct),  min(MAX_EQ_DB, peak_db)),
            peak_eq_words(dip_f,  dip_f/octave_to_q(dip_oct),   -min(MAX_EQ_DB, dip_db))]

def spectral_tilt(N, alpha, fmin=150.0, fmax=8000.0, K=2, pivot_hz=1100.0, fs=None):
    """Fractional-slope |H|~f^alpha (J.O.Smith). Pole array + interleaved zeros;
    the morph = sliding the zeros (alpha). dB/oct ~ alpha*6.02. Pivot-normalized."""
    fs = fs or AUTH_SR
    T = 1.0/fs; nyq = 0.49*fs
    lnr = (math.log(fmax)-math.log(fmin))/(N - 2*K - 1)
    r = math.exp(lnr); f1 = math.exp(math.log(fmin) - K*lnr)
    def warp(f):
        f = min(max(f, 1.0), nyq); t = math.tan(math.pi*f*T); return (1.0-t)/(1.0+t)
    pd = [warp(f1*r**n) for n in range(N)]
    zd = [warp(f1*r**n * r**(-alpha)) for n in range(N)]
    coeffs = []
    for i in range(0, N, 2):
        pa, pb = pd[i], (pd[i+1] if i+1 < N else 0.0)
        za, zb = zd[i], (zd[i+1] if i+1 < N else 0.0)
        a1=-(pa+pb); a2=pa*pb; b0=1.0; b1=-(za+zb); b2=za*zb
        num=b0+b1+b2; den=1.0+a1+a2; g=(den/num) if abs(num)>1e-12 else 1.0
        coeffs.append([b0*g, b1*g, b2*g, a1, a2])
    wp = 2*math.pi*pivot_hz/fs; z=complex(math.cos(-wp), math.sin(-wp)); z2=z*z
    H = 1.0+0j
    for b0,b1,b2,a1,a2 in coeffs:
        H *= (b0 + b1*z + b2*z2)/(1.0 + a1*z + a2*z2)
    s = 1.0/abs(H) if abs(H) > 1e-12 else 1.0
    coeffs[0][0]*=s; coeffs[0][1]*=s; coeffs[0][2]*=s
    out = [coeffs_to_words(b1/b0+2.0, 1.0-b2/b0, a1+2.0, 1.0-a2, b0)
           for b0,b1,b2,a1,a2 in coeffs]
    while len(out) < 6: out.append(passthrough())
    return out[:6]

def phaser_notch(freq, depth_db=18.0, radius=0.97):
    zr = max(0.0, 1.0 - 10.0 ** (-min(MAX_EQ_DB, depth_db) / 20.0))
    return _sp(notch(freq, radius, -0.05, freq, zr))

# ---- build / measure / render ---------------------------------------------
def build_body(corners: dict) -> bytes:
    raw = bytearray()
    for lab in LABELS:
        st = corners[lab]
        if len(st) != 6:
            raise ValueError(f"{lab}: a corner is 6 stages, got {len(st)}")
        for w in st:
            raw += struct.pack("<5H", *[int(x) & 0xFFFF for x in w])
    assert len(raw) == 240
    return bytes(raw)

def pink_noise(secs, seed=7):
    n = int(secs*AUTH_SR); rng = np.random.default_rng(seed)
    X = np.fft.rfft(rng.standard_normal(n)); f = np.arange(len(X)); f[0] = 1
    x = np.fft.irfft(X / np.sqrt(f), n).astype(np.float64)
    x *= 0.25/np.max(np.abs(x))
    return x.astype("<f4").tobytes()

def _db(body, m, q, freqs):
    return cascade_response_db([EncodedCoeffs(*c) for c in trench_ffi.packed_interpolate(body, m, q)], freqs)

def measure(body):
    freqs = freq_points(512); lm=(freqs>=100)&(freqs<=400); hi=(freqs>=8000)&(freqs<=16000)
    rows = {}
    for nm,(m,q) in {"home Q0":(0,0),"away Q0":(1,0),"MID Q0":(0.5,0),
                     "MID Q100":(0.5,1),"home Q100":(0,1),"away Q100":(1,1)}.items():
        d=_db(body,m,q,freqs); rows[nm]=(round(float(d.max()),1), round(float(d[lm].mean()),1), round(float(d[hi].mean()),1))
    return rows

def _dominant_hz(body, m, q):
    freqs = freq_points(1024); d = _db(body, m, q, freqs)
    return float(freqs[int(np.argmax(d))])

def verify_body(body, drive=3.0, source=None):
    """The synthesized guardrails as objective metrics. The machine culls broken;
    the ear still chooses. Returns a dict the verifier interprets."""
    freqs = freq_points(1024)
    peaks = {lab: float(np.max(_db(body, 0.0 if "M0" in lab else 1.0, 0.0 if "Q0" in lab else 1.0, freqs)))
             for lab in LABELS}
    finite = all(np.all(np.isfinite(_db(body, m, q, freqs)))
                 for m,q in [(0,0),(1,0),(0,1),(1,1),(0.5,0.5)])
    max_peak = max(peaks.values())
    stable = finite and max_peak < 45.0
    # Q escalation: Q100 peaks should rise vs Q0
    q_esc = float(np.mean([np.max(_db(body,m,1.0,freqs)) for m in (0,1)])
                  - np.mean([np.max(_db(body,m,0.0,freqs)) for m in (0,1)]))
    # registration / middle emergence: dominant peak at M50 sits BETWEEN home & away
    h,a,mid = _dominant_hz(body,0,0), _dominant_hz(body,1,0), _dominant_hz(body,0.5,0)
    lo,hi2 = min(h,a), max(h,a)
    middle_emerges = (lo*0.85 <= mid <= hi2*1.15) and (abs(mid-h) > 0.04*h or abs(mid-a) > 0.04*a) \
                     if abs(h-a) > 0.05*h else True   # if home==away (e.g. tilt), middle is fine
    # zeros present? minimum dB IN-BAND (200-5000 Hz, excl. LP rolloff floor) = carved valleys
    inb = (freqs >= 200) & (freqs <= 5000)
    min_db = float(min(np.min(_db(body,m,q,freqs)[inb]) for m,q in [(0,0),(1,0),(0.5,0)]))
    has_zeros = min_db < -12.0
    # AGC drive evidence: crest factor falls when driven (compression engaging)
    src = source if source is not None else pink_noise(2.0)
    nb = max(1,(len(src)//4)//512); lin=list(np.linspace(0,1,nb))
    def crest(d):
        s = (np.frombuffer(src,dtype="<f4")*float(d)).astype("<f4").tobytes()
        a = np.frombuffer(trench_ffi.engine_render_automated(body, [0.5]*nb, lin, s), dtype="<f4")
        rms = np.sqrt(np.mean(a**2)); return float(np.max(np.abs(a))/(rms+1e-9)), float(rms)
    crest_dry,_ = crest(1.0); crest_drv, rms_drv = crest(drive)
    drives_agc = (crest_drv < crest_dry - 0.15) and rms_drv > 1e-4
    return {
        "stable": bool(stable), "max_peak_db": round(max_peak,1), "finite": bool(finite),
        "q_escalation_db": round(q_esc,1), "middle_emerges": bool(middle_emerges),
        "dominant_hz_home_mid_away": [round(h), round(mid), round(a)],
        "has_zeros": bool(has_zeros), "min_db": round(min_db,1),
        "drives_agc": bool(drives_agc), "crest_dry": round(crest_dry,2), "crest_driven": round(crest_drv,2),
        "corner_peaks_db": {k: round(v,1) for k,v in peaks.items()},
    }

def curve_png(body, name, outdir):
    freqs = freq_points(512)
    plt.style.use("dark_background"); fig,ax=plt.subplots(figsize=(11,6)); ax.set_facecolor("#050505")
    ax.semilogx(freqs,_db(body,0,0,freqs),  color="#9aef5a",lw=1.4,label="home (M0 Q0)")
    ax.semilogx(freqs,_db(body,0.5,0,freqs),color="#e5dccb",lw=2.4,label="MIDDLE (M50 Q0)")
    ax.semilogx(freqs,_db(body,1,0,freqs),  color="#5ad1ef",lw=1.4,label="away (M100 Q0)")
    ax.semilogx(freqs,_db(body,0.5,1,freqs),color="#ff5a5a",lw=1.6,ls="--",label="MIDDLE (M50 Q100)")
    ax.axvspan(100,400,color="#ffa838",alpha=0.06)
    ax.set_xlim(80,19000); ax.set_ylim(-60,40); ax.grid(True,which="both",color="#1a2030",lw=0.4)
    ax.axhline(0,color="#444",lw=0.6)
    ax.set_title(name,color="#9aa096"); ax.legend(fontsize=8)
    ax.set_xlabel("Hz",color="#5a605c"); ax.set_ylabel("dB",color="#5a605c")
    fig.tight_layout(); p=f"{outdir}/{name}_curve.png"; fig.savefig(p,dpi=120,facecolor="#0a0a0c"); plt.close(fig)
    return p

def _wav(path, audio):
    x=np.clip(np.frombuffer(audio,dtype="<f4"),-1,1)
    with wave.open(path,"w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(AUTH_SR))
        w.writeframes((x*32767).astype("<i2").tobytes())

# ---- real-material sources (FX insert: judged on program material) ---------
def reese(secs=3.0, f0=82.4, seed=3):
    """Reese bass: detuned saw stack (harmonically rich, sustained)."""
    n=int(secs*AUTH_SR); t=np.arange(n)/AUTH_SR; rng=np.random.default_rng(seed); x=np.zeros(n)
    for k in range(7):
        det=1.0+(k-3)*0.007; ph=rng.random()*6.283
        for h in range(1,30): x += np.sin(2*np.pi*f0*det*h*t+ph)/h
    x *= 0.2/np.max(np.abs(x)); return x.astype("<f4").tobytes()

def eight08(secs=3.0, f0=50.0):
    """808: sine sub + pitch-drop click transient + decay."""
    n=int(secs*AUTH_SR); t=np.arange(n)/AUTH_SR
    pitch=f0*(1+3*np.exp(-t*40)); ph=2*np.pi*np.cumsum(pitch)/AUTH_SR
    x=(np.sin(ph)+0.3*np.sin(2*ph))*np.exp(-t*1.2) + 0.5*np.exp(-t*200)*np.sign(np.sin(ph))
    x *= 0.5/np.max(np.abs(x)); return x.astype("<f4").tobytes()

def pad(secs=3.0, root=110.0, seed=5):
    """Pad: sustained detuned-saw minor triad (mid-rich, soft)."""
    n=int(secs*AUTH_SR); t=np.arange(n)/AUTH_SR; rng=np.random.default_rng(seed); x=np.zeros(n)
    for mult in (1.0, 1.1892, 1.4983):           # root, min3, 5th
        for d in (0.994,1.0,1.006):
            ph=rng.random()*6.283
            for h in range(1,24): x += np.sin(2*np.pi*root*mult*d*h*t+ph)/h
    env=np.minimum(1.0, t/0.2); x*=env
    x *= 0.18/np.max(np.abs(x)); return x.astype("<f4").tobytes()

SOURCES = {"reese": reese, "808": eight08, "pad": pad}

def _norm_bytes(audio, peak=0.9):
    x=np.frombuffer(audio,dtype="<f4").astype(np.float64); m=np.max(np.abs(x))
    return ((x*(peak/m)) if m>1e-9 else x).astype("<f4").tobytes()

# THE GAIN-STAGING LADDER (the workflow's spine): clean=resonance, slam=density.
DRIVE_LADDER = [("clean", 0, 0.0), ("slam", 1, 0.5), ("slammed", 1, 0.85), ("crush", 2, 0.0)]

def render_fx(body, src, mode_id, slam_drive, morph_per_block, q_per_block):
    """Render body on `src` through a pre-filter input character.
    mode_id: 0=None(clean,max resonance) 1=MackieDeskSlam(saturation density) 2=CVSD(bit-crush)."""
    if mode_id == 1:
        return trench_ffi.engine_render_slam(body, morph_per_block, q_per_block, src, slam_drive=slam_drive)
    return trench_ffi.engine_render_automated(body, morph_per_block, q_per_block, src, input_mode=mode_id)

def audition_fx(body, name, outdir, source_name="reese", source=None,
                ladder=None, morph_sweep=True):
    """Audition a body up the DRIVE LADDER on real material (clean->slam->slammed->
    crush). A premium FX body has RANGE: pronounced clean resonance AND thick slam
    density. Writes one WAV per rung; output peak-normalized (clean-output rule)."""
    os.makedirs(outdir, exist_ok=True)
    src = source if source is not None else SOURCES.get(source_name, reese)()
    nb = max(1,(len(src)//4)//512)
    mp = list(np.linspace(0,1,nb)) if morph_sweep else [0.5]*nb
    qp = [0.5]*nb
    paths = {}
    for label, mode_id, sd in (ladder or DRIVE_LADDER):
        a = render_fx(body, src, mode_id, sd, mp, qp)
        p = f"{outdir}/{name}_{source_name}_{label}.wav"; _wav(p, _norm_bytes(a)); paths[label] = p
    return paths

def audition(body, name, outdir, source=None, drive=4.0, normalize=True):
    """Render set on pink noise. drive>1 engages the AGC; output peak-normalized."""
    os.makedirs(outdir, exist_ok=True)
    Path(f"{outdir}/{name}.body240").write_bytes(body)
    src = source if source is not None else pink_noise(3.0)
    if drive != 1.0:
        src = (np.frombuffer(src,dtype="<f4")*float(drive)).astype("<f4").tobytes()
    nb = max(1,(len(src)//4)//512); lin=list(np.linspace(0,1,nb))
    def render(m,q):
        a = trench_ffi.engine_render_automated(body, m, q, src)
        if normalize:
            x=np.frombuffer(a,dtype="<f4").astype(np.float64); mx=np.max(np.abs(x))
            if mx>1e-9: a=(x*(0.9/mx)).astype("<f4").tobytes()
        return a
    _wav(f"{outdir}/{name}_glide_casualQ.wav",  render(lin, [0.0]*nb))
    _wav(f"{outdir}/{name}_escalation_midM.wav", render([0.5]*nb, lin))
    _wav(f"{outdir}/{name}_diagonal.wav",        render(lin, lin))
    return measure(body), curve_png(body, name, outdir)
