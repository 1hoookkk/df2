use std::path::PathBuf;
use trench_workstation::proof::run_recipe_proof;

fn main() {
    if let Err(error) = run() {
        eprintln!("recipe proof failed: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let repo_root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repository root")
        .to_path_buf();
    let output = repo_root.join("out").join("recipe-proof-r003-l6");
    let receipt = run_recipe_proof(&repo_root, &output, "four-pose", "R003:L6")?;
    println!("VERDICT {}", receipt.report.verdict);
    println!("PROOF_BUNDLE {}", receipt.directory);
    println!("MANIFEST_SHA256 {}", receipt.manifest_sha256);
    println!(
        "REUSED_IDENTICAL_BUNDLE {}",
        receipt.reused_identical_bundle
    );
    println!(
        "INDEX accepted={} rejected={} sha256={}",
        receipt.report.index_validation.accepted_lane_count,
        receipt.report.index_validation.rejected_lane_count,
        receipt.report.index_validation.index_sha256,
    );
    println!(
        "SELECTED {} scaffold={} lane={}",
        receipt.report.application.candidate.candidate_id,
        receipt.report.application.scaffold_name,
        receipt.report.application.candidate.scaffold_lane_index + 1,
    );
    println!(
        "CHANGED_WORDS {}",
        serde_json::to_string(&receipt.report.application.changed_words)?
    );
    println!(
        "SAMPLED_AUDIT {}x{} max_pole_radius={:.9} unstable_rows={} nonfinite_rows={}",
        receipt
            .report
            .application
            .sampled_audit_after
            .morph_points,
        receipt.report.application.sampled_audit_after.q_points,
        receipt
            .report
            .application
            .sampled_audit_after
            .maximum_pole_radius,
        receipt
            .report
            .application
            .sampled_audit_after
            .unstable_mask
            .iter()
            .filter(|failed| **failed)
            .count(),
        receipt
            .report
            .application
            .sampled_audit_after
            .nonfinite_mask
            .iter()
            .filter(|failed| **failed)
            .count(),
    );
    Ok(())
}
