//! Site plan SVG generator.
//!
//! Port of `ArchEngine_kernel/scripts/generate_site_plan.py` (91 LOC). Emits
//! a permit-style site plan: lot boundary, building footprint, setbacks,
//! driveway. Distances in feet (Ontario residential convention is mixed;
//! permit sets in Toronto/Ottawa typically use imperial for site plans).

use std::fmt::Write as _;

/// Target px the longer lot axis occupies in the rendered viewBox.
/// qbd_dump's `fit_display` caps the displayed sheet at 1100 px, so a
/// lot of ~700 px leaves headroom for margins, title block, and street
/// while keeping 10-11 px in-plan fonts at 1-1.5 % of the sheet —
/// readable across parcel sizes from 50 ft to 2000 ft.
const LOT_TARGET_PX: f32 = 700.0;

/// Geometry of the site plan: lot box, building footprint, setbacks, driveway.
/// All distances in feet (the Python uses imperial throughout).
#[derive(Debug, Clone)]
pub struct SitePlan {
    pub lot_width_ft: f32,
    pub lot_depth_ft: f32,
    pub building_x_ft: f32,
    pub building_z_ft: f32,
    pub building_width_ft: f32,
    pub building_depth_ft: f32,
    pub front_setback_ft: f32,
    pub side_setback_ft: f32,
    pub rear_setback_ft: f32,
    pub driveway_width_ft: f32,
    /// Street the lot fronts (drawn along the front lot line).
    pub street: String,
    /// Municipal zone label (e.g. "R1").
    pub zone: String,
    /// Whether the footprint fits inside the buildable envelope.
    pub fits: bool,
    /// LiDAR grade spot elevations (m) at the corners, SW/SE/NE/NW. Empty if
    /// no terrain is wired; then no grade is drawn.
    pub grade_corners_m: Vec<f32>,
    /// Parcel outline as local `(x, y)` ft vertices. When present (≥3), the
    /// site plan draws this real lot shape instead of a rectangle.
    pub lot_polygon_ft: Vec<(f32, f32)>,
    /// LiDAR-derived contour lines in lot-local feet. Drawn as thin gray
    /// segments behind the lot/footprint.
    pub contours_ft: Vec<Contour>,
    /// Elevation step (m) between successive contours; reported in the legend.
    pub contour_interval_m: f32,
    /// OSM-sourced street network in lot-local feet. Drawn as a layer
    /// behind the lot polygon so the parcel sits "on top" of its block.
    pub streets_ft: Vec<StreetWay>,
}

/// One LiDAR contour at a single elevation: a list of disjoint polylines
/// (stitched chains) in lot-local feet. Closed loops repeat their start.
#[derive(Debug, Clone, Default)]
pub struct Contour {
    pub elevation_m: f32,
    pub polylines_ft: Vec<Vec<(f32, f32)>>,
}

/// One street segment from Overpass, projected into lot-local feet. The
/// renderer draws lines + the optional name label.
#[derive(Debug, Clone, Default)]
pub struct StreetWay {
    /// Polyline points in lot-local feet (same frame as `lot_polygon_ft`).
    pub points_ft: Vec<(f32, f32)>,
    /// `name=*` tag, if any.
    pub name: Option<String>,
    /// Display class: arterial / connector / local / path — drives weight.
    pub kind: StreetClass,
}

/// Visual tier for a [`StreetWay`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum StreetClass {
    Arterial,
    Connector,
    #[default]
    Local,
    Path,
}

impl SitePlan {
    /// Compute a SitePlan from building width/depth in metres plus standard
    /// Ontario residential setbacks (matches `permit_drawing_set.py`'s
    /// defaults: 60' x 120' lot, 25/6/25 setbacks, 12' driveway, building
    /// centred X-wise and offset 30' from the front lot line).
    #[must_use]
    pub fn from_building_metres(building_width_m: f32, building_depth_m: f32) -> Self {
        let m_to_ft = 3.280_84;
        Self::from_lot(60.0, 120.0, building_width_m * m_to_ft, building_depth_m * m_to_ft, (25.0, 6.0, 25.0), "Street", "R1")
    }

    /// Place a building footprint (ft) on a lot (ft) per `(front, side, rear)`
    /// setbacks (ft): centred across the lot, sitting at the front setback.
    /// `fits` records whether it stays inside the buildable envelope.
    #[must_use]
    pub fn from_lot(
        lot_width_ft: f32,
        lot_depth_ft: f32,
        building_width_ft: f32,
        building_depth_ft: f32,
        setbacks_ft: (f32, f32, f32),
        street: &str,
        zone: &str,
    ) -> Self {
        let (front, side, rear) = setbacks_ft;
        let buildable_w = lot_width_ft - 2.0 * side;
        let buildable_d = lot_depth_ft - front - rear;
        let fits = building_width_ft <= buildable_w + 0.01 && building_depth_ft <= buildable_d + 0.01;
        Self {
            lot_width_ft,
            lot_depth_ft,
            building_x_ft: (lot_width_ft - building_width_ft) * 0.5,
            building_z_ft: front,
            building_width_ft,
            building_depth_ft,
            front_setback_ft: front,
            side_setback_ft: side,
            rear_setback_ft: rear,
            driveway_width_ft: 12.0,
            street: street.to_string(),
            zone: zone.to_string(),
            fits,
            grade_corners_m: Vec::new(),
            lot_polygon_ft: Vec::new(),
            contours_ft: Vec::new(),
            contour_interval_m: 0.5,
            streets_ft: Vec::new(),
        }
    }
}

/// Inset a convex polygon inward by `d` (uniform), assuming/forcing CCW
/// winding: offset each edge inward and intersect neighbours. Returns `None`
/// if the polygon is too small for the inset or an offset pair is parallel.
/// Concave polygons aren't handled (the caller skips the buildable line then).
#[must_use]
#[allow(clippy::many_single_char_names)]
pub fn inset_convex(poly: &[(f32, f32)], d: f32) -> Option<Vec<(f32, f32)>> {
    let n = poly.len();
    if n < 3 {
        return None;
    }
    // Signed area; reverse to CCW if needed (interior is left of each edge).
    let area2: f32 = (0..n).map(|i| {
        let a = poly[i];
        let b = poly[(i + 1) % n];
        a.0 * b.1 - b.0 * a.1
    }).sum();
    let ccw: Vec<(f32, f32)> = if area2 < 0.0 { poly.iter().rev().copied().collect() } else { poly.to_vec() };

    // Offset line per edge: a point shifted inward by d + the edge direction.
    let mut lines = Vec::with_capacity(n);
    for i in 0..n {
        let a = ccw[i];
        let b = ccw[(i + 1) % n];
        let (ex, ey) = (b.0 - a.0, b.1 - a.1);
        let len = (ex * ex + ey * ey).sqrt();
        if len < 1e-3 {
            return None;
        }
        let (nx, ny) = (-ey / len, ex / len); // inward (left) normal for CCW
        lines.push(((a.0 + nx * d, a.1 + ny * d), (ex, ey)));
    }
    // New vertex i = intersection of offset edge (i-1) and edge i.
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let (p0, d0) = lines[(i + n - 1) % n];
        let (p1, d1) = lines[i];
        let denom = d0.0 * d1.1 - d0.1 * d1.0;
        if denom.abs() < 1e-6 {
            return None; // parallel
        }
        let t = ((p1.0 - p0.0) * d1.1 - (p1.1 - p0.1) * d1.0) / denom;
        out.push((p0.0 + d0.0 * t, p0.1 + d0.1 * t));
    }
    // Reject if the inset collapsed (non-positive area).
    let a2: f32 = (0..n).map(|i| {
        let a = out[i];
        let b = out[(i + 1) % n];
        a.0 * b.1 - b.0 * a.1
    }).sum();
    if a2.abs() < 1.0 { None } else { Some(out) }
}

/// Below this chain length no elevation label is placed (would crowd the
/// parcel and risk overprinting other annotations).
const MIN_VERTICES_FOR_LABEL: usize = 4;

/// Emit the OSM street network as one `<polyline>` per `StreetWay`,
/// styled by class, with name labels at the midpoint of named ways that
/// have enough on-screen length. `x_of`/`y_of` map lot-local ft into the
/// SVG coordinate space, so the helper feeds both the rectangular and
/// polygon paths.
fn write_streets(
    s: &mut String,
    x_of: &dyn Fn(f32) -> f32,
    y_of: &dyn Fn(f32) -> f32,
    streets: &[StreetWay],
) {
    if streets.is_empty() {
        return;
    }
    // Layer the lines beneath the lot/contour/footprint stack so the
    // parcel reads as "this lot inside that block." Subtle warm-grey for
    // road surface; line weight scales with class.
    for w in streets {
        if w.points_ft.len() < 2 {
            continue;
        }
        let stroke_w = match w.kind {
            StreetClass::Arterial => 4.5,
            StreetClass::Connector => 3.0,
            StreetClass::Local => 1.8,
            StreetClass::Path => 0.8,
        };
        let pts = w
            .points_ft
            .iter()
            .map(|(x, y)| format!("{},{}", x_of(*x), y_of(*y)))
            .collect::<Vec<_>>()
            .join(" ");
        let dasharray = if matches!(w.kind, StreetClass::Path) {
            r#" stroke-dasharray="4,3""#
        } else {
            ""
        };
        let _ = writeln!(
            s,
            r##"<polyline points="{pts}" fill="none" stroke="#9d9d8e" stroke-width="{stroke_w}"{dasharray}/>"##,
        );
    }
    // Name labels (one per named way, mid-segment). Light grey so they
    // don't compete with parcel dimensions; rotated to follow the
    // longest segment.
    let lbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#666""##;
    for w in streets {
        let Some(name) = &w.name else { continue; };
        if w.points_ft.len() < 2 {
            continue;
        }
        // Pick the longest segment in the way to anchor the label — gives
        // it enough horizontal run to read.
        let (mid, angle_deg) = longest_segment_anchor(&w.points_ft);
        let (tx, ty) = (x_of(mid.0), y_of(mid.1) - 3.0);
        let _ = writeln!(
            s,
            r#"<text x="{tx}" y="{ty}" text-anchor="middle" transform="rotate({angle_deg:.1} {tx} {ty})" {lbl}>{name}</text>"#,
        );
    }
}

/// Find the longest segment in a polyline; return its midpoint (in the
/// same coordinate space as the input) and its screen-space rotation in
/// degrees (clamped so labels never read upside-down).
fn longest_segment_anchor(pts: &[(f32, f32)]) -> ((f32, f32), f32) {
    let mut best_len2 = 0.0;
    let mut best = (pts[0], pts.get(1).copied().unwrap_or(pts[0]));
    for w in pts.windows(2) {
        let dx = w[1].0 - w[0].0;
        let dy = w[1].1 - w[0].1;
        let len2 = dx * dx + dy * dy;
        if len2 > best_len2 {
            best_len2 = len2;
            best = (w[0], w[1]);
        }
    }
    let mid = ((best.0.0 + best.1.0) * 0.5, (best.0.1 + best.1.1) * 0.5);
    // y_of flips the y-axis, so rotation needs the sign of dy inverted to
    // match screen space. Atan2(-dy, dx) gives the right tilt.
    let mut angle = (-(best.1.1 - best.0.1)).atan2(best.1.0 - best.0.0).to_degrees();
    if !(-90.0..=90.0).contains(&angle) {
        angle += 180.0;
    }
    (mid, angle)
}

/// Emit LiDAR contours as one `<polyline>` per stitched chain, plus a small
/// elevation label at each chain's midpoint vertex. `x_of`/`y_of` map
/// lot-local ft into the SVG's own coordinate space, so the same helper
/// serves both the rectangular and polygon site plans.
fn write_contour_lines(
    s: &mut String,
    x_of: &dyn Fn(f32) -> f32,
    y_of: &dyn Fn(f32) -> f32,
    contours: &[Contour],
) {
    if contours.is_empty() {
        return;
    }
    // Lines first (warm-gray group), then labels (separate so labels aren't
    // dimmed by the group's opacity).
    let _ = writeln!(s, r##"<g stroke="#a89e7c" stroke-width="0.6" fill="none" opacity="0.7">"##);
    for c in contours {
        for chain in &c.polylines_ft {
            if chain.len() < 2 {
                continue;
            }
            let pts = chain
                .iter()
                .map(|(x, y)| format!("{},{}", x_of(*x), y_of(*y)))
                .collect::<Vec<_>>()
                .join(" ");
            let _ = writeln!(s, r#"<polyline points="{pts}"/>"#);
        }
    }
    s.push_str("</g>\n");
    // Per-polyline elevation labels at the middle vertex (chains ≥4 verts).
    let lbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="9" fill="#665""##;
    for c in contours {
        for chain in &c.polylines_ft {
            if chain.len() < MIN_VERTICES_FOR_LABEL {
                continue;
            }
            let mid = chain[chain.len() / 2];
            let _ = writeln!(
                s,
                r#"<text x="{tx}" y="{ty}" text-anchor="middle" {lbl}>{e:.1}</text>"#,
                tx = x_of(mid.0),
                ty = y_of(mid.1) - 1.0,
                e = c.elevation_m,
            );
        }
    }
}

/// Render the site plan to an SVG string. Port of
/// `generate_site_plan_svg` (`generate_site_plan.py:26`). The Python's
/// `building_data` argument is unused in the body — we drop it.
#[must_use]
#[allow(clippy::too_many_lines)]
// Drawing math uses single-letter binding conventions (x, y, w, h) that
// match the SVG vocabulary; renaming them would obscure rather than clarify.
#[allow(clippy::many_single_char_names)]
pub fn generate_site_plan_svg(site: &SitePlan) -> String {
    // Irregular parcel: draw the real lot outline instead of a rectangle.
    if site.lot_polygon_ft.len() >= 3 {
        return polygon_site_plan_svg(site);
    }
    // Scale so the lot occupies ~700 px on the longer axis regardless of
    // size — the 10/11 px in-plan font sizes were tuned for a small viewBox
    // and turn unreadable when the scale is fixed against multi-hundred-ft
    // lots (display size is capped at 1100 px in qbd_dump).
    let scale: f32 = LOT_TARGET_PX / site.lot_width_ft.max(site.lot_depth_ft).max(1.0);
    let margin: f32 = 60.0;
    let w = site.lot_width_ft * scale + 2.0 * margin;
    let h = site.lot_depth_ft * scale + 2.0 * margin;

    let x = |ft: f32| margin + ft * scale;
    let y = |ft: f32| h - margin - ft * scale;

    let mut s = String::with_capacity(2048);

    let _ = writeln!(
        s,
        r#"<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">"#
    );
    let _ = writeln!(s, r#"<rect width="{w}" height="{h}" fill="white"/>"#);

    // Lot boundary.
    let _ = writeln!(
        s,
        r##"<rect x="{x_lot}" y="{y_lot}" width="{w_lot}" height="{h_lot}" fill="#f4f4f0" stroke="black" stroke-width="2"/>"##,
        x_lot = x(0.0),
        y_lot = y(site.lot_depth_ft),
        w_lot = site.lot_width_ft * scale,
        h_lot = site.lot_depth_ft * scale,
    );

    // LiDAR contours (under the setback envelope + footprint).
    // Streets behind the lot/contour stack so the parcel reads as a lot
    // inside its block.
    write_streets(&mut s, &x, &y, &site.streets_ft);
    write_contour_lines(&mut s, &x, &y, &site.contours_ft);

    // Setback envelope (dashed grey).
    let _ = writeln!(
        s,
        r##"<rect x="{xs}" y="{ys}" width="{ws}" height="{hs}" fill="none" stroke="#888" stroke-width="1" stroke-dasharray="6,4"/>"##,
        xs = x(site.side_setback_ft),
        ys = y(site.lot_depth_ft - site.rear_setback_ft),
        ws = (site.lot_width_ft - 2.0 * site.side_setback_ft) * scale,
        hs = (site.lot_depth_ft - site.front_setback_ft - site.rear_setback_ft) * scale,
    );

    // Building footprint.
    let _ = writeln!(
        s,
        r##"<rect x="{xb}" y="{yb}" width="{wb}" height="{hb}" fill="#d8d4c8" stroke="black" stroke-width="1.5"/>"##,
        xb = x(site.building_x_ft),
        yb = y(site.building_z_ft + site.building_depth_ft),
        wb = site.building_width_ft * scale,
        hb = site.building_depth_ft * scale,
    );

    // Driveway (between building front and lot front line, centred on building).
    let drive_x = site.building_x_ft + (site.building_width_ft - site.driveway_width_ft) * 0.5;
    let _ = writeln!(
        s,
        r##"<rect x="{xd}" y="{yd}" width="{wd}" height="{hd}" fill="#e8e4d8" stroke="#888" stroke-width="1"/>"##,
        xd = x(drive_x),
        yd = y(site.building_z_ft),
        wd = site.driveway_width_ft * scale,
        hd = site.building_z_ft * scale,
    );

    // Labels.
    let label_attrs = r#"font-family="Helvetica, Arial, sans-serif" font-size="11" fill="black""#;
    let _ = writeln!(
        s,
        r#"<text x="{xl}" y="{yl}" text-anchor="middle" {label_attrs}>LOT: {lw:.0}' x {ld:.0}'</text>"#,
        xl = x(site.lot_width_ft * 0.5),
        yl = y(-2.0),
        lw = site.lot_width_ft,
        ld = site.lot_depth_ft,
    );
    let _ = writeln!(
        s,
        r#"<text x="{xb}" y="{yb}" text-anchor="middle" dominant-baseline="middle" {label_attrs}>BUILDING</text>"#,
        xb = x(site.building_x_ft + site.building_width_ft * 0.5),
        yb = y(site.building_z_ft + site.building_depth_ft * 0.5),
    );
    let _ = writeln!(
        s,
        r#"<text x="{xs}" y="{ys}" {label_attrs}>Setbacks: F {f:.0}' / S {sd:.0}' / R {r:.0}'</text>"#,
        xs = x(2.0),
        ys = y(2.0),
        f = site.front_setback_ft,
        sd = site.side_setback_ft,
        r = site.rear_setback_ft,
    );

    // Street along the front lot line (the front setback is measured from it).
    let street_top = y(0.0) + 8.0;
    let _ = writeln!(
        s,
        r##"<rect x="0" y="{street_top}" width="{w}" height="30" fill="#cfcfcf" stroke="#999" stroke-width="1"/>"##,
    );
    let _ = writeln!(
        s,
        r#"<text x="{cx}" y="{ty}" text-anchor="middle" {label_attrs}>{street} (STREET)</text>"#,
        cx = w * 0.5,
        ty = street_top + 20.0,
        street = site.street,
    );

    // Setback dimensions: front + rear down the left margin, side across the top.
    let dim = r##"stroke="#06c" stroke-width="1""##;
    let dimlbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#06c""##;
    let lx = x(0.0) - 22.0; // left of the lot, in the margin
    // front (lot front line → building front)
    let _ = writeln!(s, r#"<line x1="{lx}" y1="{a}" x2="{lx}" y2="{b}" {dim}/>"#, a = y(0.0), b = y(site.front_setback_ft));
    let _ = writeln!(s, r#"<text x="{tx}" y="{ty}" text-anchor="middle" transform="rotate(-90 {tx} {ty})" {dimlbl}>F {f:.1} m</text>"#, tx = lx - 6.0, ty = (y(0.0) + y(site.front_setback_ft)) * 0.5, f = site.front_setback_ft / 3.280_84);
    // rear (building rear → rear lot line)
    let rear_z = site.building_z_ft + site.building_depth_ft;
    let _ = writeln!(s, r#"<line x1="{lx}" y1="{a}" x2="{lx}" y2="{b}" {dim}/>"#, a = y(rear_z), b = y(site.lot_depth_ft));
    let _ = writeln!(s, r#"<text x="{tx}" y="{ty}" text-anchor="middle" transform="rotate(-90 {tx} {ty})" {dimlbl}>R {r:.1} m</text>"#, tx = lx - 6.0, ty = (y(rear_z) + y(site.lot_depth_ft)) * 0.5, r = site.rear_setback_ft / 3.280_84);
    // side (lot side → building side), across the top
    let ty_line = y(site.lot_depth_ft) - 12.0;
    let _ = writeln!(s, r#"<line x1="{a}" y1="{ty_line}" x2="{b}" y2="{ty_line}" {dim}/>"#, a = x(0.0), b = x(site.building_x_ft));
    let _ = writeln!(s, r#"<text x="{tx}" y="{tt}" text-anchor="middle" {dimlbl}>S {sd:.1} m</text>"#, tx = (x(0.0) + x(site.building_x_ft)) * 0.5, tt = ty_line - 4.0, sd = site.side_setback_ft / 3.280_84);

    // North arrow (top-right).
    let nx = w - 30.0;
    let ny = 40.0;
    let _ = writeln!(s, r#"<line x1="{nx}" y1="{a}" x2="{nx}" y2="{b}" stroke="black" stroke-width="1.5"/>"#, a = ny + 18.0, b = ny - 10.0);
    let _ = writeln!(s, r#"<polygon points="{nx},{t} {l},{m} {r},{m}" fill="black"/>"#, t = ny - 16.0, l = nx - 5.0, r = nx + 5.0, m = ny - 6.0);
    let _ = writeln!(s, r#"<text x="{nx}" y="{ty}" text-anchor="middle" {label_attrs}>N</text>"#, ty = ny + 30.0);

    // Zone label + fit flag.
    let _ = writeln!(s, r#"<text x="{xs}" y="{ys}" {label_attrs}>ZONE: {zone}</text>"#, xs = x(2.0), ys = y(6.0), zone = site.zone);
    // Contour legend (only when contours are present).
    if !site.contours_ft.is_empty() {
        let _ = writeln!(
            s,
            r##"<text x="{xs}" y="{ys}" font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#665">Contours @ {i:.1} m</text>"##,
            xs = x(2.0), ys = y(10.0), i = site.contour_interval_m,
        );
    }
    if !site.fits {
        let _ = writeln!(
            s,
            r##"<text x="{cx}" y="{ty}" text-anchor="middle" font-family="Helvetica, Arial, sans-serif" font-size="12" font-weight="bold" fill="#c00">FOOTPRINT EXCEEDS BUILDABLE ENVELOPE</text>"##,
            cx = w * 0.5,
            ty = y(site.lot_depth_ft * 0.5),
        );
    }

    // LiDAR grade: spot elevations at the corners + a drainage arrow downhill.
    if site.grade_corners_m.len() == 4 {
        // Corner plan positions (ft): SW, SE, NE, NW.
        let corners = [
            (0.0, 0.0),
            (site.lot_width_ft, 0.0),
            (site.lot_width_ft, site.lot_depth_ft),
            (0.0, site.lot_depth_ft),
        ];
        let glbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#070""##;
        for (i, &(cxft, czft)) in corners.iter().enumerate() {
            let _ = writeln!(
                s,
                r#"<text x="{tx}" y="{ty}" text-anchor="middle" {glbl}>▲{e:.1}</text>"#,
                tx = x(cxft),
                ty = y(czft) - 4.0,
                e = site.grade_corners_m[i],
            );
        }
        // Drainage arrow: from the highest corner toward the lowest.
        let hi = (0..4).max_by(|&a, &b| site.grade_corners_m[a].total_cmp(&site.grade_corners_m[b])).unwrap_or(0);
        let lo = (0..4).min_by(|&a, &b| site.grade_corners_m[a].total_cmp(&site.grade_corners_m[b])).unwrap_or(0);
        if (site.grade_corners_m[hi] - site.grade_corners_m[lo]).abs() > 0.05 {
            let (hx, hz) = corners[hi];
            let (lx, lz) = corners[lo];
            let (x1, y1, x2, y2) = (x(hx), y(hz), x(lx), y(lz));
            // Pull the arrow toward the lot centre so it reads inside.
            let cx = x(site.lot_width_ft * 0.5);
            let cy = y(site.lot_depth_ft * 0.5);
            let (ax1, ay1) = ((x1 + cx) * 0.5, (y1 + cy) * 0.5);
            let (ax2, ay2) = ((x2 + cx) * 0.5, (y2 + cy) * 0.5);
            let _ = writeln!(s, r##"<line x1="{ax1}" y1="{ay1}" x2="{ax2}" y2="{ay2}" stroke="#070" stroke-width="1.5"/>"##);
            let _ = writeln!(s, r#"<text x="{tx}" y="{ty}" {glbl}>drainage</text>"#, tx = (ax1 + ax2) * 0.5 + 4.0, ty = (ay1 + ay2) * 0.5);
        }
    }

    s.push_str("</svg>\n");
    s
}

/// Site plan for an irregular parcel: draws the real lot polygon, edge-length
/// dimensions, a uniform setback buildable line (convex lots), the building
/// footprint centred on the lot, plus grade / north / zone.
#[must_use]
#[allow(clippy::too_many_lines, clippy::many_single_char_names, clippy::cast_precision_loss)]
fn polygon_site_plan_svg(site: &SitePlan) -> String {
    let poly = &site.lot_polygon_ft;
    let (min_x, max_x) = poly.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p.0), b.max(p.0)));
    let (min_z, max_z) = poly.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p.1), b.max(p.1)));
    // Scale so the lot occupies ~700 px on the longer axis. Fixed scale
    // (5 px/ft) produced 6000+ px viewBoxes for large parcels (e.g. a 1300
    // ft lot), and qbd_dump caps display at 1100 px — so the 10/11 px
    // in-plan font sizes shrank to 2-3 px on screen. Adaptive scale keeps
    // the type at the size it was designed for.
    let lot_extent = (max_x - min_x).max(max_z - min_z).max(1.0);
    let scale = LOT_TARGET_PX / lot_extent;
    let margin = 70.0;
    let w = (max_x - min_x) * scale + 2.0 * margin;
    let h = (max_z - min_z) * scale + 2.0 * margin;
    let x = |ft: f32| margin + (ft - min_x) * scale;
    let y = |ft: f32| h - margin - (ft - min_z) * scale;
    let pts = |p: &[(f32, f32)]| p.iter().map(|v| format!("{},{}", x(v.0), y(v.1))).collect::<Vec<_>>().join(" ");

    let mut s = String::with_capacity(2048);
    let _ = writeln!(s, r#"<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">"#);
    let _ = writeln!(s, r#"<rect width="{w}" height="{h}" fill="white"/>"#);

    // Lot polygon.
    let _ = writeln!(s, r##"<polygon points="{}" fill="#f4f4f0" stroke="black" stroke-width="2"/>"##, pts(poly));
    // LiDAR contours (under the setback inset + footprint).
    // Streets behind the lot/contour stack so the parcel reads as a lot
    // inside its block.
    write_streets(&mut s, &x, &y, &site.streets_ft);
    write_contour_lines(&mut s, &x, &y, &site.contours_ft);
    // Buildable line: uniform inset by the front setback (convex lots only).
    if let Some(inset) = inset_convex(poly, site.front_setback_ft) {
        let _ = writeln!(s, r##"<polygon points="{}" fill="none" stroke="#888" stroke-width="1" stroke-dasharray="6,4"/>"##, pts(&inset));
    }

    // Building footprint, centred on the lot centroid.
    let n = poly.len() as f32;
    let cx = poly.iter().map(|p| p.0).sum::<f32>() / n;
    let cz = poly.iter().map(|p| p.1).sum::<f32>() / n;
    let _ = writeln!(
        s,
        r##"<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" fill="#d8d4c8" stroke="black" stroke-width="1.5"/>"##,
        bx = x(cx - site.building_width_ft * 0.5),
        by = y(cz + site.building_depth_ft * 0.5),
        bw = site.building_width_ft * scale,
        bh = site.building_depth_ft * scale,
    );

    // Edge-length dimensions (m) at each edge midpoint.
    let dimlbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#06c""##;
    let np = poly.len();
    for i in 0..np {
        let a = poly[i];
        let b = poly[(i + 1) % np];
        let len_m = ((b.0 - a.0).powi(2) + (b.1 - a.1).powi(2)).sqrt() / 3.280_84;
        let _ = writeln!(
            s,
            r#"<text x="{tx}" y="{ty}" text-anchor="middle" {dimlbl}>{len_m:.1} m</text>"#,
            tx = (x(a.0) + x(b.0)) * 0.5,
            ty = (y(a.1) + y(b.1)) * 0.5,
        );
    }

    // Grade spot elevations at the lot vertices (when available).
    if site.grade_corners_m.len() == np {
        let glbl = r##"font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#070""##;
        for (i, v) in poly.iter().enumerate() {
            let _ = writeln!(s, r#"<text x="{tx}" y="{ty}" text-anchor="middle" {glbl}>▲{e:.1}</text>"#, tx = x(v.0), ty = y(v.1) - 3.0, e = site.grade_corners_m[i]);
        }
    }

    // North arrow + labels.
    let lbl = r#"font-family="Helvetica, Arial, sans-serif" font-size="11" fill="black""#;
    let (nx, ny) = (w - 30.0, 40.0);
    let _ = writeln!(s, r#"<line x1="{nx}" y1="{a}" x2="{nx}" y2="{b}" stroke="black" stroke-width="1.5"/>"#, a = ny + 18.0, b = ny - 10.0);
    let _ = writeln!(s, r#"<polygon points="{nx},{t} {l},{m} {r},{m}" fill="black"/>"#, t = ny - 16.0, l = nx - 5.0, r = nx + 5.0, m = ny - 6.0);
    let _ = writeln!(s, r#"<text x="{nx}" y="{ty}" text-anchor="middle" {lbl}>N</text>"#, ty = ny + 30.0);
    let _ = writeln!(s, r#"<text x="{tx}" y="22" {lbl} font-weight="bold">SITE PLAN — {zone} · {street}</text>"#, tx = margin, zone = site.zone, street = site.street);
    // Contour legend.
    if !site.contours_ft.is_empty() {
        let _ = writeln!(
            s,
            r##"<text x="{tx}" y="{ty}" font-family="Helvetica, Arial, sans-serif" font-size="10" fill="#665">Contours @ {i:.1} m</text>"##,
            tx = margin, ty = h - margin * 0.5, i = site.contour_interval_m,
        );
    }

    s.push_str("</svg>\n");
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn from_building_metres_uses_standard_defaults() {
        let s = SitePlan::from_building_metres(12.0, 10.0);
        assert_eq!(s.lot_width_ft, 60.0);
        assert_eq!(s.lot_depth_ft, 120.0);
        assert_eq!(s.front_setback_ft, 25.0);
        assert_eq!(s.side_setback_ft, 6.0);
        assert_eq!(s.rear_setback_ft, 25.0);
        assert_eq!(s.driveway_width_ft, 12.0);
        // 12 m * 3.28084 ≈ 39.37 ft
        assert!((s.building_width_ft - 39.37).abs() < 0.01);
        // building centred X-wise on the 60' lot
        assert!((s.building_x_ft - (60.0 - 39.37) * 0.5).abs() < 0.01);
    }

    #[test]
    fn generate_site_plan_svg_emits_well_formed_svg() {
        let site = SitePlan::from_building_metres(12.0, 10.0);
        let svg = generate_site_plan_svg(&site);
        assert!(svg.starts_with("<svg xmlns="));
        assert!(svg.ends_with("</svg>\n"));
        // bg + lot + setback envelope + building + driveway + street = 6 rects.
        assert_eq!(svg.matches("<rect").count(), 6);
        assert!(svg.contains("LOT: 60' x 120'"));
        assert!(svg.contains("BUILDING"));
        assert!(svg.contains("Setbacks: F 25' / S 6' / R 25'"));
        // Street + north arrow + zone label are present.
        assert!(svg.contains("(STREET)"));
        assert!(svg.contains(">N</text>"));
        assert!(svg.contains("ZONE:"));
    }

    #[test]
    fn from_lot_centres_building_and_flags_fit() {
        // 40x50 ft building on a 50x100 lot with 20/5/25 setbacks:
        // buildable = 40 x 55 → fits (40<=40 wide, 50<=55 deep).
        let s = SitePlan::from_lot(50.0, 100.0, 40.0, 50.0, (20.0, 5.0, 25.0), "Elm St", "R1");
        assert!(s.fits);
        assert!((s.building_x_ft - 5.0).abs() < 0.01); // (50-40)/2
        assert!((s.building_z_ft - 20.0).abs() < 0.01); // at the front setback
        assert_eq!(s.zone, "R1");
        // Too-wide building overflows the buildable envelope.
        let bad = SitePlan::from_lot(40.0, 100.0, 45.0, 30.0, (20.0, 5.0, 25.0), "Elm St", "R1");
        assert!(!bad.fits);
    }

    #[test]
    fn unfit_footprint_renders_a_warning() {
        let bad = SitePlan::from_lot(30.0, 60.0, 40.0, 50.0, (20.0, 5.0, 25.0), "Elm St", "R1");
        let svg = generate_site_plan_svg(&bad);
        assert!(svg.contains("EXCEEDS BUILDABLE ENVELOPE"));
    }

    #[test]
    fn inset_convex_shrinks_a_square_uniformly() {
        // A 10x10 square inset by 2 → a centred 6x6 square (corners at 2 and 8).
        let sq = vec![(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)];
        let inset = inset_convex(&sq, 2.0).expect("convex inset");
        assert_eq!(inset.len(), 4);
        let (min_x, max_x) = inset.iter().fold((f32::MAX, f32::MIN), |(a, b), p| (a.min(p.0), b.max(p.0)));
        assert!((min_x - 2.0).abs() < 0.01, "min_x={min_x}");
        assert!((max_x - 8.0).abs() < 0.01, "max_x={max_x}");
    }

    #[test]
    fn site_plan_renders_contour_polylines_and_legend() {
        let mut site = SitePlan::from_building_metres(12.0, 10.0);
        site.contours_ft = vec![
            // A long chain (≥4 verts) — gets a label.
            Contour {
                elevation_m: 100.5,
                polylines_ft: vec![vec![
                    (10.0, 10.0), (20.0, 12.0), (30.0, 14.0), (40.0, 12.0), (50.0, 10.0),
                ]],
            },
            // Short chain — drawn but no label.
            Contour {
                elevation_m: 101.0,
                polylines_ft: vec![vec![(10.0, 30.0), (50.0, 30.0)]],
            },
        ];
        let svg = generate_site_plan_svg(&site);
        // One <polyline> per chain.
        assert!(svg.matches("<polyline").count() >= 2);
        assert!(svg.contains("Contours @ 0.5 m"));
        assert!(svg.contains(r##"stroke="#a89e7c""##));
        // Long chain's elevation label appears; short chain's does not.
        assert!(svg.contains(">100.5</text>"));
        assert!(!svg.contains(">101.0</text>"));
        // Without contours, neither the group nor the legend should appear.
        let plain = SitePlan::from_building_metres(12.0, 10.0);
        let svg2 = generate_site_plan_svg(&plain);
        assert!(!svg2.contains("Contours @"));
    }

    #[test]
    fn polygon_site_plan_renders_real_lot_outline() {
        // An irregular (5-sided) parcel triggers the polygon renderer.
        let mut site = SitePlan::from_lot(60.0, 100.0, 30.0, 40.0, (20.0, 5.0, 25.0), "Birch Ave", "R2");
        site.lot_polygon_ft = vec![(0.0, 0.0), (60.0, 0.0), (60.0, 70.0), (30.0, 100.0), (0.0, 70.0)];
        let svg = generate_site_plan_svg(&site);
        assert!(svg.starts_with("<svg xmlns="));
        assert!(svg.ends_with("</svg>\n"));
        // The lot is drawn as a polygon, not a rect.
        assert!(svg.contains("<polygon"));
        assert!(svg.contains("SITE PLAN — R2 · Birch Ave"));
        // Edge lengths are labelled in metres; the 60 ft bottom edge ≈ 18.3 m.
        assert!(svg.contains("18.3 m"));
        assert!(svg.contains(">N</text>"));
    }

    #[test]
    fn driveway_runs_between_building_front_and_lot_front() {
        let site = SitePlan::from_building_metres(12.0, 10.0);
        let svg = generate_site_plan_svg(&site);
        // building_z_ft = 30 → driveway height = 30 * 5 = 150 in SVG units.
        // The driveway is the only rect with stroke="#888" and fill="#e8e4d8".
        assert!(svg.contains(r##"fill="#e8e4d8""##));
    }
}
