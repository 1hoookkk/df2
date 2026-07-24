import sys, wave, numpy as np
from pathlib import Path
DF2 = Path("C:/Users/hooki/df2")
for p in (str(DF2), str(DF2/"pyruntime")):
    if p not in sys.path: sys.path.insert(0, p)
from pyruntime import trench_ffi
SR=44100; BLOCK=64
def pink(n, seed=1):
    r=np.random.RandomState(seed); w=r.randn(n); b=np.zeros(7); out=np.zeros(n)
    for i in range(n):
        x=w[i]
        b[0]=0.99886*b[0]+x*0.0555179; b[1]=0.99332*b[1]+x*0.0750759
        b[2]=0.96900*b[2]+x*0.1538520; b[3]=0.86650*b[3]+x*0.3104856
        b[4]=0.55000*b[4]+x*0.5329522; b[5]=-0.7616*b[5]-x*0.0168980
        out[i]=b[0]+b[1]+b[2]+b[3]+b[4]+b[5]+b[6]+x*0.5362; b[6]=x*0.115926
    return (out/np.max(np.abs(out))*0.5).astype(np.float32)
def render(path, m_blocks, q_blocks, src):
    bb=Path(path).read_bytes()
    raw=trench_ffi.engine_render_automated(bb, m_blocks.tolist(), q_blocks.tolist(), src.tobytes(), SR, block=BLOCK)
    wet=np.frombuffer(raw,dtype=np.float32).astype(np.float64)
    return wet
def rms(x): return float(np.sqrt(np.mean(x*x)))
def wav(path,x):
    x=np.clip(x/max(rms(x),1e-9)*0.14,-0.99,0.99)  # RMS level-match
    pcm=(x*32767).astype("<i2")
    with wave.open(path,"wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())
assert trench_ffi.engine_available(), "engine unavailable"
n_blocks=int(SR*3.0/BLOCK)
src=pink(n_blocks*BLOCK)
# Q0 state: sweep morph 0->1 at Q=0 (the boring default axis)
m=np.linspace(0,1,n_blocks); q=np.zeros(n_blocks)
before="dev/q0fix_20260722/../../dev/tmp/bytes_survivors/shipv2_hedz_bottle_mouth.body240"
wav("dev/q0fix_20260722/hedz_q0_BEFORE.wav", render("dev/tmp/bytes_survivors/shipv2_hedz_bottle_mouth.body240", m, q, src))
wav("dev/q0fix_20260722/hedz_q0_AFTER.wav",  render("dev/q0fix_20260722/hedz_q0lift.body240", m, q, src))
print("wrote hedz_q0_BEFORE.wav / hedz_q0_AFTER.wav (morph sweep at Q0, RMS-matched)")
