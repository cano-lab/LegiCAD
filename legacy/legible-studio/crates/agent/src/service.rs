use std::path::{Path, PathBuf};

use archgeometry::SchemaDocument;
use base64::Engine as _;
use serde::{Deserialize, Serialize};

pub const PROFESSIONAL_REVIEW_DISCLAIMER: &str = "This automated report reflects checks implemented by Legible Studio. It is not a substitute for review by a qualified designer, building official, or professional engineer where required.";

#[derive(Debug, thiserror::Error)]
pub enum AgentError {
    #[error("schema parse: {0}")]
    SchemaParse(String),
    #[error("OBC init: {0}")]
    ObcInit(String),
    #[error("solver: {0}")]
    Solver(String),
    #[error("patch: {0}")]
    Patch(String),
    #[error("export: {0}")]
    Export(String),
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ValidationOptions {
    #[serde(default)]
    pub jurisdiction: Option<String>,
    #[serde(default)]
    pub code: Option<String>,
    #[serde(default)]
    pub climate_zone: Option<String>,
    #[serde(default)]
    pub include_part3: Option<bool>,
    #[serde(default)]
    pub include_coverage: Option<bool>,
    #[serde(default)]
    pub obc_dir: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidateRequest {
    pub building: serde_json::Value,
    #[serde(default)]
    pub options: ValidationOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidateResponse {
    pub passes: bool,
    pub summary: ValidationSummary,
    pub issues: Vec<ValidationIssue>,
    pub validation: qbd::ValidationResult,
    pub coverage: ValidationCoverage,
    pub layout_quality: Vec<crate::layout_quality::LayoutQualityIssue>,
    pub disclaimer: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationSummary {
    pub overall_pass: bool,
    pub critical: usize,
    pub failures: usize,
    pub warnings: usize,
    pub checked_reports: usize,
    pub walls_checked: i32,
    pub walls_passed: i32,
    pub walls_failed: i32,
    pub thermal_compliance: bool,
    pub average_r_value: f32,
    pub part3_reports: usize,
    pub stair_reports: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum IssueSeverity {
    Critical,
    Error,
    Warning,
    Info,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum IssueCategory {
    Part3Egress,
    Part3FireSeparation,
    Part3Occupancy,
    Part3Stairs,
    Part9Stairs,
    Thermal,
    WallAssembly,
    ModeSanity,
    LayoutQuality,
    Other,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationIssue {
    pub id: String,
    pub severity: IssueSeverity,
    pub category: IssueCategory,
    pub status: String,
    pub code_section: String,
    pub rule_name: String,
    pub element_ids: Vec<String>,
    pub level: Option<String>,
    pub message: String,
    pub requirement: String,
    pub actual: String,
    pub suggested_fix_kinds: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationCoverage {
    pub jurisdiction: String,
    pub code: String,
    pub mode: String,
    pub checked: Vec<String>,
    pub skipped: Vec<String>,
    pub not_implemented: Vec<String>,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SuggestFixesOptions {
    #[serde(default)]
    pub max_fixes: Option<usize>,
    #[serde(default)]
    pub implemented_only: Option<bool>,
    #[serde(default)]
    pub validation_options: ValidationOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SuggestFixesRequest {
    pub building: serde_json::Value,
    #[serde(default)]
    pub options: SuggestFixesOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SuggestFixesResponse {
    pub fixes: Vec<DesignFix>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesignFix {
    pub id: String,
    pub issue_ids: Vec<String>,
    pub fix_type: String,
    pub confidence: f32,
    pub severity_reduction: f32,
    pub destructive: bool,
    pub implemented: bool,
    pub rationale: String,
    pub code_sections: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub patch: Option<DesignPatch>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApplyPatchRequest {
    pub building: serde_json::Value,
    pub patch: DesignPatch,
    #[serde(default)]
    pub options: ApplyPatchOptions,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ApplyPatchOptions {
    #[serde(default)]
    pub validate_before: bool,
    #[serde(default)]
    pub validate_after: bool,
    #[serde(default)]
    pub validation_options: ValidationOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ApplyPatchResponse {
    pub applied: bool,
    pub dry_run: bool,
    pub changed_element_ids: Vec<String>,
    pub warnings: Vec<String>,
    pub errors: Vec<String>,
    pub building: SchemaDocument,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub validation_before: Option<Box<ValidateResponse>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub validation_after: Option<Box<ValidateResponse>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub score_delta: Option<ValidationScoreDelta>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationScoreDelta {
    pub before: i32,
    pub after: i32,
    pub delta: i32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DesignPatch {
    pub patch_id: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub dry_run: bool,
    pub ops: Vec<DesignPatchOp>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
pub enum DesignPatchOp {
    WidenStair {
        stair_id: String,
        width_clear_mm: f32,
    },
    LowerFloorToFloor {
        level: String,
        target_height_mm: f32,
    },
    ChangeLevelOccupancy {
        level: String,
        occupancy: String,
    },
    ChangeRoomType {
        room_id: String,
        room_type: String,
    },
    ResizeRoom {
        room_id: String,
        target_area_m2: f32,
    },
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct IterateRequest {
    pub building: serde_json::Value,
    #[serde(default)]
    pub max_iterations: Option<usize>,
    #[serde(default)]
    pub validation_options: ValidationOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IterateResponse {
    pub status: String,
    pub passes: bool,
    pub blocked_reason: Option<String>,
    pub iterations: Vec<IterationTrace>,
    pub building: SchemaDocument,
    pub validation: ValidateResponse,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IterationTrace {
    pub iteration: usize,
    pub issues_before: usize,
    pub patches_applied: Vec<String>,
    pub issues_after: usize,
    pub score_before: i32,
    pub score_after: i32,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExportProjectInfo {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub designer: Option<String>,
    #[serde(default)]
    pub bcin: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportBundleRequest {
    pub building: serde_json::Value,
    #[serde(default)]
    pub outputs: Vec<String>,
    #[serde(default)]
    pub project: ExportProjectInfo,
    #[serde(default)]
    pub validation_options: ValidationOptions,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportBundleResponse {
    pub bundle_id: String,
    pub files: Vec<ExportedFile>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportedFile {
    pub name: String,
    pub mime: String,
    pub bytes: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content_base64: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SolveTemplateRequest {
    pub template: String,
    #[serde(default)]
    pub storeys: Option<u32>,
    #[serde(default)]
    pub sqft: Option<f32>,
    #[serde(default)]
    pub rooms_per_floor: Option<u32>,
    #[serde(default)]
    pub bedrooms: Option<u32>,
    #[serde(default)]
    pub bathrooms: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CatalogResponse {
    pub modes: Vec<String>,
    pub templates: Vec<String>,
    pub room_types: Vec<String>,
}

#[must_use]
pub fn catalog(mode: Option<&str>) -> CatalogResponse {
    let parsed = mode
        .unwrap_or("part9")
        .parse::<solver::BuildingMode>()
        .unwrap_or(solver::BuildingMode::Part9);
    let cat = solver::RoomCatalog::for_mode(parsed);
    CatalogResponse {
        modes: vec!["part9".into(), "part3".into(), "mixed".into()],
        templates: vec![
            "part9_house".into(),
            "small_office".into(),
            "neighbourhood_retail".into(),
            "community_assembly".into(),
            "light_industrial".into(),
            "mixed_use_podium".into(),
            "college_residence".into(),
        ],
        room_types: cat.room_types(),
    }
}

pub fn solve_template(req: &SolveTemplateRequest) -> Result<serde_json::Value, AgentError> {
    let sqft = req.sqft.unwrap_or(4_000.0);
    let storeys = req.storeys.unwrap_or(2);
    let rooms_per_floor = req.rooms_per_floor.unwrap_or(20);
    let template = match req.template.as_str() {
        "house" | "part9_house" | "part9-house" | "residential" => {
            solver::BuildingTemplate::Part9House {
                bedrooms: req.bedrooms.unwrap_or(3),
                bathrooms: req.bathrooms.unwrap_or(2),
                sqft,
            }
        }
        "office" | "small_office" | "small-office" => {
            solver::BuildingTemplate::SmallOffice { storeys, sqft }
        }
        "retail" | "neighbourhood_retail" | "neighborhood_retail" => {
            solver::BuildingTemplate::NeighbourhoodRetail { sqft }
        }
        "assembly" | "community_assembly" | "hall" => {
            solver::BuildingTemplate::CommunityAssembly { sqft }
        }
        "industrial" | "light_industrial" => solver::BuildingTemplate::LightIndustrial { sqft },
        "mixed" | "mixed_use" | "mixed_use_podium" | "podium" => {
            solver::BuildingTemplate::MixedUsePodium {
                retail_sqft: sqft,
                residential_floors: storeys.saturating_sub(1).max(1),
            }
        }
        "college" | "college_residence" | "dorm" => solver::BuildingTemplate::CollegeResidence {
            floors: storeys,
            rooms_per_floor,
            sqft,
        },
        other => return Err(AgentError::Solver(format!("unknown template '{other}'"))),
    };
    let manifest = template.manifest();
    if let Err(errors) = manifest.validate() {
        return Err(AgentError::Solver(format!(
            "template manifest invalid: {errors:?}"
        )));
    }
    Ok(solver::building_json_from_manifest(&manifest))
}

pub fn solve_manifest(manifest: &solver::ProgramManifest) -> Result<serde_json::Value, AgentError> {
    if let Err(errors) = manifest.validate() {
        return Err(AgentError::Solver(format!("manifest invalid: {errors:?}")));
    }
    Ok(solver::building_json_from_manifest(manifest))
}

pub fn validate(req: &ValidateRequest) -> Result<ValidateResponse, AgentError> {
    let doc = parse_document(&req.building)?;
    validate_doc(&doc, &req.options)
}

pub fn validate_doc(
    doc: &SchemaDocument,
    options: &ValidationOptions,
) -> Result<ValidateResponse, AgentError> {
    let climate_zone = options.climate_zone.as_deref().unwrap_or("Zone 6");
    let obc_dir = options.obc_dir.clone().unwrap_or_else(default_obc_dir);
    let mut engine = obc::OBCEngine::new();
    engine
        .initialize(&obc_dir)
        .map_err(|e| AgentError::ObcInit(format!("{} ({})", e, obc_dir.display())))?;

    let include_part3 = options.include_part3.unwrap_or(true);
    let mut part3_engine = obc::Part3Engine::new();
    let part3_ready = include_part3 && part3_engine.initialize(&obc_dir).is_ok();
    let validation = if part3_ready {
        qbd::validate_layout_with_part3(&engine, Some(&part3_engine), doc, climate_zone)
    } else {
        qbd::validate_layout(&engine, doc, climate_zone)
    };
    let mut issues = flatten_issues(&validation);
    issues.extend(mode_sanity_issues(doc));
    let layout_quality = crate::layout_quality::check(doc);
    issues.extend(layout_quality.iter().cloned().map(layout_quality_issue));
    let coverage = coverage_for(doc, options, part3_ready);
    let summary = summarize(&validation, &issues);
    Ok(ValidateResponse {
        passes: validation.overall_pass
            && !issues.iter().any(|i| i.severity == IssueSeverity::Critical),
        summary,
        issues,
        validation,
        coverage,
        layout_quality,
        disclaimer: PROFESSIONAL_REVIEW_DISCLAIMER.into(),
    })
}

pub fn suggest_fixes(req: &SuggestFixesRequest) -> Result<SuggestFixesResponse, AgentError> {
    let doc = parse_document(&req.building)?;
    let validation = validate_doc(&doc, &req.options.validation_options)?;
    let implemented_only = req.options.implemented_only.unwrap_or(false);
    let max = req.options.max_fixes.unwrap_or(20);
    let mut fixes = Vec::new();

    for (idx, fix) in qbd::analyze(&doc).into_iter().enumerate() {
        let (fix_type, implemented, rationale, patch) = match fix {
            qbd::EgressFix::InjectCorridor { level, rooms } => (
                "inject_corridor".to_string(),
                false,
                format!(
                    "Level {level} has rooms isolated from the egress graph: {}.",
                    rooms.join(", ")
                ),
                None,
            ),
            qbd::EgressFix::AddStair { level } => (
                "add_stair_core".to_string(),
                false,
                format!("Level {level} requires another remote exit/stair."),
                None,
            ),
            qbd::EgressFix::LowerFloorToFloor {
                level,
                current_ft,
                recommended_ft,
            } => {
                let patch = DesignPatch {
                    patch_id: format!("patch_lower_floor_to_floor_l{level}"),
                    description: Some(
                        "Lower floor-to-floor height for public-stair riser compliance.".into(),
                    ),
                    dry_run: false,
                    ops: vec![DesignPatchOp::LowerFloorToFloor {
                        level: format!("Level {level}"),
                        target_height_mm: recommended_ft * 304.8,
                    }],
                };
                (
                    "lower_floor_to_floor".to_string(),
                    true,
                    format!(
                        "Level {level} floor-to-floor height {current_ft:.2} ft should be reduced toward {recommended_ft:.2} ft for stair riser compliance."
                    ),
                    Some(patch),
                )
            }
        };
        if implemented_only && !implemented {
            continue;
        }
        fixes.push(DesignFix {
            id: format!("fix_{idx}_{fix_type}"),
            issue_ids: matching_issue_ids(&validation.issues, &fix_type),
            fix_type,
            confidence: if implemented { 0.75 } else { 0.45 },
            severity_reduction: if implemented { 30.0 } else { 10.0 },
            destructive: false,
            implemented,
            rationale,
            code_sections: vec!["OBC 3.4".into(), "OBC 3.4.6".into()],
            patch,
        });
        if fixes.len() >= max {
            break;
        }
    }

    for report in &validation.validation.stair_reports {
        if !report.passes() {
            if let Some(stair) = doc
                .stairs
                .iter()
                .find(|st| report.element_id.contains(&st.level_name))
            {
                let patch = DesignPatch {
                    patch_id: format!("patch_widen_{}", stair.id),
                    description: Some("Widen stair clear width.".into()),
                    dry_run: false,
                    ops: vec![DesignPatchOp::WidenStair {
                        stair_id: stair.id.clone(),
                        width_clear_mm: stair.width_clear.max(1_100.0),
                    }],
                };
                fixes.push(DesignFix {
                    id: format!("fix_widen_{}", stair.id),
                    issue_ids: validation
                        .issues
                        .iter()
                        .filter(|i| i.element_ids.iter().any(|id| id == &report.element_id))
                        .map(|i| i.id.clone())
                        .collect(),
                    fix_type: "widen_stair".into(),
                    confidence: 0.8,
                    severity_reduction: 30.0,
                    destructive: false,
                    implemented: true,
                    rationale: format!("Widen stair {} clear width to at least 1100 mm.", stair.id),
                    code_sections: vec!["OBC 9.8".into(), "OBC 3.4.6".into()],
                    patch: Some(patch),
                });
            }
        }
        if fixes.len() >= max {
            break;
        }
    }

    fixes.truncate(max);
    Ok(SuggestFixesResponse { fixes })
}

pub fn apply_patch(req: &ApplyPatchRequest) -> Result<ApplyPatchResponse, AgentError> {
    let mut doc = parse_document(&req.building)?;
    let before = if req.options.validate_before {
        Some(Box::new(validate_doc(
            &doc,
            &req.options.validation_options,
        )?))
    } else {
        None
    };
    let mut warnings = Vec::new();
    let mut errors = Vec::new();
    let mut changed = Vec::new();
    let mut applied_any = false;

    if !req.patch.dry_run {
        for op in &req.patch.ops {
            match apply_op(&mut doc, op) {
                Ok(Some(id)) => {
                    applied_any = true;
                    changed.push(id);
                }
                Ok(None) => warnings.push(format!(
                    "op already satisfied or target not changed: {op:?}"
                )),
                Err(e) => errors.push(e),
            }
        }
    }

    let after = if req.options.validate_after {
        Some(Box::new(validate_doc(
            &doc,
            &req.options.validation_options,
        )?))
    } else {
        None
    };
    let score_delta = match (&before, &after) {
        (Some(b), Some(a)) => {
            let before_score = severity_score(&b.issues);
            let after_score = severity_score(&a.issues);
            Some(ValidationScoreDelta {
                before: before_score,
                after: after_score,
                delta: before_score - after_score,
            })
        }
        _ => None,
    };

    Ok(ApplyPatchResponse {
        applied: applied_any && errors.is_empty(),
        dry_run: req.patch.dry_run,
        changed_element_ids: changed,
        warnings,
        errors,
        building: doc,
        validation_before: before,
        validation_after: after,
        score_delta,
    })
}

pub fn iterate(req: &IterateRequest) -> Result<IterateResponse, AgentError> {
    let mut doc = parse_document(&req.building)?;
    let max_iterations = req.max_iterations.unwrap_or(8);
    let mut traces = Vec::new();
    let mut final_validation = validate_doc(&doc, &req.validation_options)?;
    if final_validation.passes {
        return Ok(IterateResponse {
            status: "passed".into(),
            passes: true,
            blocked_reason: None,
            iterations: traces,
            building: doc,
            validation: final_validation,
        });
    }

    for iteration in 1..=max_iterations {
        let before_score = severity_score(&final_validation.issues);
        let before_count = final_validation.issues.len();
        let building_value =
            serde_json::to_value(&doc).map_err(|e| AgentError::Patch(e.to_string()))?;
        let suggestions = suggest_fixes(&SuggestFixesRequest {
            building: building_value.clone(),
            options: SuggestFixesOptions {
                max_fixes: Some(5),
                implemented_only: Some(true),
                validation_options: req.validation_options.clone(),
            },
        })?;
        let Some(fix) = suggestions
            .fixes
            .into_iter()
            .find(|f| f.implemented && f.patch.is_some())
        else {
            return Ok(IterateResponse {
                status: "blocked".into(),
                passes: false,
                blocked_reason: Some("No implemented fix available for remaining issues.".into()),
                iterations: traces,
                building: doc,
                validation: final_validation,
            });
        };
        let patch = fix.patch.expect("checked is_some");
        let apply = apply_patch(&ApplyPatchRequest {
            building: building_value,
            patch: patch.clone(),
            options: ApplyPatchOptions {
                validate_before: false,
                validate_after: true,
                validation_options: req.validation_options.clone(),
            },
        })?;
        doc = apply.building;
        final_validation = apply
            .validation_after
            .map_or_else(|| validate_doc(&doc, &req.validation_options), |v| Ok(*v))?;
        let after_score = severity_score(&final_validation.issues);
        traces.push(IterationTrace {
            iteration,
            issues_before: before_count,
            patches_applied: vec![patch.patch_id],
            issues_after: final_validation.issues.len(),
            score_before: before_score,
            score_after: after_score,
        });
        if final_validation.passes {
            return Ok(IterateResponse {
                status: "passed".into(),
                passes: true,
                blocked_reason: None,
                iterations: traces,
                building: doc,
                validation: final_validation,
            });
        }
        if after_score >= before_score {
            return Ok(IterateResponse {
                status: "no_progress".into(),
                passes: false,
                blocked_reason: Some(
                    "Applied patch did not reduce validation severity score.".into(),
                ),
                iterations: traces,
                building: doc,
                validation: final_validation,
            });
        }
    }
    Ok(IterateResponse {
        status: "max_iterations".into(),
        passes: final_validation.passes,
        blocked_reason: Some("Maximum iterations reached.".into()),
        iterations: traces,
        building: doc,
        validation: final_validation,
    })
}

pub fn export_bundle(req: &ExportBundleRequest) -> Result<ExportBundleResponse, AgentError> {
    let doc = parse_document(&req.building)?;
    let validation = validate_doc(&doc, &req.validation_options).ok();
    let project_name = req
        .project
        .name
        .clone()
        .unwrap_or_else(|| "Agent Project".into());
    let project_info = drawing::ProjectInfo {
        name: project_name.clone(),
        number: doc.building_id.clone(),
        solver: "Legible Agent Runtime".into(),
        designer: req.project.designer.clone().unwrap_or_default(),
        designer_bcin: req.project.bcin.clone().unwrap_or_default(),
        climate_zone: req
            .validation_options
            .climate_zone
            .clone()
            .unwrap_or_else(|| "Zone 6".into()),
        ..Default::default()
    };
    let docs = match &validation {
        Some(v) => qbd::generate_documentation_with_validation_for_project(
            &doc,
            project_info,
            &v.validation,
        ),
        None => qbd::generate_documentation_for_project(&doc, project_info),
    };
    let wanted = if req.outputs.is_empty() {
        vec!["svg".to_string()]
    } else {
        req.outputs.clone()
    };
    let wants = |s: &str| wanted.iter().any(|w| w == s);
    let svg_sheets = documentation_sheets(&docs);
    let mut files = Vec::new();
    if wants("svg") {
        for (name, svg) in &svg_sheets {
            files.push(text_file(name, "image/svg+xml", svg.clone()));
        }
    }
    if wants("pdf") {
        for (name, svg) in &svg_sheets {
            let pdf = qbd::svg_to_pdf(svg).map_err(|e| AgentError::Export(e.to_string()))?;
            files.push(binary_file(
                &name.replace(".svg", ".pdf"),
                "application/pdf",
                pdf,
            ));
        }
        let combined =
            qbd::svgs_to_pdf(&svg_sheets).map_err(|e| AgentError::Export(e.to_string()))?;
        files.push(binary_file(
            "permit_set_combined.pdf",
            "application/pdf",
            combined,
        ));
    }
    if wants("png") {
        for (name, svg) in &svg_sheets {
            let png = qbd::svg_to_png(svg, 1600).map_err(|e| AgentError::Export(e.to_string()))?;
            files.push(binary_file(&name.replace(".svg", ".png"), "image/png", png));
        }
    }
    if wants("dxf") {
        if !docs.floor_plan_dxf.is_empty() {
            files.push(text_file(
                "02_floor_plan.dxf",
                "application/dxf",
                String::from_utf8_lossy(&docs.floor_plan_dxf).into_owned(),
            ));
        }
        for elev in &docs.elevations {
            if !elev.dxf.is_empty() {
                let name = drawing::elevation_sheet_name(elev.direction).replace(".svg", ".dxf");
                files.push(text_file(
                    &name,
                    "application/dxf",
                    String::from_utf8_lossy(&elev.dxf).into_owned(),
                ));
            }
        }
    }
    if wants("ifc") {
        files.push(text_file(
            "model.ifc",
            "application/step",
            qbd::ifc::to_ifc(&doc, &project_name, &docs.generated_date),
        ));
    }
    let manifest =
        serde_json::to_string_pretty(&files).map_err(|e| AgentError::Export(e.to_string()))?;
    files.push(text_file("manifest.json", "application/json", manifest));
    Ok(ExportBundleResponse {
        bundle_id: stable_id(&serde_json::to_value(&doc).unwrap_or_default()),
        files,
    })
}

fn parse_document(value: &serde_json::Value) -> Result<SchemaDocument, AgentError> {
    let json = serde_json::to_string(value).map_err(|e| AgentError::SchemaParse(e.to_string()))?;
    archgeometry::parse_json(&json).map_err(|e| AgentError::SchemaParse(e.to_string()))
}

fn default_obc_dir() -> PathBuf {
    if let Ok(dir) = std::env::var("LEGIBLE_OBC_DIR") {
        return PathBuf::from(dir);
    }
    let manifest_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.join("..").join("..").join("OBC_Library")
}

fn flatten_issues(validation: &qbd::ValidationResult) -> Vec<ValidationIssue> {
    let mut issues = Vec::new();
    for report in validation
        .wall_reports
        .iter()
        .chain(validation.stair_reports.iter())
        .chain(validation.part3_reports.iter())
    {
        for check in &report.checks {
            let status = format!("{:?}", check.status).to_lowercase();
            if matches!(
                check.status,
                obc::ComplianceStatus::Pass | obc::ComplianceStatus::NotApplicable
            ) {
                continue;
            }
            let category = categorize(&report.element_type, &check.rule_name, &check.code_section);
            let severity = severity_for(check.status, &category);
            issues.push(ValidationIssue {
                id: issue_id(&report.element_id, &check.rule_name, issues.len()),
                severity,
                category: category.clone(),
                status,
                code_section: check.code_section.clone(),
                rule_name: check.rule_name.clone(),
                element_ids: vec![report.element_id.clone()],
                level: extract_level(&report.element_id),
                message: check.message.clone(),
                requirement: check.requirement.clone(),
                actual: check.actual.clone(),
                suggested_fix_kinds: suggested_fix_kinds(&category, &check.rule_name),
            });
        }
    }
    if !validation.thermal_compliance {
        issues.push(ValidationIssue {
            id: "issue_thermal_envelope".into(),
            severity: IssueSeverity::Error,
            category: IssueCategory::Thermal,
            status: "fail".into(),
            code_section: "OBC 9.36".into(),
            rule_name: "thermal envelope".into(),
            element_ids: vec!["building".into()],
            level: None,
            message: "Average exterior wall R-value is below the required value.".into(),
            requirement: "Meet or exceed OBC minimum effective R-value.".into(),
            actual: format!("R-{:.1}", validation.average_r_value),
            suggested_fix_kinds: vec!["upgrade_wall_assembly".into()],
        });
    }
    issues
}

fn mode_sanity_issues(doc: &SchemaDocument) -> Vec<ValidationIssue> {
    let mut out = Vec::new();
    let mode = doc.qbd_answers.mode.as_str();
    let explicit_part3 = doc.levels.iter().any(|l| l.occupancy.is_some())
        || doc.rooms.values().any(|r| {
            matches!(
                r.room_type.as_str(),
                "retail" | "office_open" | "assembly" | "auditorium" | "classroom" | "dorm_room"
            )
        });
    if mode == "part9" && (doc.levels.len() > 3 || explicit_part3) {
        out.push(ValidationIssue {
            id: "issue_mode_mismatch_part9_part3".into(),
            severity: IssueSeverity::Warning,
            category: IssueCategory::ModeSanity,
            status: "warning".into(),
            code_section: "mode selection".into(),
            rule_name: "declared mode sanity".into(),
            element_ids: vec!["building".into()],
            level: None,
            message: "Declared mode is part9, but program/height appears to require Part 3 or mixed-mode checks.".into(),
            requirement: "Use part3 or mixed when building geometry/program triggers Part 3.".into(),
            actual: format!("mode={mode}, levels={}", doc.levels.len()),
            suggested_fix_kinds: vec!["change_mode".into()],
        });
    }
    out
}

fn coverage_for(
    doc: &SchemaDocument,
    options: &ValidationOptions,
    part3_ready: bool,
) -> ValidationCoverage {
    let mode = doc.qbd_answers.mode.clone();
    let mut checked = vec![
        "wall_assemblies".into(),
        "thermal_envelope".into(),
        "stairs_obc_9_8".into(),
    ];
    let mut skipped = Vec::new();
    if part3_ready && matches!(mode.as_str(), "part3" | "mixed") {
        checked.extend([
            "part3_area_height_storeys".into(),
            "part3_occupant_load".into(),
            "part3_egress".into(),
            "part3_stairs".into(),
            "part3_fire_separation".into(),
            "part3_exit_discharge".into(),
        ]);
    } else {
        skipped.push("part3_checks".into());
    }
    ValidationCoverage {
        jurisdiction: options
            .jurisdiction
            .clone()
            .unwrap_or_else(|| "Ontario".into()),
        code: options.code.clone().unwrap_or_else(|| "OBC".into()),
        mode,
        checked,
        skipped,
        not_implemented: vec![
            "zoning".into(),
            "part11_renovation_compliance".into(),
            "full_structural_engineering".into(),
            "mechanical_hvac_design".into(),
            "plumbing_design".into(),
        ],
        warnings: vec![PROFESSIONAL_REVIEW_DISCLAIMER.into()],
    }
}

fn summarize(validation: &qbd::ValidationResult, issues: &[ValidationIssue]) -> ValidationSummary {
    ValidationSummary {
        overall_pass: validation.overall_pass,
        critical: issues
            .iter()
            .filter(|i| i.severity == IssueSeverity::Critical)
            .count(),
        failures: issues
            .iter()
            .filter(|i| matches!(i.severity, IssueSeverity::Critical | IssueSeverity::Error))
            .count(),
        warnings: issues
            .iter()
            .filter(|i| i.severity == IssueSeverity::Warning)
            .count(),
        checked_reports: validation.wall_reports.len()
            + validation.stair_reports.len()
            + validation.part3_reports.len(),
        walls_checked: validation.walls_checked,
        walls_passed: validation.walls_passed,
        walls_failed: validation.walls_failed,
        thermal_compliance: validation.thermal_compliance,
        average_r_value: validation.average_r_value,
        part3_reports: validation.part3_reports.len(),
        stair_reports: validation.stair_reports.len(),
    }
}

fn categorize(element_type: &str, rule: &str, section: &str) -> IssueCategory {
    let text = format!("{element_type} {rule} {section}").to_lowercase();
    if text.contains("fire separation") {
        IssueCategory::Part3FireSeparation
    } else if text.contains("egress")
        || text.contains("exit")
        || text.contains("travel")
        || text.contains("discharge")
    {
        IssueCategory::Part3Egress
    } else if text.contains("occupant")
        || text.contains("occupancy")
        || text.contains("area")
        || text.contains("height")
    {
        IssueCategory::Part3Occupancy
    } else if element_type == "stair" || text.contains("stair") {
        if section.contains("3.") {
            IssueCategory::Part3Stairs
        } else {
            IssueCategory::Part9Stairs
        }
    } else if text.contains("thermal") || text.contains("r-value") {
        IssueCategory::Thermal
    } else if element_type.contains("wall") {
        IssueCategory::WallAssembly
    } else {
        IssueCategory::Other
    }
}

fn severity_for(status: obc::ComplianceStatus, category: &IssueCategory) -> IssueSeverity {
    match status {
        obc::ComplianceStatus::Fail
            if matches!(
                category,
                IssueCategory::Part3Egress
                    | IssueCategory::Part3FireSeparation
                    | IssueCategory::Part3Stairs
            ) =>
        {
            IssueSeverity::Critical
        }
        obc::ComplianceStatus::Fail => IssueSeverity::Error,
        obc::ComplianceStatus::Warning | obc::ComplianceStatus::DataMissing => {
            IssueSeverity::Warning
        }
        _ => IssueSeverity::Info,
    }
}

fn suggested_fix_kinds(category: &IssueCategory, rule: &str) -> Vec<String> {
    let mut out = match category {
        IssueCategory::Part3Egress => vec![
            "add_stair_core".into(),
            "inject_corridor".into(),
            "add_exit_door".into(),
        ],
        IssueCategory::Part3Stairs | IssueCategory::Part9Stairs => {
            vec!["widen_stair".into(), "lower_floor_to_floor".into()]
        }
        IssueCategory::Part3FireSeparation => vec!["add_fire_separation_annotation".into()],
        IssueCategory::Thermal => vec!["upgrade_wall_assembly".into()],
        _ => Vec::new(),
    };
    if rule.to_lowercase().contains("width") && !out.iter().any(|s| s == "widen_stair") {
        out.push("widen_stair".into());
    }
    out
}

fn issue_id(element_id: &str, rule: &str, idx: usize) -> String {
    let raw = format!("{element_id}_{rule}_{idx}");
    format!("issue_{}", sanitize(&raw))
}

fn sanitize(s: &str) -> String {
    let mut out = String::new();
    for ch in s.chars() {
        if ch.is_ascii_alphanumeric() {
            out.push(ch.to_ascii_lowercase());
        } else if !out.ends_with('_') {
            out.push('_');
        }
    }
    out.trim_matches('_').to_string()
}

fn extract_level(s: &str) -> Option<String> {
    let idx = s.find("Level ")?;
    let rest = &s[idx..];
    let level = rest
        .split(|c: char| !(c.is_ascii_alphanumeric() || c == ' '))
        .next()
        .unwrap_or(rest)
        .trim();
    if level.is_empty() {
        None
    } else {
        Some(level.to_string())
    }
}

fn matching_issue_ids(issues: &[ValidationIssue], fix_type: &str) -> Vec<String> {
    issues
        .iter()
        .filter(|i| i.suggested_fix_kinds.iter().any(|k| k == fix_type))
        .map(|i| i.id.clone())
        .collect()
}

fn layout_quality_issue(issue: crate::layout_quality::LayoutQualityIssue) -> ValidationIssue {
    ValidationIssue {
        id: issue.id,
        severity: IssueSeverity::Warning,
        category: IssueCategory::LayoutQuality,
        status: "warning".into(),
        code_section: "layout quality".into(),
        rule_name: format!("{:?}", issue.kind).to_lowercase(),
        element_ids: issue.element_ids,
        level: issue.level,
        message: issue.message,
        requirement: "Rooms and corridors should be well-connected and serve a clear purpose.".into(),
        actual: "Layout connectivity or proportion suggests an awkward or unused space.".into(),
        suggested_fix_kinds: vec!["rearrange_layout".into()],
    }
}

fn apply_op(doc: &mut SchemaDocument, op: &DesignPatchOp) -> Result<Option<String>, String> {
    match op {
        DesignPatchOp::WidenStair {
            stair_id,
            width_clear_mm,
        } => {
            let Some(stair) = doc.stairs.iter_mut().find(|s| &s.id == stair_id) else {
                return Err(format!("stair '{stair_id}' not found"));
            };
            if stair.width_clear >= *width_clear_mm {
                return Ok(None);
            }
            stair.width_clear = *width_clear_mm;
            Ok(Some(stair_id.clone()))
        }
        DesignPatchOp::LowerFloorToFloor {
            level,
            target_height_mm,
        } => {
            let mut changed = false;
            for lvl in &mut doc.levels {
                if &lvl.name == level && (lvl.height - *target_height_mm).abs() > 0.1 {
                    lvl.height = *target_height_mm;
                    changed = true;
                }
            }
            for stair in &mut doc.stairs {
                if &stair.level_name == level
                    && (stair.floor_to_floor - *target_height_mm).abs() > 0.1
                {
                    stair.floor_to_floor = *target_height_mm;
                    if stair.num_risers > 0 {
                        stair.riser_height = *target_height_mm / stair.num_risers as f32;
                    }
                    changed = true;
                }
            }
            Ok(changed.then(|| level.clone()))
        }
        DesignPatchOp::ChangeLevelOccupancy { level, occupancy } => {
            let Some(lvl) = doc.levels.iter_mut().find(|l| &l.name == level) else {
                return Err(format!("level '{level}' not found"));
            };
            if lvl.occupancy.as_deref() == Some(occupancy.as_str()) {
                return Ok(None);
            }
            lvl.occupancy = Some(occupancy.clone());
            Ok(Some(level.clone()))
        }
        DesignPatchOp::ChangeRoomType { room_id, room_type } => {
            let Some(room) = doc.rooms.get_mut(room_id) else {
                return Err(format!("room '{room_id}' not found"));
            };
            if room.room_type == *room_type {
                return Ok(None);
            }
            room.room_type = room_type.clone();
            Ok(Some(room_id.clone()))
        }
        DesignPatchOp::ResizeRoom {
            room_id,
            target_area_m2,
        } => {
            let Some(room) = doc.rooms.get_mut(room_id) else {
                return Err(format!("room '{room_id}' not found"));
            };
            if (room.area - *target_area_m2).abs() < 0.01 {
                return Ok(None);
            }
            room.area = *target_area_m2;
            Ok(Some(room_id.clone()))
        }
    }
}

fn severity_score(issues: &[ValidationIssue]) -> i32 {
    issues
        .iter()
        .map(|i| match i.severity {
            IssueSeverity::Critical => 100,
            IssueSeverity::Error => 30,
            IssueSeverity::Warning => 5,
            IssueSeverity::Info => 1,
        })
        .sum()
}

fn documentation_sheets(docs: &qbd::Documentation) -> Vec<(String, String)> {
    let mut sheets = Vec::new();
    let mut push = |name: String, svg: &str| {
        if !svg.is_empty() {
            sheets.push((name, svg.to_string()));
        }
    };
    push("01_site_plan.svg".into(), &docs.site_plan_svg);
    for (idx, (_level, svg)) in docs.floor_plans.iter().enumerate() {
        let name = if idx == 0 {
            "02_floor_plan.svg".into()
        } else {
            format!("02_floor_plan_l{}.svg", idx + 1)
        };
        push(name, svg);
    }
    for elev in &docs.elevations {
        push(drawing::elevation_sheet_name(elev.direction), &elev.svg);
    }
    push("04_section_aa.svg".into(), &docs.section_svg);
    push("05_door_schedule.svg".into(), &docs.door_schedule_svg);
    push("05_window_schedule.svg".into(), &docs.window_schedule_svg);
    push("06_roof_plan.svg".into(), &docs.roof_plan_svg);
    for (i, detail) in docs.wall_details.iter().enumerate() {
        push(
            format!(
                "07_wall_detail_{:02}_{}.svg",
                i + 1,
                detail.detail.wall_type_id
            ),
            &detail.svg,
        );
    }
    push("08_foundation_plan.svg".into(), &docs.foundation_plan_svg);
    push(
        "09_compliance_report.svg".into(),
        &docs.compliance_report_svg,
    );
    push("10_framing_plan.svg".into(), &docs.framing_plan_svg);
    push("11_footing_detail.svg".into(), &docs.footing_detail_svg);
    push("12_stair_section.svg".into(), &docs.stair_section_svg);
    sheets
}

fn text_file(name: &str, mime: &str, text: String) -> ExportedFile {
    ExportedFile {
        name: name.into(),
        mime: mime.into(),
        bytes: text.len(),
        text: Some(text),
        content_base64: None,
    }
}

fn binary_file(name: &str, mime: &str, bytes: Vec<u8>) -> ExportedFile {
    ExportedFile {
        name: name.into(),
        mime: mime.into(),
        bytes: bytes.len(),
        text: None,
        content_base64: Some(base64::engine::general_purpose::STANDARD.encode(bytes)),
    }
}

fn stable_id(value: &serde_json::Value) -> String {
    let bytes = serde_json::to_vec(value).unwrap_or_default();
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for byte in bytes {
        h ^= u64::from(byte);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{:016x}", h)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn catalog_exposes_part3_templates() {
        let c = catalog(Some("part3"));
        assert!(c.templates.contains(&"college_residence".to_string()));
        assert!(c.room_types.contains(&"retail".to_string()));
    }

    #[test]
    fn solve_template_generates_building_json() {
        let value = solve_template(&SolveTemplateRequest {
            template: "college_residence".into(),
            storeys: Some(2),
            rooms_per_floor: Some(4),
            sqft: Some(8_000.0),
            bedrooms: None,
            bathrooms: None,
        })
        .unwrap();
        assert_eq!(value["success"], true);
        assert_eq!(value["qbd_answers"]["mode"], "part3");
    }

    #[test]
    fn patch_widens_stair_idempotently() {
        let value = solve_template(&SolveTemplateRequest {
            template: "part9_house".into(),
            storeys: None,
            rooms_per_floor: None,
            sqft: Some(2_400.0),
            bedrooms: Some(3),
            bathrooms: Some(2),
        })
        .unwrap();
        let mut doc = parse_document(&value).unwrap();
        let Some(stair_id) = doc.stairs.first().map(|s| s.id.clone()) else {
            return;
        };
        assert!(
            apply_op(
                &mut doc,
                &DesignPatchOp::WidenStair {
                    stair_id: stair_id.clone(),
                    width_clear_mm: 1100.0,
                },
            )
            .unwrap()
            .is_some()
        );
        assert!(
            apply_op(
                &mut doc,
                &DesignPatchOp::WidenStair {
                    stair_id,
                    width_clear_mm: 1100.0,
                },
            )
            .unwrap()
            .is_none()
        );
    }

    #[test]
    fn validate_default_house_returns_structured_coverage() {
        let value = solve_template(&SolveTemplateRequest {
            template: "part9_house".into(),
            storeys: None,
            rooms_per_floor: None,
            sqft: Some(1_600.0),
            bedrooms: Some(3),
            bathrooms: Some(2),
        })
        .unwrap();
        let response = validate(
            &ValidateRequest {
                building: value,
                options: ValidationOptions::default(),
            }
        )
        .unwrap();
        assert!(response.coverage.checked.contains(&"wall_assemblies".into()));
        assert!(response.disclaimer.contains("not a substitute"));
    }

    #[test]
    fn part9_house_layout_quality_has_no_hallway_to_nowhere() {
        let value = solve_template(&SolveTemplateRequest {
            template: "part9_house".into(),
            storeys: Some(2),
            rooms_per_floor: None,
            sqft: Some(2_400.0),
            bedrooms: Some(3),
            bathrooms: Some(2),
        })
        .unwrap();
        let response = validate(
            &ValidateRequest {
                building: value,
                options: ValidationOptions::default(),
            }
        )
        .unwrap();
        eprintln!(
            "layout quality issues for default Part 9 house: {}",
            response.layout_quality.len()
        );
        for issue in &response.layout_quality {
            eprintln!("  {:?}: {}", issue.kind, issue.message);
        }
        // A well-formed Part 9 house should not have hallways to nowhere.
        assert!(
            !response
                .layout_quality
                .iter()
                .any(|i| i.kind == crate::layout_quality::LayoutQualityIssueKind::HallwayToNowhere),
            "generated Part 9 house has a hallway to nowhere"
        );
        assert!(
            !response
                .layout_quality
                .iter()
                .any(|i| i.kind == crate::layout_quality::LayoutQualityIssueKind::DeadEndHallway),
            "generated Part 9 house has a dead-end hallway"
        );
    }

    #[test]
    fn iterate_part9_house_reaches_pass_or_clean_blocked() {
        let value = solve_template(&SolveTemplateRequest {
            template: "part9_house".into(),
            storeys: Some(2),
            rooms_per_floor: None,
            sqft: Some(2_400.0),
            bedrooms: Some(3),
            bathrooms: Some(2),
        })
        .unwrap();
        let response = iterate(&IterateRequest {
            building: value,
            max_iterations: Some(8),
            validation_options: ValidationOptions::default(),
        })
        .unwrap();
        // We accept either a pass or a blocked/no-progress that is not a crash.
        // Print the trace so a human can inspect the loop behaviour.
        eprintln!("iterate status: {}", response.status);
        eprintln!("iterate passes: {}", response.passes);
        eprintln!("iterate blocked_reason: {:?}", response.blocked_reason);
        for trace in &response.iterations {
            eprintln!(
                "  iter {}: issues {} -> {}, score {} -> {}, patches {:?}",
                trace.iteration,
                trace.issues_before,
                trace.issues_after,
                trace.score_before,
                trace.score_after,
                trace.patches_applied
            );
        }
        assert!(
            response.passes
                || response.status == "blocked"
                || response.status == "no_progress"
                || response.status == "max_iterations",
            "unexpected iterate status: {}",
            response.status
        );
    }

    #[test]
    fn part3_college_layout_quality_diagnostic() {
        let value = solve_template(&SolveTemplateRequest {
            template: "college_residence".into(),
            storeys: Some(2),
            rooms_per_floor: Some(4),
            sqft: Some(8_000.0),
            bedrooms: None,
            bathrooms: None,
        })
        .unwrap();
        let response = validate(
            &ValidateRequest {
                building: value,
                options: ValidationOptions {
                    include_part3: Some(true),
                    ..ValidationOptions::default()
                },
            }
        )
        .unwrap();
        eprintln!(
            "layout quality issues for Part 3 college residence: {}",
            response.layout_quality.len()
        );
        for issue in &response.layout_quality {
            eprintln!("  {:?}: {}", issue.kind, issue.message);
        }
    }

    #[test]
    fn iterate_part3_college_exercises_the_loop() {
        let value = solve_template(&SolveTemplateRequest {
            template: "college_residence".into(),
            storeys: Some(2),
            rooms_per_floor: Some(4),
            sqft: Some(8_000.0),
            bedrooms: None,
            bathrooms: None,
        })
        .unwrap();
        let response = iterate(&IterateRequest {
            building: value,
            max_iterations: Some(8),
            validation_options: ValidationOptions {
                include_part3: Some(true),
                ..ValidationOptions::default()
            },
        })
        .unwrap();
        eprintln!("iterate status: {}", response.status);
        eprintln!("iterate passes: {}", response.passes);
        eprintln!("iterate blocked_reason: {:?}", response.blocked_reason);
        for trace in &response.iterations {
            eprintln!(
                "  iter {}: issues {} -> {}, score {} -> {}, patches {:?}",
                trace.iteration,
                trace.issues_before,
                trace.issues_after,
                trace.score_before,
                trace.score_after,
                trace.patches_applied
            );
        }
        // The loop must terminate cleanly; we do not require a pass here because
        // the college template is intentionally exposing known solver gaps.
        assert!(
            response.passes
                || response.status == "blocked"
                || response.status == "no_progress"
                || response.status == "max_iterations",
            "unexpected iterate status: {}",
            response.status
        );
    }
}
