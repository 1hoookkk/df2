//! 69/69 heritage XMLs byte-equal through the Rust designer port.
//! Fixtures were generated fresh from the XMLs through the direct firmware
//! word path (scratchpad gen_heritage_fixtures.py, 2026-07-25).
use std::fs;
use std::path::PathBuf;
use trench_core::designer::{body_bytes, heritage_shift, DesignerRow, DesignerSection};

fn tag_text(xml: &str, tag: &str) -> Option<String> {
    let open = format!("<{tag}");
    let start = xml.find(&open)?;
    let body_start = xml[start..].find('>')? + start + 1;
    let end = xml[body_start..].find(&format!("</{tag}>"))? + body_start;
    Some(xml[body_start..end].trim().to_string())
}

fn section_block<'a>(xml: &'a str, index: usize) -> Option<&'a str> {
    let open = format!("<designer-section index=\"{index}\"");
    let start = xml.find(&open)?;
    let end = xml[start..].find("</designer-section>")? + start;
    Some(&xml[start..end])
}

#[test]
fn heritage_xml_parity_69_of_69() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/heritage");
    let mut checked = 0;
    for entry in fs::read_dir(root.join("xml")).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().and_then(|e| e.to_str()) != Some("xml") {
            continue;
        }
        let xml = fs::read_to_string(&path).unwrap();
        let frequency: f64 = tag_text(&xml, "frequency").unwrap().parse().unwrap();
        let gain: f64 = tag_text(&xml, "gain").unwrap().parse().unwrap();
        let shift = heritage_shift(frequency, gain);
        let sections: Vec<DesignerSection> = (1..=6)
            .map(|i| {
                let Some(block) = section_block(&xml, i) else {
                    return DesignerSection::default();
                };
                let field = |tag: &str| -> i32 {
                    tag_text(block, tag).map_or(0, |t| t.parse().unwrap())
                };
                DesignerSection {
                    type_id: field("type"),
                    low: DesignerRow {
                        freq: field("low-freq"),
                        gain: field("low-gain"),
                        ..Default::default()
                    },
                    high: DesignerRow {
                        freq: field("high-freq"),
                        gain: field("high-gain"),
                        ..Default::default()
                    },
                }
            })
            .collect();
        let body = body_bytes(&sections, &sections, shift)
            .unwrap_or_else(|e| panic!("{}: {e}", path.display()));
        let fixture = root
            .join("fixtures")
            .join(format!("{}.body240", path.file_stem().unwrap().to_str().unwrap()));
        let expected = fs::read(&fixture).unwrap();
        assert_eq!(
            body.as_slice(),
            expected.as_slice(),
            "byte mismatch: {}",
            path.display()
        );
        checked += 1;
    }
    assert_eq!(checked, 69, "expected 69 heritage XMLs");
}
