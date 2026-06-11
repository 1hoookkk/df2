from pathlib import Path
from PIL import Image

FR=Path('_preview/blender/frames')
ASSET=Path('../../assets/ui')
FRAMES=129
NFW,NFH=406,86                 # = morph well, fills it 1:1
BAND_ASPECT=NFW/NFH            # 4.72

# probe source size
s0=Image.open(FR/'f000.png'); SW,SH=s0.size      # 520x192
bh=int(SW/BAND_ASPECT)                            # band height in source px
y0=(SH-bh)//2                                     # centred band (the toothed crest + glow)

strip=Image.new('RGBA',(NFW*FRAMES,NFH),(0,0,0,0))
for i in range(FRAMES):
    im=Image.open(FR/f'f{i:03d}.png').convert('RGBA')
    band=im.crop((0,y0,SW,y0+bh)).resize((NFW,NFH),Image.LANCZOS)   # no bloom, no squish
    strip.alpha_composite(band,(i*NFW,0))

ASSET.mkdir(parents=True,exist_ok=True)
name=f'native_strip_129_{NFW}x{NFH}.png'
# clear any older strips
for old in ASSET.glob('native_strip_129_*.png'):
    if old.name!=name: old.unlink()
strip.save(ASSET/name)
idx=[0,25,55,85,110,128]
cells=[strip.crop((i*NFW,0,i*NFW+NFW,NFH)) for i in idx]
sheet=Image.new('RGBA',(NFW,NFH*len(cells)+8*(len(cells)-1)),(120,112,96,255))
y=0
for c in cells: sheet.alpha_composite(c,(0,y)); y+=NFH+8
sheet.convert('RGB').save('_preview/blender/strip_band_contact.png')
print('wrote',ASSET/name,strip.size,'band y',y0,bh)
