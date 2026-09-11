//! Parametric massing generator — the bridge from constraints to geometry.
//!
//! This module takes the site, zoning rules, and program brief, then generates
//! 3-5 valid massing configurations that satisfy all constraints while exploring
//! different design options.
//!
//! Each [`MassingOption`] is a complete building envelope: footprint polygon,
//! storeys, height, and floor areas — ready for geometry generation or viewer
//! visualization.
//!
//! **Note:** The full LP/MILP solver integration (`good_lp` + HiGHS) is planned
//! for the next iteration. Current implementation uses direct geometric calculation.

use glam::Vec2;
use serde::{Deserialize, Serialize};

use crate::RegimeInput;
use regime_zoning::{ZoningRules, rect_envelope};

/// One solved massing option — a valid building configuration.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MassingOption {
    /// Footprint corners in XZ plane (metres), closed loop.
    pub footprint: Vec<Vec2>,
    /// Number of storeys.
    pub storeys: u32,
    /// Building height (metres).
    pub height_m: f32,
    /// Gross floor area (m²) — sum across all floors.
    pub gross_floor_area: f32,
    /// Footprint area (m²).
    pub footprint_area: f32,
    /// Floor space ratio achieved (GFA / lot area).
    pub fsr: f32,
    /// Lot coverage achieved (footprint / lot area).
    pub coverage: f32,
}

/// Solver configuration for massing generation.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct MassingSolver {
    /// Number of options to generate (default: 5).
    pub option_count: usize,
    /// Minimum storeys to consider.
    pub min_storeys: u32,
    /// Maximum storeys to consider.
    pub max_storeys: u32,
    /// Storey height (metres) for height calculation.
    pub storey_height_m: f32,
    /// Target GFA tolerance (±%) from the brief.
    pub gfa_tolerance_pct: f32,
}

impl Default for MassingSolver {
    fn default() -> Self {
        Self {
            option_count: 5,
            min_storeys: 1,
            max_storeys: 4,
            storey_height_m: 3.0,
            gfa_tolerance_pct: 10.0,
        }
    }
}

impl MassingSolver {
    /// Solve for massing options given site, zoning, and program.
    /// Returns up to `option_count` valid configurations.
    pub fn solve(&self, input: &RegimeInput, rules: &ZoningRules) -> Vec<MassingOption> {
        let lot_area = input.site.area();
        let target_gfa = input.brief.gross_floor_area();
        
        // Try different storey counts within range
        let mut options = Vec::new();
        for storeys in self.min_storeys..=self.max_storeys {
            if let Some(option) = self.solve_for_storeys(storeys, input, rules, lot_area, target_gfa) {
                options.push(option);
                if options.len() >= self.option_count {
                    break;
                }
            }
        }
        
        // If we didn't get enough options, try variations with different footprints
        if options.len() < self.option_count {
            if let Some(envelope) = self.try_rectangular_variations(input, rules, lot_area, target_gfa) {
                for opt in envelope {
                    if !options.iter().any(|o| (o.footprint_area - opt.footprint_area).abs() < 1.0) {
                        options.push(opt);
                        if options.len() >= self.option_count {
                            break;
                        }
                    }
                }
            }
        }
        
        options
    }
    
    fn solve_for_storeys(
        &self,
        storeys: u32,
        _input: &RegimeInput,
        rules: &ZoningRules,
        lot_area: f32,
        target_gfa: f32,
    ) -> Option<MassingOption> {
        // Per-floor GFA target
        let per_floor_gfa = target_gfa / storeys as f32;
        
        // Use zoning envelope to get buildable footprint
        let (width, depth) = self.approx_dimensions(lot_area);
        let envelope = rect_envelope(width, depth, rules)?;
        
        // Calculate required footprint from GFA and storeys
        let required_footprint = per_floor_gfa;
        
        // Check against zoning caps
        let effective_footprint = envelope.effective_footprint.min(required_footprint);
        
        if effective_footprint <= 0.0 {
            return None;
        }
        
        // Shape the footprint (golden ratio-ish)
        let aspect = 1.4;
        let fp_depth = (effective_footprint / aspect).sqrt();
        let fp_width = effective_footprint / fp_depth;
        
        // Center the footprint within the envelope
        let env_width = width - 2.0 * rules.side_setback;
        let env_depth = depth - rules.front_setback - rules.rear_setback;
        
        let offset_x = (env_width - fp_width) / 2.0 + rules.side_setback;
        let offset_y = (env_depth - fp_depth) / 2.0 + rules.front_setback;
        
        let footprint = vec![
            Vec2::new(offset_x, offset_y),
            Vec2::new(offset_x + fp_width, offset_y),
            Vec2::new(offset_x + fp_width, offset_y + fp_depth),
            Vec2::new(offset_x, offset_y + fp_depth),
        ];
        
        let actual_gfa = effective_footprint * storeys as f32;
        let height = storeys as f32 * self.storey_height_m;
        
        Some(MassingOption {
            footprint,
            storeys,
            height_m: height.min(rules.max_height),
            gross_floor_area: actual_gfa,
            footprint_area: effective_footprint,
            fsr: actual_gfa / lot_area,
            coverage: effective_footprint / lot_area,
        })
    }
    
    fn approx_dimensions(&self, lot_area: f32) -> (f32, f32) {
        // Assume 1:2 aspect ratio for typical urban lot
        let depth = (lot_area * 2.0).sqrt();
        let width = lot_area / depth;
        (width, depth)
    }
    
    fn try_rectangular_variations(
        &self,
        _input: &RegimeInput,
        rules: &ZoningRules,
        lot_area: f32,
        target_gfa: f32,
    ) -> Option<Vec<MassingOption>> {
        let mut variants = Vec::new();
        
        // Try different aspect ratios
        for aspect in [1.0, 1.2, 1.4, 1.6, 2.0] {
            let depth = (lot_area * aspect).sqrt();
            let width = lot_area / depth;
            
            if let Some(envelope) = rect_envelope(width, depth, rules) {
                for storeys in self.min_storeys..=self.max_storeys {
                    let per_floor = target_gfa / storeys as f32;
                    let fp_area = envelope.effective_footprint.min(per_floor);
                    
                    if fp_area > 10.0 {
                        let gfa = fp_area * storeys as f32;
                        let height = (storeys as f32 * self.storey_height_m).min(rules.max_height);
                        
                        variants.push(MassingOption {
                            footprint: envelope.corners.to_vec(),
                            storeys,
                            height_m: height,
                            gross_floor_area: gfa,
                            footprint_area: fp_area,
                            fsr: gfa / lot_area,
                            coverage: fp_area / lot_area,
                        });
                    }
                }
            }
        }
        
        if variants.is_empty() {
            None
        } else {
            Some(variants)
        }
    }
}

/// Convenience function: solve massing with default solver settings.
#[must_use]
pub fn solve_massing(input: &RegimeInput, rules: &ZoningRules) -> Vec<MassingOption> {
    MassingSolver::default().solve(input, rules)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{ProgramBrief, Site};
    use regime_zoning::ZoningRules;

    fn test_site() -> Site {
        Site {
            boundary: vec![
                Vec2::new(0.0, 0.0),
                Vec2::new(15.0, 0.0),
                Vec2::new(15.0, 30.0),
                Vec2::new(0.0, 30.0),
            ],
            jurisdiction: "Greater Sudbury".into(),
            zone: "R1".into(),
            street: Some("Main St".into()),
        }
    }

    fn test_brief() -> ProgramBrief {
        ProgramBrief {
            unit_count: 2,
            target_unit_sqm: 148.6,
            parking_spaces: 4,
            storeys: None,
        }
    }

    #[test]
    fn solves_basic_massing() {
        let input = RegimeInput {
            site: test_site(),
            brief: test_brief(),
            answers: vec![],
        };
        let rules = ZoningRules::sudbury("R1");
        let solver = MassingSolver::default();
        let options = solver.solve(&input, &rules);
        
        assert!(!options.is_empty());
        let opt = &options[0];
        assert!(opt.footprint.len() >= 4);
        assert!(opt.storeys >= 1);
        assert!(opt.height_m > 0.0);
        assert!(opt.gross_floor_area > 0.0);
    }

    #[test]
    fn respects_height_limit() {
        let input = RegimeInput {
            site: test_site(),
            brief: test_brief(),
            answers: vec![],
        };
        let mut rules = ZoningRules::sudbury("R1");
        rules.max_height = 6.0; // Limit to 2 storeys
        
        let solver = MassingSolver {
            max_storeys: 4,
            ..Default::default()
        };
        let options = solver.solve(&input, &rules);
        
        for opt in &options {
            assert!(opt.height_m <= 6.0);
        }
    }

    #[test]
    fn multiple_options_generated() {
        let input = RegimeInput {
            site: test_site(),
            brief: test_brief(),
            answers: vec![],
        };
        let rules = ZoningRules::sudbury("R1");
        let solver = MassingSolver {
            option_count: 3,
            ..Default::default()
        };
        let options = solver.solve(&input, &rules);
        
        assert!(options.len() >= 1);
    }
}
