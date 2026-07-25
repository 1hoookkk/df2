use crate::hash::sha256_hex;
use crate::model::{EvidenceReference, StageSourceReference, WorkstationError};
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};
use trench_core::heritage::compile_designer_stage;
use trench_core::minifloat::PackedStage;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceEndpoint {
    Low,
    High,
}

impl SourceEndpoint {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::High => "high",
        }
    }

    pub fn from_int(value: i32) -> Result<Self, WorkstationError> {
        match value {
            0 => Ok(Self::Low),
            1 => Ok(Self::High),
            _ => Err(WorkstationError("source endpoint must be LOW or HIGH".to_owned())),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DesignerSection {
    pub index: usize,
    #[serde(rename = "type")]
    pub type_id: u8,
    #[serde(rename = "lowFreq")]
    pub low_freq: u8,
    #[serde(rename = "lowGain")]
    pub low_gain: u8,
    #[serde(rename = "highFreq")]
    pub high_freq: u8,
    #[serde(rename = "highGain")]
    pub high_gain: u8,
}

impl DesignerSection {
    fn endpoint(self: &Self, endpoint: SourceEndpoint) -> (u8, u8) {
        match endpoint {
            SourceEndpoint::Low => (self.low_freq, self.low_gain),
            SourceEndpoint::High => (self.high_freq, self.high_gain),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct XmlSource {
    pub index: usize,
    pub name: String,
    #[serde(rename = "relativePath")]
    pub relative_path: String,
    #[serde(rename = "fileSha256")]
    pub file_sha256: String,
    pub frequency: f64,
    pub gain: f64,
    #[serde(rename = "activeSections")]
    pub active_sections: usize,
    pub sections: Vec<DesignerSection>,
    #[serde(skip)]
    pub absolute_path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SourceCatalog {
    pub format: String,
    pub directory: String,
    #[serde(rename = "repositoryCommit")]
    pub repository_commit: String,
    pub sources: Vec<XmlSource>,
}

pub struct CompiledSourceStage {
    pub words: PackedStage,
    pub evidence: EvidenceReference,
    pub source: StageSourceReference,
}

impl SourceCatalog {
    /// Discover the external read-only XML well. A missing well leaves an
    /// empty catalog so the packed workstation can still open elsewhere.
    pub fn discover(repo_root: &Path) -> Result<Self, WorkstationError> {
        let directory = std::env::var_os("TRENCH_HERITAGE_XML_DIR")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                repo_root
                    .parent()
                    .unwrap_or(repo_root)
                    .join("df2")
                    .join("ref")
                    .join("heritage")
            });
        let external_repo = directory
            .parent()
            .and_then(Path::parent)
            .unwrap_or(&directory);
        let repository_commit = read_git_commit(external_repo)
            .unwrap_or_else(|| "UNKNOWN".to_owned());
        let mut catalog = Self {
            format: "trench-workstation-xml-catalog-v1".to_owned(),
            directory: directory.display().to_string(),
            repository_commit,
            sources: Vec::new(),
        };
        if !directory.is_dir() {
            return Ok(catalog);
        }

        let mut paths = fs::read_dir(&directory)?
            .filter_map(Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.extension()
                    .and_then(|extension| extension.to_str())
                    .is_some_and(|extension| extension.eq_ignore_ascii_case("xml"))
            })
            .collect::<Vec<_>>();
        paths.sort_by_key(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .unwrap_or_default()
                .to_ascii_lowercase()
        });
        for (index, path) in paths.into_iter().enumerate() {
            catalog.sources.push(parse_source(index, &path)?);
        }
        Ok(catalog)
    }

    pub fn compile_stage(
        &self,
        source_index: usize,
        endpoint: SourceEndpoint,
        section_index: usize,
    ) -> Result<CompiledSourceStage, WorkstationError> {
        let source = self.sources.get(source_index).ok_or_else(|| {
            WorkstationError(format!("XML source index {source_index} is out of range"))
        })?;
        let section = source.sections.get(section_index).ok_or_else(|| {
            WorkstationError(format!("source section {} is out of range", section_index + 1))
        })?;
        let shift = -32 + ((source.frequency + source.gain) * 63.0) as i32;
        let (freq, gain) = section.endpoint(endpoint);
        let words = compile_designer_stage(section.type_id, freq, gain, shift)
            .map_err(|error| WorkstationError(error.to_owned()))?;
        let note = format!(
            "Read-only XML endpoint {}; section {}; type {}; freq {}; gain {}; global shift {}.",
            endpoint.as_str().to_ascii_uppercase(),
            section.index,
            section.type_id,
            freq,
            gain,
            shift
        );
        Ok(CompiledSourceStage {
            words,
            evidence: EvidenceReference {
                external_repository_commit: self.repository_commit.clone(),
                relative_path: source.relative_path.clone(),
                file_sha256: source.file_sha256.clone(),
                evidence_type: "external-morph-designer-xml".to_owned(),
                note,
            },
            source: StageSourceReference {
                catalog_index: source.index,
                source_name: source.name.clone(),
                relative_path: source.relative_path.clone(),
                file_sha256: source.file_sha256.clone(),
                endpoint: endpoint.as_str().to_owned(),
                section_index: section.index,
            },
        })
    }
}

fn parse_source(index: usize, path: &Path) -> Result<XmlSource, WorkstationError> {
    let bytes = fs::read(path)?;
    let xml = std::str::from_utf8(&bytes)
        .map_err(|_| WorkstationError(format!("{} is not UTF-8 XML", path.display())))?;
    let frequency = tag_text(xml, "frequency")?.parse::<f64>().map_err(|_| {
        WorkstationError(format!("{} has invalid frequency", path.display()))
    })?;
    let gain = tag_text(xml, "gain")?
        .parse::<f64>()
        .map_err(|_| WorkstationError(format!("{} has invalid gain", path.display())))?;
    let mut sections = Vec::new();
    let mut rest = xml;
    while let Some(start) = rest.find("<designer-section") {
        rest = &rest[start..];
        let Some(open_end) = rest.find('>') else {
            return Err(WorkstationError(format!(
                "{} has an unterminated designer-section",
                path.display()
            )));
        };
        let Some(close) = rest.find("</designer-section>") else {
            return Err(WorkstationError(format!(
                "{} has an unterminated designer-section",
                path.display()
            )));
        };
        let open = &rest[..=open_end];
        let block = &rest[..close];
        let section_index = attribute(open, "index")?.parse::<usize>().map_err(|_| {
            WorkstationError(format!("{} has invalid section index", path.display()))
        })?;
        sections.push(DesignerSection {
            index: section_index,
            type_id: tag_u8(block, "type", path)?,
            low_freq: tag_u8(block, "low-freq", path)?,
            low_gain: tag_u8(block, "low-gain", path)?,
            high_freq: tag_u8(block, "high-freq", path)?,
            high_gain: tag_u8(block, "high-gain", path)?,
        });
        rest = &rest[close + "</designer-section>".len()..];
    }
    sections.sort_by_key(|section| section.index);
    if sections.len() != 6 || sections.iter().enumerate().any(|(i, section)| section.index != i + 1)
    {
        return Err(WorkstationError(format!(
            "{} must contain registered sections 1..6",
            path.display()
        )));
    }
    let name = path
        .file_stem()
        .and_then(|name| name.to_str())
        .ok_or_else(|| WorkstationError("XML source filename is not UTF-8".to_owned()))?
        .to_owned();
    let active_sections = sections.iter().filter(|section| section.type_id != 0).count();
    Ok(XmlSource {
        index,
        name,
        relative_path: format!("ref/heritage/{}", path.file_name().unwrap().to_string_lossy()),
        file_sha256: sha256_hex(&bytes),
        frequency,
        gain,
        active_sections,
        sections,
        absolute_path: path.to_path_buf(),
    })
}

fn tag_u8(xml: &str, tag: &str, path: &Path) -> Result<u8, WorkstationError> {
    let value = tag_text(xml, tag)?.parse::<u8>().map_err(|_| {
        WorkstationError(format!("{} has invalid <{tag}>", path.display()))
    })?;
    if value > 127 {
        return Err(WorkstationError(format!(
            "{} <{tag}> is outside 0..127",
            path.display()
        )));
    }
    Ok(value)
}

fn tag_text<'a>(xml: &'a str, tag: &str) -> Result<&'a str, WorkstationError> {
    let opener = format!("<{tag}");
    let start = xml
        .find(&opener)
        .ok_or_else(|| WorkstationError(format!("missing <{tag}>")))?;
    let after_open = xml[start..]
        .find('>')
        .map(|offset| start + offset + 1)
        .ok_or_else(|| WorkstationError(format!("unterminated <{tag}>")))?;
    let closer = format!("</{tag}>");
    let end = xml[after_open..]
        .find(&closer)
        .map(|offset| after_open + offset)
        .ok_or_else(|| WorkstationError(format!("missing {closer}")))?;
    Ok(xml[after_open..end].trim())
}

fn attribute<'a>(open_tag: &'a str, name: &str) -> Result<&'a str, WorkstationError> {
    let key = format!("{name}=\"");
    let start = open_tag
        .find(&key)
        .map(|offset| offset + key.len())
        .ok_or_else(|| WorkstationError(format!("missing {name} attribute")))?;
    let end = open_tag[start..]
        .find('"')
        .map(|offset| start + offset)
        .ok_or_else(|| WorkstationError(format!("unterminated {name} attribute")))?;
    Ok(&open_tag[start..end])
}

fn read_git_commit(repo: &Path) -> Option<String> {
    let mut git_dir = repo.join(".git");
    if git_dir.is_file() {
        let pointer = fs::read_to_string(&git_dir).ok()?;
        let target = pointer.trim().strip_prefix("gitdir:")?.trim();
        git_dir = if Path::new(target).is_absolute() {
            PathBuf::from(target)
        } else {
            repo.join(target)
        };
    }
    let head = fs::read_to_string(git_dir.join("HEAD")).ok()?;
    let head = head.trim();
    if let Some(reference) = head.strip_prefix("ref: ") {
        if let Ok(value) = fs::read_to_string(git_dir.join(reference)) {
            return Some(value.trim().to_owned());
        }
        let packed = fs::read_to_string(git_dir.join("packed-refs")).ok()?;
        return packed.lines().find_map(|line| {
            let (hash, name) = line.split_once(' ')?;
            (name == reference).then(|| hash.to_owned())
        });
    }
    Some(head.to_owned())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn source_catalog_is_sorted_and_section_registered_when_well_exists() {
        let source = Path::new(file!());
        let root = if source.is_absolute() {
            source.ancestors().nth(3).unwrap()
        } else {
            Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap()
        };
        let catalog = SourceCatalog::discover(root).unwrap();
        if catalog.sources.is_empty() {
            return;
        }
        assert!(catalog.sources.windows(2).all(|pair| {
            pair[0].name.to_ascii_lowercase() <= pair[1].name.to_ascii_lowercase()
        }));
        assert!(catalog.sources.iter().all(|source| source.sections.len() == 6));
        let mut compiled = 0usize;
        for source in &catalog.sources {
            for endpoint in [SourceEndpoint::Low, SourceEndpoint::High] {
                for section in 0..6 {
                    let stage = catalog
                        .compile_stage(source.index, endpoint, section)
                        .unwrap();
                    assert!(trench_core::minifloat::stage_words_to_biquad(stage.words)
                        .iter()
                        .all(|value| value.is_finite()));
                    compiled += 1;
                }
            }
        }
        eprintln!(
            "OBSERVED: {} XML sources, {} endpoint sections compiled",
            catalog.sources.len(),
            compiled
        );
    }
}
