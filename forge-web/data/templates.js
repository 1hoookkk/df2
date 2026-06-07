/* df2 forge — template palette.
   Clean-room mathematical starter shapes. Each item fills the editor's six
   editable lanes (pole Hz, radius, level, zero/cut Hz, cut depth) so the user
   can drag, tune, and save normally — templates are seeds, never read-only.

   Sources (clean-room math only, no vendor bytes / names / coefficient tables):
   - tools/target_templates.json          feature freq/gain/bw ranges
   - tables/family_intents.json           physical frequency rails
   - recipes/laws/family_*.json           section laws (fc, gain, zero offsets)
   - recipes/.../cleanroom_three_layer_acoustic_recipe.json  pole/zero/radius recipe
   - docs/FORGE_FAMILY_LAW_CONTEXT.md      rails + move families

   Stage schema matches the editor exactly:
     { on, hz, r, gainDb, cutOn, cutHz, cutDepth, label }
   where r = pole radius (0.5..0.9999), cutDepth = zero radius (0..0.9999).
   Corner order for `corners`: C0=M0/Q0, C1=M100/Q0, C2=M0/Q100, C3=M100/Q100. */

const st=(on,hz,r,gainDb,cutOn,cutHz,cutDepth,label)=>({on,hz,r,gainDb,cutOn,cutHz,cutDepth,label});
const peak=(hz,r,gainDb,label)=>st(true,hz,r,gainDb,false,hz*0.75,0,label);
const cut =(hz,r,gainDb,cutHz,cutDepth,label)=>st(true,hz,r,gainDb,true,cutHz,cutDepth,label);

// --- three-layer acoustic body: foundation poles + articulation zeros, with a
//     real Q axis (radius lift q0->q100) and a real Morph axis (pole/zero move).
//     Numbers from cleanroom_three_layer_acoustic_recipe.json. ----------------
function threeLayerCorners(){
  const SHIFT=o=>Math.pow(2,o);
  // hz, morphOct, rq0, rq100, zHome, zAway, zrq0, zrq100, gainDb, label
  const lanes=[
    [   92,  0.08, 0.946, 0.985, 2.15, 2.75, 0.66, 0.82,  2, "chest floor"],
    [  330,  0.10, 0.962, 0.991, 1.70, 0.78, 0.88, 0.97,  3, "throat wall"],
    [  920,  0.12, 0.974, 0.996, 1.18, 0.64, 0.91, 0.985, 4, "mouth dome"],
    [ 1850, -0.10, 0.970, 0.997, 0.72, 1.58, 0.90, 0.988, 2, "bite ridge"],
    [ 3950,  0.14, 0.966, 0.9982,1.42, 0.92, 0.94, 0.995, 0, "tear rail"],
    [ 7900, -0.06, 0.952, 0.9985,0.86, 1.26, 0.91, 0.996,-2, "air rail"],
  ];
  const capR=r=>Math.min(0.997,r);   // keep packed-grid worst radius < edge
  const capZ=z=>Math.min(0.992,z);
  const corner=(q100,morph)=>lanes.map(L=>{
    const [hz,mOct,rq0,rq100,zHome,zAway,zrq0,zrq100,g,lab]=L;
    const phz=morph?hz*SHIFT(mOct):hz;
    const ratio=morph?zAway:zHome;
    return cut(phz, capR(q100?rq100:rq0), g, phz*ratio, capZ(q100?zrq100:zrq0), lab);
  });
  // C0=M0/Q0  C1=M100/Q0  C2=M0/Q100  C3=M100/Q100
  return [corner(0,0), corner(0,1), corner(1,0), corner(1,1)];
}

// --- contrary bandpass: two windows crossing in opposition across Morph, with
//     Q lifting radius. Proves Forge expresses families beyond one-shape+Q. ---
function contraryCorners(){
  const lift=(s,d)=>({...s,r:Math.min(0.997,s.r+d)});
  // C0 (M0/Q0): peak A low, peak B high; cut A high, cut B low
  const c0=[
    cut (180,0.82,-6,180,0.90,"low wall"),
    peak(500,0.97, 6,"peak A"),
    peak(3000,0.97,6,"peak B"),
    cut (1500,0.85,-3,2800,0.90,"cut A"),
    cut (1500,0.85,-3, 700,0.90,"cut B"),
    cut (10000,0.93,-3,16500,0.60,"air"),
  ];
  // C1 (M100/Q0): peak A has risen, peak B has fallen; cuts crossed the other way
  const c1=[
    cut (180,0.82,-6,180,0.90,"low wall"),
    peak(2400,0.97,6,"peak A"),
    peak(700,0.97, 6,"peak B"),
    cut (1500,0.85,-3, 700,0.90,"cut A"),
    cut (1500,0.85,-3,2800,0.90,"cut B"),
    cut (10000,0.93,-3,16500,0.60,"air"),
  ];
  // Q100 = same geometry, overall radius lifted
  return [c0, c1, c0.map(s=>lift(s,0.015)), c1.map(s=>lift(s,0.015))];
}

const threeLayer=threeLayerCorners();
const contrary=contraryCorners();

export const FORGE_TEMPLATES=[
  {
    id:"vowel_formant", label:"vowel formant", family:"vocal",
    source:"family_vocal_formant law + vocal intent rails",
    stages:[
      peak(223,0.965, 5,"low body"),
      peak(730,0.972, 4,"F1"),
      cut (1090,0.978,5, 700,0.90,"F2"),
      peak(2440,0.975,2,"F3"),
      cut (8720,0.955,-4,8200,0.60,"air"),
      cut (8184,0.950,-6, 640,0.90,"remote cut"),
    ],
  },
  {
    id:"bottle_cavity", label:"bottle cavity", family:"cavity",
    source:"bottle_cavity feature ranges + cavity intent (Helmholtz/pipe)",
    stages:[
      peak(119,0.960, 6,"fundamental"),
      peak(357,0.970, 4,"2nd mode"),
      cut (1100,0.800,-3,1100,0.90,"scoop"),
      peak(1608,0.965,3,"upper mode"),
      cut (6000,0.930,-3,9000,0.60,"air"),
      cut (2600,0.900,-2, 420,0.85,"counter cut"),
    ],
  },
  {
    id:"broken_comb", label:"broken comb", family:"comb_fracture",
    source:"broken_comb feature ranges + comb intent teeth",
    stages:[
      peak(500,0.970, 6,"peak low"),
      peak(2000,0.970,5,"peak high"),
      cut (700,0.860,-2, 700,0.92,"tooth 1"),
      cut (1500,0.860,-2,1500,0.92,"tooth 2"),
      cut (3200,0.860,-2,3200,0.90,"tooth 3"),
      cut (7000,0.860,-2,7000,0.88,"tooth 4"),
    ],
  },
  {
    id:"small_metal_shell", label:"small metal shell", family:"metallic",
    source:"small_metal_shell feature ranges + resonant intent modes",
    stages:[
      peak(320,0.985, 6,"mode 1"),
      peak(1200,0.990,7,"mode 2"),
      peak(3500,0.990,6,"mode 3"),
      peak(7000,0.988,4,"mode 4"),
      cut (2500,0.820,-2,2500,0.85,"scoop"),
      peak(5200,0.987,3,"mode 5"),
    ],
  },
  {
    id:"razor_cut", label:"razor cut", family:"shell_fracture",
    source:"razor_shell feature ranges + cut intent tears",
    stages:[
      peak(220,0.955, 6,"low body"),
      peak(850,0.960, 5,"mid body"),
      cut (3500,0.850,-2,3500,0.92,"scoop"),
      cut (5500,0.990, 4,6300,0.93,"edge lo"),
      cut (9000,0.988, 3,10350,0.90,"edge hi"),
      cut (12000,0.950,-3,16500,0.60,"air"),
    ],
  },
  {
    id:"speaker_knock", label:"speaker knock", family:"bass",
    source:"speaker_knocker feature ranges + knock intent (sub left unity)",
    stages:[
      peak(90,0.950, 3,"weight"),
      peak(240,0.965, 6,"knock"),
      peak(700,0.960, 4,"body"),
      cut (2000,0.970, 4,2000,0.60,"grit"),
      cut (3000,0.850,-3,3000,0.90,"scoop"),
      cut (6000,0.985, 3,6900,0.90,"edge"),
    ],
  },
  {
    id:"bandpass_window", label:"bandpass window", family:"bandpass_swept_eq",
    source:"family_bandpass_swept_eq law (paired peaks + outside cuts)",
    stages:[
      cut (200,0.800,-6, 200,0.90,"low wall"),
      peak(700,0.970, 6,"window lo"),
      peak(2600,0.970,6,"window hi"),
      peak(1300,0.950,3,"center"),
      cut (9000,0.860,-6,9000,0.92,"high wall"),
      cut (4130,0.900,-5,9650,0.85,"remote cut"),
    ],
  },
  {
    id:"contrary_bandpass", label:"contrary bandpass", family:"bandpass_swept_eq",
    source:"family_bandpass_swept_eq law, two windows in opposition across C0-C3",
    stages:contrary[0],
    corners:contrary,
  },
  {
    id:"phaser_comb", label:"phaser comb", family:"phaser_comb",
    source:"family_phaser_comb law (cut field + sparse peaks)",
    stages:[
      peak(318,0.965, 6,"low"),
      cut (700,0.860,-5, 700,0.90,"cut lo"),
      peak(1624,0.970,3,"peak"),
      cut (4363,0.860,-6,4363,0.90,"cut hi"),
      peak(10268,0.950,1,"peak air"),
      cut (10074,0.900,-8,16500,0.85,"air kill"),
    ],
  },
  {
    id:"slope_ladder", label:"slope ladder", family:"slope_ladder",
    source:"family_slope_ladder law (descending keep/kill staircase)",
    stages:[
      peak(339,0.960, 6,"low"),
      peak(639,0.930, 2,"step 1"),
      cut (1511,0.880,-2,1511,0.60,"step 2"),
      cut (3945,0.860,-5,3945,0.80,"step 3"),
      cut (10286,0.850,-8,10286,0.85,"step 4"),
      cut (16500,0.800,-7,16500,0.60,"top cap"),
    ],
  },
  {
    id:"three_layer_acoustic", label:"three layer acoustic", family:"acoustic_three_layer",
    source:"cleanroom_three_layer_acoustic_recipe (foundation poles + articulation zeros)",
    stages:threeLayer[0],
    corners:threeLayer,
  },
];
