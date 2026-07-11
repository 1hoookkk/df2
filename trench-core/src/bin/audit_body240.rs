use serde::Serialize;
use std::collections::HashSet;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use trench_core::response::{audit_body240, BodyCascadeAudit};

#[derive(Serialize)]
struct AuditRecord {
    path: String,
    source_set: String,
    audit: BodyCascadeAudit,
}

#[derive(Serialize)]
struct AuditReport {
    contract: String,
    repo: String,
    records: Vec<AuditRecord>,
}

fn main() {
    let mut repo = PathBuf::from(".");
    let mut out = PathBuf::from("dev/tmp/body240_cascade_gate");
    let mut inputs: Vec<PathBuf> = Vec::new();
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--repo" => repo = PathBuf::from(args.next().expect("--repo needs a path")),
            "--out" => out = PathBuf::from(args.next().expect("--out needs a path")),
            "--input" => inputs.push(PathBuf::from(args.next().expect("--input needs a path"))),
            other => inputs.push(PathBuf::from(other)),
        }
    }

    let repo = fs::canonicalize(&repo).unwrap_or(repo);
    if inputs.is_empty() {
        inputs = default_roots(&repo);
    } else {
        inputs = inputs
            .into_iter()
            .map(|p| if p.is_absolute() { p } else { repo.join(p) })
            .collect();
    }

    let mut files = Vec::new();
    let mut seen = HashSet::new();
    for input in inputs {
        collect_body_files(&input, &mut files, &mut seen);
    }
    files.sort();

    let mut records = Vec::new();
    for file in files {
        let Ok(bytes) = fs::read(&file) else {
            continue;
        };
        let rel = rel_path(&repo, &file);
        match audit_body240(&bytes) {
            Ok(audit) => records.push(AuditRecord {
                source_set: source_set(&rel),
                path: rel,
                audit,
            }),
            Err(err) => eprintln!("skip {}: {err}", file.display()),
        }
    }

    records.sort_by(|a, b| {
        b.audit
            .gate
            .pass
            .cmp(&a.audit.gate.pass)
            .then_with(|| {
                a.audit
                    .ranking
                    .crown_parity_db
                    .partial_cmp(&b.audit.ranking.crown_parity_db)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                b.audit
                    .ranking
                    .usable_headroom_db
                    .partial_cmp(&a.audit.ranking.usable_headroom_db)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
            .then_with(|| {
                b.audit
                    .ranking
                    .stability_margin
                    .partial_cmp(&a.audit.ranking.stability_margin)
                    .unwrap_or(std::cmp::Ordering::Equal)
            })
    });

    fs::create_dir_all(&out).expect("create output dir");
    let report = AuditReport {
        contract: "trench-core-owned body240 cascade audit report v1".to_owned(),
        repo: repo.display().to_string(),
        records,
    };
    let json_path = out.join("cascade_audit.json");
    fs::write(&json_path, serde_json::to_vec_pretty(&report).unwrap()).expect("write json");
    let csv_path = out.join("cascade_audit.csv");
    fs::write(&csv_path, csv_report(&report)).expect("write csv");
    println!("OBSERVED: audited {} .body240 files", report.records.len());
    println!("OBSERVED: wrote {}", json_path.display());
    println!("OBSERVED: wrote {}", csv_path.display());
}

fn default_roots(repo: &Path) -> Vec<PathBuf> {
    [
        "presets",
        "bodies",
        "juce-shell/assets/bodies",
        "desk/bank/v1/staging",
        "desk/sheets",
        "dev/tmp/law_author",
        "dev/tmp/forge_gpu_painter",
        "dev/tmp/gpt_pro_presets_20260612/plots",
        "forge-web/v1_candidates",
    ]
    .into_iter()
    .map(|p| repo.join(p))
    .collect()
}

fn collect_body_files(path: &Path, out: &mut Vec<PathBuf>, seen: &mut HashSet<PathBuf>) {
    if !path.exists() {
        return;
    }
    if path.is_file() {
        if is_body240(path) {
            let p = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
            if seen.insert(p.clone()) {
                out.push(p);
            }
        }
        return;
    }
    let Ok(entries) = fs::read_dir(path) else {
        return;
    };
    for entry in entries.flatten() {
        collect_body_files(&entry.path(), out, seen);
    }
}

fn is_body240(path: &Path) -> bool {
    path.extension()
        .and_then(|s| s.to_str())
        .map(|s| s.eq_ignore_ascii_case("body240") || s.eq_ignore_ascii_case("bin"))
        .unwrap_or(false)
}

fn rel_path(repo: &Path, file: &Path) -> String {
    file.strip_prefix(repo)
        .unwrap_or(file)
        .to_string_lossy()
        .replace('\\', "/")
}

fn source_set(path: &str) -> String {
    if path.contains("dev/tmp/law_author") {
        "law_author".to_owned()
    } else if path.contains("juce-shell/assets/bodies") || path.starts_with("presets/") || path.starts_with("bodies/") {
        "factory_manifest".to_owned()
    } else if path.contains("dev/tmp/forge_gpu_painter") || path.contains("desk/bank/v1/staging") {
        "forge_audition_or_staging".to_owned()
    } else if path.contains("dev/tmp/gpt_pro_presets_20260612") {
        "gpt_candidate_set".to_owned()
    } else {
        "candidate".to_owned()
    }
}

fn csv_report(report: &AuditReport) -> String {
    let mut s = String::from("rank,path,source_set,pass,failures,crown_min_db,crown_max_db,crown_parity_db,headroom_db,morph_contrast_db,q_bloom_db,peak_valley_clarity,stability_margin,max_pole_radius,worst_floor_db,worst_span_db,warnings\n");
    for (idx, r) in report.records.iter().enumerate() {
        let max_r = r
            .audit
            .samples
            .iter()
            .map(|s| s.max_pole_radius)
            .fold(0.0, f64::max);
        let floor = r
            .audit
            .samples
            .iter()
            .map(|s| s.floor_db)
            .fold(f64::INFINITY, f64::min);
        let span = r
            .audit
            .samples
            .iter()
            .map(|s| s.span_db)
            .fold(0.0, f64::max);
        s.push_str(&format!(
            "{},{},{},{},{},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.3},{:.6},{:.6},{:.3},{:.3},{}\n",
            idx + 1,
            csv(&r.path),
            csv(&r.source_set),
            r.audit.gate.pass,
            csv(&r.audit.gate.failures.join("; ")),
            r.audit.gate.measured_crown_min_db,
            r.audit.gate.measured_crown_max_db,
            r.audit.ranking.crown_parity_db,
            r.audit.ranking.usable_headroom_db,
            r.audit.ranking.morph_contrast_db,
            r.audit.ranking.q_bloom_db,
            r.audit.ranking.peak_valley_clarity,
            r.audit.ranking.stability_margin,
            max_r,
            floor,
            span,
            r.audit.warnings.len()
        ));
    }
    s
}

fn csv(v: &str) -> String {
    if v.contains(',') || v.contains('"') || v.contains('\n') {
        format!("\"{}\"", v.replace('"', "\"\""))
    } else {
        v.to_owned()
    }
}
