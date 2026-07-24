import sys, numpy as np
from pathlib import Path
sys.path.insert(0,"C:/Users/hooki/df2"); sys.path.insert(0,"C:/Users/hooki/df2/pyruntime")
from pyruntime import trench_ffi
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

f=np.logspace(np.log10(30),np.log10(19200),512)
SR=39062.5
w=2*np.pi*f/SR; z1=np.exp(-1j*w); z2=z1*z1
def db(path,m,q):
    bb=Path(path).read_bytes(); pr=trench_ffi.packed_probe(bb,m,q)
    mag=np.ones_like(f)
    for (b0,b1,b2,a1,a2) in pr["biquad"]:
        mag*=np.abs(b0+b1*z1+b2*z2)/np.maximum(np.abs(1+a1*z1+a2*z2),1e-12)
    return 20*np.log10(np.maximum(mag,1e-9))

BEF="dev/tmp/bytes_survivors/shipv2_hedz_bottle_mouth.body240"
AFT="dev/q0fix_20260722/hedz_q0lift.body240"

fig,ax=plt.subplots(2,1,figsize=(9,7),dpi=110,sharex=True)
fig.patch.set_facecolor("#0e1512")
for a in ax: a.set_facecolor("#0e1512")

for i,(m,ttl) in enumerate([(0,"M0_Q0  (default load state)"),(1,"M100_Q0")]):
    b=db(BEF,m,0); a=db(AFT,m,0)
    ax[i].semilogx(f,b,color="#7a8a82",lw=1.6,ls="--",label=f"BEFORE  crown {b.max():.0f} dB")
    ax[i].semilogx(f,a,color="#e0555f",lw=2.2,label=f"AFTER   crown {a.max():.0f} dB")
    ax[i].axhline(27,color="#e0b23e",lw=0.8,ls=":",alpha=0.6)  # +27 ceiling
    ax[i].text(33,28,"+27 ceiling",color="#e0b23e",fontsize=8,alpha=0.8)
    ax[i].set_ylim(-45,50); ax[i].set_xlim(30,19200)
    ax[i].set_title(ttl,color="#cfe8de",fontsize=12,loc="left")
    ax[i].grid(True,which="both",color="#1c2722",lw=0.5)
    ax[i].tick_params(colors="#7a8a82")
    ax[i].legend(facecolor="#12201b",edgecolor="#1c2722",labelcolor="#cfe8de",fontsize=10,loc="upper right")
    ax[i].set_ylabel("dB",color="#7a8a82")
ax[1].set_xlabel("Hz (log)",color="#7a8a82")
fig.suptitle("Hedz Bottle Mouth  -  Q0 corners lifted (Q100 untouched)",color="#cfe8de",fontsize=13)
fig.tight_layout()
fig.savefig("dev/q0fix_20260722/q0_before_after.png",facecolor="#0e1512")
print("wrote q0_before_after.png")
