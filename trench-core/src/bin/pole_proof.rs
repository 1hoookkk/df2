//! Proof that E-MU dynamic pole-radius distortion (US 10,514,883) behaves
//! differently from the interstage saturator.
//!
//! Renders the SAME decaying sine through the SAME body at high Q, three ways:
//!   clean / interstage saturator / pole-radius
//! and dumps CSV so the difference can be plotted.

use trench_core::cartridge::Cartridge;
use trench_core::engine::FilterEngine;

const SR: f64 = 39_062.5;
thread_local!(static MORPH: std::cell::RefCell<f64> = std::cell::RefCell::new(0.62));

fn source(n: usize) -> Vec<f32> {
    // A decaying tone: level sweeps DOWN through the threshold, so the pole
    // distortion should engage hard at the start and release as it decays.
    // That level-dependence is the whole point - a saturator cannot do it.
    let mut out = vec![0.0f32; n];
    let mut ph = 0.0f64;
    for (i, v) in out.iter_mut().enumerate() {
        let t = i as f64 / SR;
        ph += 2.0 * std::f64::consts::PI * 110.0 / SR;
        *v = (ph.sin() * (-t / 0.55).exp() * 0.9) as f32;
    }
    out
}

fn render(body: &[u8], mode: &str, amount: f32, n: usize) -> Vec<f32> {
    let mut eng = FilterEngine::new();
    eng.prepare(SR);
    match mode {
        "pole" => eng.set_pole_distortion(amount),
        "inter" => eng.set_interstage_drive(amount),
        _ => {}
    }
    let cart = Cartridge::from_body_bytes_at("proof", body, 1.0, SR).expect("cartridge");
    eng.load_cartridge(cart);
    let src = source(n);
    let mut l = src.clone();
    let mut r = src;
    let block = 128;
    let mut done = 0usize;
    while done < n {
        let take = block.min(n - done);
        let (le, re) = (&mut l[done..done + take], &mut r[done..done + take]);
        // high Q: the regime where the poles actually misbehave
        eng.process_block(le, re, MORPH.with(|m| *m.borrow()), 1.0);
        done += take;
    }
    l
}

fn main() {
    let path = std::env::args()
        .nth(1)
        .expect("usage: pole_proof <body240>");
    let body = std::fs::read(&path).expect("read body");
    let n = (SR * 1.2) as usize;

    let clean = render(&body, "none", 0.0, n);
    let inter = render(&body, "inter", 0.22, n);
    // sweep to find where the pole path actually starts biting
    let pk = |v: &Vec<f32>| v.iter().fold(0.0f32, |m, x| m.max(x.abs()));
    let rms =
        |v: &Vec<f32>| (v.iter().map(|x| (x * x) as f64).sum::<f64>() / v.len() as f64).sqrt();
    println!("amount   peak     rms      vs-clean-rms");
    for a in [0.0f32, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0] {
        let o = render(&body, "pole", a, n);
        println!(
            "{:5.2}   {:.4}   {:.5}   {:+.2}%",
            a,
            pk(&o),
            rms(&o),
            (rms(&o) / rms(&clean) - 1.0) * 100.0
        );
    }
    // Does CHEW engagement vary with MORPH position? If so, modulating morph
    // already makes the chew breathe and no new control is needed.
    println!();
    println!("morph   clean-rms   chew-rms   delta");
    for m in [0.10f64, 0.30, 0.50, 0.70, 0.90] {
        MORPH.with(|c| *c.borrow_mut() = m);
        let c0 = render(&body, "none", 0.0, n);
        let c1 = render(&body, "pole", 0.22, n);
        println!(
            "{:5.2}   {:.5}     {:.5}    {:+.1}%",
            m,
            rms(&c0),
            rms(&c1),
            (rms(&c1) / rms(&c0) - 1.0) * 100.0
        );
    }
    MORPH.with(|c| *c.borrow_mut() = 0.62);
    let pole = render(&body, "pole", 1.0, n);

    let mut csv = String::from("i,clean,inter,pole\n");
    for i in 0..n {
        csv.push_str(&format!("{},{},{},{}\n", i, clean[i], inter[i], pole[i]));
    }
    std::fs::write("pole_proof.csv", csv).expect("write csv");
    let pk = |v: &Vec<f32>| v.iter().fold(0.0f32, |m, x| m.max(x.abs()));
    println!(
        "peaks  clean {:.4}  interstage {:.4}  pole {:.4}",
        pk(&clean),
        pk(&inter),
        pk(&pole)
    );
    println!("wrote pole_proof.csv ({} samples)", n);
}
