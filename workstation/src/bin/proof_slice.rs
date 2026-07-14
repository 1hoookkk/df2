use std::path::PathBuf;
use trench_workstation::proof::{run_proof_slice, PROOF_DIRECTORY};

fn main() {
    if let Err(error) = run() {
        eprintln!("proof slice failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repository root")
        .to_path_buf();
    let output = repo_root.join("out").join(PROOF_DIRECTORY);
    let receipt = run_proof_slice(&repo_root, &output)?;
    println!("VERDICT {}", receipt.report.verdict);
    println!("PROOF_BUNDLE {}", receipt.directory);
    println!("MANIFEST_SHA256 {}", receipt.manifest_sha256);
    println!(
        "REUSED_IDENTICAL_BUNDLE {}",
        receipt.reused_identical_bundle
    );
    println!(
        "CHANGED_WORDS {}",
        serde_json::to_string(&receipt.report.changed_words)?
    );
    println!(
        "SAMPLED_AUDIT {}x{} max_pole_radius={:.9} unstable_rows={} nonfinite_rows={}",
        receipt.report.sampled_audit.morph_points,
        receipt.report.sampled_audit.q_points,
        receipt.report.sampled_audit.maximum_pole_radius,
        receipt
            .report
            .sampled_audit
            .unstable_mask
            .iter()
            .filter(|failed| **failed)
            .count(),
        receipt
            .report
            .sampled_audit
            .nonfinite_mask
            .iter()
            .filter(|failed| **failed)
            .count(),
    );
    Ok(())
}
