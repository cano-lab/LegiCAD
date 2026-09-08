//! Section-sheet generator (the "permit-set section drawing", not the
//! slicer's `slice::generate_section` 3D->2D operator).
//!
//! Port of `ArchEngine_kernel/scripts/generate_sections.py` (278 LOC).
//! Produces a single section drawing for one cut plane through the
//! building: cut walls, floor slab, roof profile, grade line, level
//! markers, title.

use std::fmt::Write as _;

use glam::Vec3;

/// Minimal wall description for section-sheet generation: just the
/// centreline endpoints, height, and category (for thickness).
/// Callers convert from their richer schema (qbd does
/// `SchemaWall` -> `SectionWallInput`).
#[derive(Debug, Clone)]
pub struct SectionWallInput {
    pub start: Vec3,
    pub end: Vec3,
    pub height: f32,
    /// `"exterior"` => 150 mm thick, anything else => 100 mm.
    pub category: String,
    /// Floor base elevation (mm) the wall sits on — non-zero for upper storeys
    /// so the section stacks.
    pub base: f32,
}

/// One envelope-assembly callout for the section's thermal notes block.
/// Drives the OBC 9.25 / SB-12 thermal demonstration: each lists an assembly
/// (wall / roof-ceiling / floor) with its effective R-value and a spec line.
#[derive(Debug, Clone)]
pub struct AssemblyCallout {
    /// Short heading, e.g. `"EXTERIOR WALL"`, `"ROOF / CEILING"`, `"FLOOR"`.
    pub label: String,
    /// Assembly description, e.g. `"2x6 @ 16\" o.c. + R-22 batt + R-5 c.i."`.
    pub spec: String,
    /// Effective R-value shown as `R-{n}` (rounded).
    pub r_value: f32,
}

/// Minimal building input for section-sheet generation. `width` is used
/// only to pick the default cut plane (centre of building).
#[derive(Debug, Clone, Default)]
pub struct SectionInput {
    pub width: f32,
    pub walls: Vec<SectionWallInput>,
    /// Maximum ridge height above the wall plate (mm). Multiple roofs
    /// contribute their tallest ridge; if empty, no roof element appears.
    pub ridge_heights_above_plate: Vec<f32>,
    /// Storey base elevations (mm) above grade — a level line is drawn at each.
    pub floor_lines: Vec<f32>,
    /// Clear floor-to-plate ceiling height (mm) for the ground storey. When 0,
    /// it is derived from the tallest ground-storey wall.
    pub ceiling_height_mm: f32,
    /// Envelope-assembly callouts rendered as a thermal notes block. Empty =
    /// no block (back-compatible with callers that don't supply them).
    pub assemblies: Vec<AssemblyCallout>,
    /// Eave overhang projected past the exterior wall (mm). The roof profile
    /// extends this far beyond each side wall so the section shows the eaves.
    /// 0 = roof flush with the wall (legacy).
    pub eave_overhang_mm: f32,
}

/// Direction of the section cut plane.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CutDirection {
    /// Cut perpendicular to the X axis. Walls running in the Z direction are
    /// intersected. Section view's horizontal axis is Z.
    Transverse,
    /// Cut perpendicular to the Z axis. Walls running in the X direction are
    /// intersected. Section view's horizontal axis is X.
    Longitudinal,
}

/// View direction for the cut — purely a label on the drawing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewDirection {
    East,
    West,
    North,
    South,
}

impl ViewDirection {
    fn as_str(self) -> &'static str {
        match self {
            ViewDirection::East => "east",
            ViewDirection::West => "west",
            ViewDirection::North => "north",
            ViewDirection::South => "south",
        }
    }
}

/// A section cut through the building.
#[derive(Debug, Clone)]
pub struct SectionCut {
    pub name: String,
    /// X coordinate of the cut plane (mm). Used when `direction == Transverse`.
    pub cut_x: f32,
    /// Z coordinate of the cut plane (mm). Used when `direction == Longitudinal`.
    pub cut_z: f32,
    pub direction: CutDirection,
    pub view_direction: ViewDirection,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ElementType {
    Wall,
    Floor,
    Roof,
}

#[derive(Debug, Clone)]
struct SectionElement {
    element_type: ElementType,
    /// Horizontal position in the section view (Z for transverse, X for longitudinal).
    x: f32,
    y_bottom: f32,
    y_top: f32,
    /// For walls: thickness in mm.
    width: f32,
}

/// Generate section elements for a cut through the building. Port of
/// `generate_section` (`generate_sections.py:37`).
fn generate_section_elements(input: &SectionInput, cut: &SectionCut) -> Vec<SectionElement> {
    let tolerance = 100.0_f32; // mm

    let mut elements: Vec<SectionElement> = Vec::new();

    for wall in &input.walls {
        let (s, e) = (wall.start, wall.end);
        let intersects = match cut.direction {
            CutDirection::Transverse => {
                let min_x = s.x.min(e.x);
                let max_x = s.x.max(e.x);
                cut.cut_x >= min_x - tolerance && cut.cut_x <= max_x + tolerance
            }
            CutDirection::Longitudinal => {
                let min_z = s.z.min(e.z);
                let max_z = s.z.max(e.z);
                cut.cut_z >= min_z - tolerance && cut.cut_z <= max_z + tolerance
            }
        };
        if !intersects {
            continue;
        }

        let pos = match cut.direction {
            CutDirection::Transverse => (s.z + e.z) * 0.5,
            CutDirection::Longitudinal => (s.x + e.x) * 0.5,
        };
        let thickness = if wall.category == "exterior" {
            150.0
        } else {
            100.0
        };

        elements.push(SectionElement {
            element_type: ElementType::Wall,
            x: pos,
            y_bottom: wall.base,
            y_top: wall.base + wall.height,
            width: thickness,
        });
    }

    // Ground-floor slab (150 mm below grade).
    elements.push(SectionElement {
        element_type: ElementType::Floor,
        x: 0.0,
        y_bottom: -150.0,
        y_top: 0.0,
        width: 0.0,
    });

    // Intermediate floor platforms: a joist+subfloor band at each upper-storey
    // level, so the section shows the floor structure cut through (not just a
    // line). Depth ≈ 2x10 joist + subfloor.
    const FLOOR_PLATFORM_MM: f32 = 300.0;
    for &fy in &input.floor_lines {
        if fy > 1.0 {
            elements.push(SectionElement {
                element_type: ElementType::Floor,
                x: 0.0,
                y_bottom: fy - FLOOR_PLATFORM_MM,
                y_top: fy,
                width: 0.0,
            });
        }
    }

    // Roof elements sit on the top plate — the tallest wall top in the cut
    // (so a multi-storey roof rides above the upper storey), with a 2700 mm
    // fallback when no walls were cut.
    let plate = elements
        .iter()
        .filter(|e| matches!(e.element_type, ElementType::Wall))
        .map(|e| e.y_top)
        .fold(0.0_f32, f32::max)
        .max(2700.0);

    // Ceiling joists: a band just below the top plate. Drawn wall-to-wall so it
    // stays under the roof line (it must NOT poke past the eaves).
    const CEILING_MM: f32 = 250.0;
    if plate > CEILING_MM {
        elements.push(SectionElement {
            element_type: ElementType::Floor,
            x: 0.0,
            y_bottom: plate - CEILING_MM,
            y_top: plate,
            width: 0.0,
        });
    }

    for &ridge_above_base in &input.ridge_heights_above_plate {
        let base_height = plate;
        elements.push(SectionElement {
            element_type: ElementType::Roof,
            x: 0.0,
            y_bottom: base_height,
            y_top: base_height + ridge_above_base,
            width: 0.0,
        });
    }

    elements.sort_by(|a, b| a.x.partial_cmp(&b.x).unwrap_or(std::cmp::Ordering::Equal));
    elements
}

/// Default cut plane: transverse, through the centre of the building, looking east.
#[must_use]
pub fn default_cut(input: &SectionInput) -> SectionCut {
    SectionCut {
        name: "A-A".to_string(),
        cut_x: input.width * 0.5,
        cut_z: 0.0,
        direction: CutDirection::Transverse,
        view_direction: ViewDirection::East,
    }
}

/// Render the section to an SVG string. Port of `render_section_svg`
/// (`generate_sections.py:122`).
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn generate_section_sheet_svg(input: &SectionInput, cut: &SectionCut, scale: f32) -> String {
    let elements = generate_section_elements(input, cut);

    let (min_x, max_x) = elements
        .iter()
        .map(|e| e.x)
        .fold((f32::INFINITY, f32::NEG_INFINITY), |(a, b), x| {
            (a.min(x), b.max(x))
        });
    let (min_y, max_y) = elements
        .iter()
        .flat_map(|e| [e.y_bottom, e.y_top])
        .fold((f32::INFINITY, f32::NEG_INFINITY), |(a, b), y| {
            (a.min(y), b.max(y))
        });

    let (min_x, max_x) = if elements.is_empty() {
        (0.0_f32, 10_000.0_f32)
    } else {
        (min_x, max_x)
    };
    let (min_y, max_y) = if elements.is_empty() {
        (-200.0_f32, 5000.0_f32)
    } else {
        (min_y, max_y)
    };

    // Asymmetric margins: left holds the height dim + grade labels, right holds
    // the ceiling-height dim, top holds the assembly notes block, bottom holds
    // the overall width dim + title. Both sides also keep room for the roof's
    // eave overhang projecting past the wall.
    let oh = input.eave_overhang_mm.max(0.0);
    let margin_left = 2200.0_f32.max(oh + 700.0);
    let margin_right = 1800.0_f32.max(oh + 700.0);
    let margin_top = if input.assemblies.is_empty() { 800.0 } else { 3000.0 };
    let margin_bottom = 1600.0_f32;

    let vb_x = min_x - margin_left;
    let vb_y = min_y - margin_top;
    let vb_w = (max_x - min_x) + margin_left + margin_right;
    let vb_h = (max_y - min_y) + margin_top + margin_bottom;

    #[allow(clippy::cast_possible_truncation)]
    let px_w = (vb_w * scale) as i32;
    #[allow(clippy::cast_possible_truncation)]
    let px_h = (vb_h * scale) as i32;

    let mut s = String::with_capacity(4096);
    s.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{px_w}" height="{px_h}" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}">"#,
    );
    let _ = writeln!(s, "  <title>Section {}</title>", cut.name);
    s.push_str("  <rect width=\"100%\" height=\"100%\" fill=\"white\"/>\n");

    // Styles — match the Python's class names + sizes.
    s.push_str("  <style>\n");
    s.push_str("    .wall-cut { fill: #666; stroke: #000; stroke-width: 8; }\n");
    s.push_str("    .wall-below { fill: url(#earth-hatch); stroke: #000; stroke-width: 4; }\n");
    s.push_str("    .floor { fill: #999; stroke: #000; stroke-width: 4; }\n");
    s.push_str("    .roof { fill: url(#shingle-pattern); stroke: #000; stroke-width: 6; }\n");
    s.push_str("    .grade { stroke: #666; stroke-width: 6; fill: none; }\n");
    s.push_str("    .level-line { stroke: #999; stroke-width: 2; stroke-dasharray: 50,25; }\n");
    s.push_str(
        "    .level-text { font-family: Arial, sans-serif; font-size: 200px; fill: #666; }\n",
    );
    s.push_str("    .title { font-family: Arial, sans-serif; font-size: 400px; font-weight: bold; fill: #333; }\n");
    s.push_str(
        "    .dimension { font-family: Arial, sans-serif; font-size: 180px; fill: #333; }\n",
    );
    s.push_str("    .label { font-family: Arial, sans-serif; font-size: 250px; fill: #333; }\n");
    s.push_str("    .cut-line { stroke: #c00; stroke-width: 4; stroke-dasharray: 20,10; }\n");
    s.push_str("  </style>\n");

    // Patterns (earth-hatch under-grade, shingle on roof).
    s.push_str("  <defs>\n");
    s.push_str("    <pattern id=\"earth-hatch\" patternUnits=\"userSpaceOnUse\" width=\"200\" height=\"200\">\n");
    s.push_str("      <rect width=\"200\" height=\"200\" fill=\"#d4c9b8\"/>\n");
    s.push_str("      <line x1=\"0\" y1=\"200\" x2=\"200\" y2=\"0\" stroke=\"#b0a080\" stroke-width=\"6\"/>\n");
    s.push_str("    </pattern>\n");
    s.push_str("    <pattern id=\"shingle-pattern\" patternUnits=\"userSpaceOnUse\" width=\"400\" height=\"200\">\n");
    s.push_str("      <rect width=\"400\" height=\"200\" fill=\"#5a5a5a\"/>\n");
    s.push_str("      <line x1=\"0\" y1=\"100\" x2=\"400\" y2=\"100\" stroke=\"#484848\" stroke-width=\"6\"/>\n");
    s.push_str("      <line x1=\"0\" y1=\"200\" x2=\"400\" y2=\"200\" stroke=\"#484848\" stroke-width=\"6\"/>\n");
    s.push_str("    </pattern>\n");
    s.push_str("  </defs>\n");

    // Flip Y axis so positive-Y in mm goes UP on the page. ONLY geometry goes
    // in this group — text drawn here would render mirrored, so all labels and
    // dimensions are emitted upright afterwards in screen coordinates.
    let flip_y = max_y + min_y;
    // Map a model-space Y (mm, up-positive) to its screen Y inside the page.
    let sy = |model_y: f32| flip_y - model_y;
    let _ = writeln!(s, r#"<g transform="translate(0, {flip_y}) scale(1, -1)">"#);

    for elem in &elements {
        match elem.element_type {
            ElementType::Wall => {
                let w = elem.width;
                let x = elem.x - w * 0.5;
                let h = elem.y_top - elem.y_bottom;
                let _ = writeln!(
                    s,
                    r#"    <rect x="{x}" y="{yb}" width="{w}" height="{h}" class="wall-cut"/>"#,
                    yb = elem.y_bottom,
                );
            }
            ElementType::Floor => {
                // The ground slab (at/below grade) oversails the walls for the
                // foundation; floor platforms + ceiling joists stay wall-to-wall
                // so they never poke past the roof line.
                let (x, w) = if elem.y_top <= 0.0 {
                    (min_x - 500.0, max_x - min_x + 1000.0)
                } else {
                    (min_x, max_x - min_x)
                };
                let _ = writeln!(
                    s,
                    r#"    <rect x="{x}" y="{yb}" width="{w}" height="{h}" class="floor"/>"#,
                    yb = elem.y_bottom,
                    h = elem.y_top - elem.y_bottom,
                );
            }
            ElementType::Roof => {
                // The roof eaves overhang the side walls by `eave_overhang_mm`,
                // so the cut profile is wider than the wall box at the plate.
                let oh = input.eave_overhang_mm.max(0.0);
                let center_x = (min_x + max_x) * 0.5;
                let (xl, xr) = (min_x - oh, max_x + oh);
                let _ = writeln!(
                    s,
                    r#"    <polygon points="{xl},{yb} {center_x},{yt} {xr},{yb}" class="roof"/>"#,
                    yb = elem.y_bottom,
                    yt = elem.y_top,
                );
            }
        }
    }

    // Floor lines between storeys, so a multi-storey section reads as stacked.
    for &fy in &input.floor_lines {
        if fy > 0.0 && fy < max_y {
            let _ = writeln!(
                s,
                r#"    <line x1="{x1}" y1="{fy}" x2="{x2}" y2="{fy}" class="level-line"/>"#,
                x1 = min_x - 500.0,
                x2 = max_x + 500.0,
            );
        }
    }

    // Grade line (geometry).
    let _ = writeln!(
        s,
        r#"    <line x1="{x1}" y1="0" x2="{x2}" y2="0" class="grade"/>"#,
        x1 = min_x - 500.0,
        x2 = max_x + 500.0,
    );

    s.push_str("  </g>\n");

    // ---------------------------------------------------------------------
    // Upright annotations (screen coordinates, OUTSIDE the flipped group).
    // ---------------------------------------------------------------------

    // Grade marker + label.
    let grade_y = sy(0.0);
    let _ = writeln!(
        s,
        r#"  <line x1="{x1}" y1="{grade_y}" x2="{x2}" y2="{grade_y}" class="level-line"/>"#,
        x1 = min_x - 900.0,
        x2 = max_x + 900.0,
    );
    let _ = writeln!(
        s,
        r#"  <text x="{x}" y="{y}" class="level-text">EL. 0.0 (GRADE)</text>"#,
        x = vb_x + 100.0,
        y = grade_y - 80.0,
    );

    // Overall envelope dimensions: section width along the bottom, height
    // (ground-to-ridge) along the left.
    if max_x > min_x {
        let width_dim =
            crate::dimensions::LinearDim::horizontal_mm(min_x, max_x, sy(min_y) + 700.0);
        s.push_str(&crate::dimensions::render_horizontal(&width_dim, 200.0));
    }
    if max_y > 0.0 {
        let height_dim =
            crate::dimensions::LinearDim::vertical_mm(sy(max_y), sy(0.0), min_x - 800.0);
        s.push_str(&crate::dimensions::render_vertical(&height_dim, 200.0));
    }

    // Ceiling-height dimension (right side, ground storey floor-to-plate).
    let ground_plate = if input.ceiling_height_mm > 0.0 {
        input.ceiling_height_mm
    } else {
        elements
            .iter()
            .filter(|e| e.element_type == ElementType::Wall && e.y_bottom < 100.0)
            .map(|e| e.y_top)
            .fold(0.0_f32, f32::max)
    };
    if ground_plate > 0.0 {
        let clg_dim =
            crate::dimensions::LinearDim::vertical_mm(sy(ground_plate), sy(0.0), max_x + 800.0);
        s.push_str(&crate::dimensions::render_vertical(&clg_dim, 200.0));
        let _ = writeln!(
            s,
            r#"  <text x="{x}" y="{y}" class="dimension" text-anchor="middle">CEILING HT.</text>"#,
            x = max_x + 800.0,
            y = sy(ground_plate) - 150.0,
        );
    }

    // Envelope-assembly thermal notes block (top-left, upright). Demonstrates
    // OBC 9.25 / SB-12 effective R-values for the building envelope.
    if !input.assemblies.is_empty() {
        let bx = vb_x + 300.0;
        let mut by = vb_y + 500.0;
        let _ = writeln!(
            s,
            r##"  <text x="{bx}" y="{by}" font-family="Arial, sans-serif" font-size="240" font-weight="bold" fill="#333">ENVELOPE ASSEMBLIES (OBC SB-12)</text>"##,
        );
        by += 360.0;
        for a in &input.assemblies {
            #[allow(clippy::cast_possible_truncation)]
            let r = a.r_value.round() as i32;
            let _ = writeln!(
                s,
                r##"  <text x="{bx}" y="{by}" font-family="Arial, sans-serif" font-size="220" font-weight="bold" fill="#333">{label}: R-{r}</text>"##,
                label = crate::svg::xml_escape(&a.label),
            );
            by += 280.0;
            let _ = writeln!(
                s,
                r##"  <text x="{x}" y="{by}" font-family="Arial, sans-serif" font-size="185" fill="#555">{spec}</text>"##,
                x = bx + 200.0,
                spec = crate::svg::xml_escape(&a.spec),
            );
            by += 340.0;
        }
    }

    // Title + view label (upright, screen coordinates).
    let title_y = vb_y + vb_h - 200.0;
    let title_x = vb_x + vb_w * 0.5;
    let _ = writeln!(
        s,
        r#"  <text x="{title_x:.0}" y="{title_y}" text-anchor="middle" class="title">SECTION {name}</text>"#,
        name = cut.name,
    );
    let _ = writeln!(
        s,
        r#"  <text x="{x}" y="{y}" class="label">View: Looking {dir}</text>"#,
        x = vb_x + 200.0,
        y = title_y - 450.0,
        dir = cut.view_direction.as_str(),
    );

    s.push_str("</svg>\n");
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn rectangular_input() -> SectionInput {
        let mut input = SectionInput {
            width: 5000.0,
            ..Default::default()
        };
        for ((sx, sz), (ex, ez)) in [
            ((0.0, 0.0), (5000.0, 0.0)),
            ((5000.0, 0.0), (5000.0, 4000.0)),
            ((5000.0, 4000.0), (0.0, 4000.0)),
            ((0.0, 4000.0), (0.0, 0.0)),
        ] {
            input.walls.push(SectionWallInput {
                start: Vec3::new(sx, 0.0, sz),
                end: Vec3::new(ex, 0.0, ez),
                height: 2700.0,
                category: "exterior".into(),
                base: 0.0,
            });
        }
        input
    }

    #[test]
    fn transverse_cut_intersects_x_running_walls() {
        let input = rectangular_input();
        let cut = default_cut(&input); // transverse cut at X = 2500
        let elements = generate_section_elements(&input, &cut);
        // The 4-wall rectangle: 2 X-running walls (top/bottom) span X=[0,5000]
        // and intersect cut_x=2500; the 2 Z-running walls (left/right) have
        // a single X coordinate (0 or 5000), neither within ±100 of 2500.
        // So 2 walls hit. Floor elements: the ground slab + a ceiling-joist band
        // below the plate = 2.
        let wall_count = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Wall)
            .count();
        assert_eq!(wall_count, 2);
        let floor_count = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Floor)
            .count();
        assert_eq!(floor_count, 2);
    }

    #[test]
    fn two_storey_section_stacks_walls_and_draws_a_floor_line() {
        // A wall in the cut on each storey (ground base 0, upper base 3000).
        let mut input = SectionInput {
            width: 5000.0,
            floor_lines: vec![3000.0],
            ..Default::default()
        };
        for base in [0.0, 3000.0] {
            input.walls.push(SectionWallInput {
                start: Vec3::new(2500.0, 0.0, 0.0),
                end: Vec3::new(2500.0, 0.0, 4000.0),
                height: 2700.0,
                category: "exterior".into(),
                base,
            });
        }
        let cut = default_cut(&input);
        let svg = generate_section_sheet_svg(&input, &cut, 0.05);
        // Upper wall cut starts at y=3000 (stacked above the ground storey).
        assert!(svg.contains(r#"y="3000""#), "upper storey wall not stacked: {svg}");
        // Floor line between storeys.
        assert!(svg.contains(r#"y1="3000""#), "missing inter-storey floor line");
    }

    #[test]
    fn floor_lines_emit_intermediate_floor_platforms() {
        // Two storeys with an upper floor at 3000 → ground slab + one platform.
        let mut input = rectangular_input();
        input.floor_lines = vec![3000.0];
        let cut = default_cut(&input);
        let elements = generate_section_elements(&input, &cut);
        let floors: Vec<_> = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Floor)
            .collect();
        // Ground slab + intermediate platform at 3000 + ceiling band at the plate.
        assert_eq!(floors.len(), 3);
        // The platform is a band at the storey line, not a zero-height line.
        let platform = floors
            .iter()
            .find(|f| (f.y_top - 3000.0).abs() < 1.0)
            .expect("intermediate platform at 3000");
        assert!(platform.y_top - platform.y_bottom > 50.0, "platform has depth");
    }

    #[test]
    fn transverse_cut_through_x_zero_intersects_the_wall_at_x_zero() {
        let mut input = rectangular_input();
        // Add a wall that runs in X from (1000,2000) to (4000,2000) — its
        // X-extent covers cut_x=2500.
        input.walls.push(SectionWallInput {
            start: Vec3::new(1000.0, 0.0, 2000.0),
            end: Vec3::new(4000.0, 0.0, 2000.0),
            height: 2700.0,
            category: "interior".into(),
            base: 0.0,
        });
        let cut = SectionCut {
            name: "B-B".into(),
            cut_x: 2500.0,
            cut_z: 0.0,
            direction: CutDirection::Transverse,
            view_direction: ViewDirection::East,
        };
        let elements = generate_section_elements(&input, &cut);
        let walls: Vec<_> = elements
            .iter()
            .filter(|e| e.element_type == ElementType::Wall)
            .collect();
        // 2 Z-running walls don't hit (X-extent is a single value); 2 X-running
        // walls (at Z=0 and Z=4000) span X=[0,5000] so both hit; plus the
        // new X-running wall in the middle hits too. 3 hits.
        assert_eq!(walls.len(), 3);
        // Each wall thickness: exterior=150, interior=100.
        let interior = walls.iter().find(|w| (w.width - 100.0).abs() < 1.0);
        assert!(interior.is_some());
    }

    #[test]
    fn render_emits_well_formed_svg_with_styles_and_patterns() {
        let input = rectangular_input();
        let cut = default_cut(&input);
        let svg = generate_section_sheet_svg(&input, &cut, 0.05);
        assert!(svg.starts_with("<?xml version=\"1.0\""));
        assert!(svg.ends_with("</svg>\n"));
        assert!(svg.contains("<style>"));
        assert!(svg.contains("earth-hatch"));
        assert!(svg.contains("shingle-pattern"));
        assert!(svg.contains("SECTION A-A"));
        assert!(svg.contains("View: Looking east"));
        // The flip group is what makes positive-Y go up.
        assert!(svg.contains("scale(1, -1)"));
    }

    #[test]
    fn annotations_render_upright_outside_the_flip_group() {
        // All text/dims must be emitted AFTER the flipped geometry group
        // closes, otherwise they render upside-down.
        let input = rectangular_input();
        let cut = default_cut(&input);
        let svg = generate_section_sheet_svg(&input, &cut, 0.05);
        let close = svg.find("</g>").expect("flip group should close");
        // No <text> may appear before the group closes.
        let first_text = svg.find("<text").expect("section has text");
        assert!(
            first_text > close,
            "text at {first_text} appears before </g> at {close} — would render mirrored"
        );
        // The overall dimension value (a width in mm) is also outside.
        let dim = svg.find(" mm<").or_else(|| svg.find("mm</text>")).unwrap();
        assert!(dim > close, "dimension text must be outside the flip group");
    }

    #[test]
    fn ceiling_height_dimension_is_emitted() {
        let mut input = rectangular_input();
        input.ceiling_height_mm = 2700.0;
        let cut = default_cut(&input);
        let svg = generate_section_sheet_svg(&input, &cut, 0.05);
        assert!(svg.contains("CEILING HT."), "missing ceiling-height label");
        assert!(svg.contains("2700 mm"), "missing ceiling-height value: {svg}");
    }

    #[test]
    fn assembly_notes_block_lists_r_values() {
        let mut input = rectangular_input();
        input.assemblies = vec![
            AssemblyCallout {
                label: "EXTERIOR WALL".into(),
                spec: "2x6 @ 16\" o.c. + R-22 batt + R-5 c.i.".into(),
                r_value: 28.0,
            },
            AssemblyCallout {
                label: "ROOF / CEILING".into(),
                spec: "Vented attic, blown cellulose".into(),
                r_value: 60.0,
            },
        ];
        let cut = default_cut(&input);
        let svg = generate_section_sheet_svg(&input, &cut, 0.05);
        assert!(svg.contains("ENVELOPE ASSEMBLIES (OBC SB-12)"));
        assert!(svg.contains("EXTERIOR WALL: R-28"), "got {svg}");
        assert!(svg.contains("ROOF / CEILING: R-60"));
        // The quote in the spec must be XML-escaped, not raw.
        assert!(svg.contains("16&quot; o.c.") || svg.contains("16\" o.c."));
    }

    #[test]
    fn no_assemblies_means_no_notes_block() {
        let input = rectangular_input(); // assemblies empty
        let cut = default_cut(&input);
        let svg = generate_section_sheet_svg(&input, &cut, 0.05);
        assert!(!svg.contains("ENVELOPE ASSEMBLIES"));
    }

    #[test]
    fn default_cut_centres_on_building_width() {
        let input = SectionInput {
            width: 8000.0,
            ..Default::default()
        };
        let cut = default_cut(&input);
        assert_eq!(cut.cut_x, 4000.0);
        assert_eq!(cut.direction, CutDirection::Transverse);
        assert_eq!(cut.view_direction, ViewDirection::East);
    }
}
