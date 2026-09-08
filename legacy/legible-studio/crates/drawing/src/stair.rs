//! Stair plan symbols for floor plans (OBC 9.8 private stairs).
//!
//! Renders a stair in the standard plan convention: a run of tread (nosing)
//! lines across the stair well, a centred direction arrow, and an `UP`/`DN`
//! label. Three arrangements:
//! - `straight` — a single run of nosing lines spanning the well;
//! - `switchback` — a U: two tread columns split by a central well, joined by a
//!   half-landing, for storeys whose run is too long to fit a straight flight; and
//! - `l_shaped` — a quarter-turn: a main flight plus a short return flight at the
//!   landing, running perpendicular to the main flight.
//!
//! Geometry is built in a run-local frame (`u` along the climb, `v` across the
//! well) and mapped to plan mm with the floor plan's negated-Y convention baked
//! in, so the caller injects the fragment under a uniform scale only — the same
//! contract as the detector / room-label passes in `qbd::documentation`.

use std::fmt::Write as _;

/// One stair's plan parameters, in plan mm (`y` is Z in 3D). Mirrors
/// `archgeometry::SchemaStair`, kept separate so `drawing` needs no schema
/// dependency (the same split as [`crate::RoomLabelInput`]).
#[derive(Debug, Clone)]
pub struct StairPlan {
    /// Bay minimum-corner.
    pub x: f32,
    pub y: f32,
    /// Extent across the run (perpendicular to the climb).
    pub across: f32,
    /// Extent along the run (the climb direction).
    pub run: f32,
    /// Climb direction in plan: `"+y"`, `"-y"`, `"+x"`, `"-x"`. Empty → `"+y"`.
    pub run_dir: String,
    pub num_treads: u32,
    pub tread_run: f32,
    /// `"straight"`, `"switchback"` or `"l_shaped"`. Empty → `"straight"`.
    pub shape: String,
    /// `"up"` or `"down"`. Empty → `"up"`.
    pub going: String,
}

impl StairPlan {
    /// Map a run-local point `(u, v)` to SVG coordinates, with the floor plan's
    /// negated-Y (plan Z → `-y`) convention applied. `u` runs along the climb
    /// from the bottom of the stair; `v` runs across the well from the bay's
    /// minimum side.
    fn pt(&self, u: f32, v: f32) -> (f32, f32) {
        let (px, pz) = match self.run_dir.as_str() {
            "-y" => (self.x + v, self.y + self.run - u),
            "+x" => (self.x + u, self.y + v),
            "-x" => (self.x + self.run - u, self.y + v),
            _ => (self.x + v, self.y + u), // "+y"
        };
        (px, -pz)
    }
}

fn line(s: &mut String, a: (f32, f32), b: (f32, f32), color: &str, weight: f32) {
    let _ = writeln!(
        s,
        r#"    <line x1="{:.1}" y1="{:.1}" x2="{:.1}" y2="{:.1}" stroke="{}" stroke-width="{:.0}"/>"#,
        a.0, a.1, b.0, b.1, color, weight,
    );
}

/// Filled-triangle arrowhead at `head`, pointing from `tail` toward `head`.
fn arrowhead(s: &mut String, tail: (f32, f32), head: (f32, f32), size: f32) {
    let (dx, dy) = (head.0 - tail.0, head.1 - tail.1);
    let len = (dx * dx + dy * dy).sqrt().max(1e-3);
    let (ux, uy) = (dx / len, dy / len);
    let (px, py) = (-uy, ux); // perpendicular
    let half = size * 0.45;
    let b1 = (head.0 - ux * size + px * half, head.1 - uy * size + py * half);
    let b2 = (head.0 - ux * size - px * half, head.1 - uy * size - py * half);
    let _ = writeln!(
        s,
        r##"    <polygon points="{:.1},{:.1} {:.1},{:.1} {:.1},{:.1}" fill="#000"/>"##,
        head.0, head.1, b1.0, b1.1, b2.0, b2.1,
    );
}

/// A direction arrow along the climb at across-position `v`, from `u_tail` to
/// `u_head` (the head sits at `u_head`).
fn arrow(s: &mut String, p: &StairPlan, u_tail: f32, u_head: f32, v: f32) {
    let tail = p.pt(u_tail, v);
    let head = p.pt(u_head, v);
    line(s, tail, head, "#000", 18.0);
    arrowhead(s, tail, head, 260.0);
}

fn label(s: &mut String, at: (f32, f32), text: &str, text_height: f32) {
    let _ = writeln!(
        s,
        r##"    <text x="{:.1}" y="{:.1}" font-family="Arial, sans-serif" font-size="{:.0}" font-weight="bold" text-anchor="middle" fill="#000">{}</text>"##,
        at.0, at.1 + text_height * 0.35, text_height, text,
    );
}

/// Render a stair plan symbol as an SVG fragment in plan-mm (negated-Y) space.
#[must_use]
#[allow(clippy::cast_precision_loss)] // tread indices are small (≈15)
pub fn render_stair_symbol(p: &StairPlan, text_height: f32) -> String {
    const TREAD_COLOR: &str = "#333";
    const WELL_COLOR: &str = "#555";
    let tread = p.tread_run.max(1.0);
    let down = p.going == "down";
    let mut s = String::with_capacity(1024);

    if p.shape == "switchback" {
        // Two flights side by side, divided by a central well, joined by a
        // landing against the back wall. The well gap keeps the flights from
        // merging into one wide run.
        const WELL_HALF_GAP: f32 = 70.0;
        let half = p.across * 0.5;
        let l_far = half - WELL_HALF_GAP; // up-flight inner edge
        let r_near = half + WELL_HALF_GAP; // return-flight inner edge
        let t1 = p.num_treads.div_ceil(2); // longer flight climbs first
        let t2 = p.num_treads - t1;
        // Flights fill the run below the landing; landing spans the rest, full
        // width, against the back wall.
        let flight_len = (t1.max(t2) as f32 * tread).min(p.run);
        let landing_near = flight_len;

        // Up-flight nosings (left): v in 0..l_far.
        for i in 1..=t1 {
            let u = (i as f32 * tread).min(flight_len);
            line(&mut s, p.pt(u, 0.0), p.pt(u, l_far), TREAD_COLOR, 12.0);
        }
        // Return-flight nosings (right): v in r_near..across.
        for i in 1..=t2 {
            let u = (i as f32 * tread).min(flight_len);
            line(&mut s, p.pt(u, r_near), p.pt(u, p.across), TREAD_COLOR, 12.0);
        }
        // Central-well walls, bottom up to the landing.
        line(&mut s, p.pt(0.0, l_far), p.pt(landing_near, l_far), WELL_COLOR, 16.0);
        line(&mut s, p.pt(0.0, r_near), p.pt(landing_near, r_near), WELL_COLOR, 16.0);
        line(&mut s, p.pt(landing_near, l_far), p.pt(landing_near, r_near), WELL_COLOR, 16.0);
        // Landing front edge (full width) where the flights meet the platform.
        line(&mut s, p.pt(landing_near, 0.0), p.pt(landing_near, p.across), WELL_COLOR, 16.0);

        // Direction arrow up the first (left) flight.
        let vq = l_far * 0.5;
        if down {
            arrow(&mut s, p, landing_near, tread * 0.5, vq);
        } else {
            arrow(&mut s, p, tread * 0.5, landing_near, vq);
        }
        // Label on the landing, clear of the treads.
        let lbl = p.pt((landing_near + p.run) * 0.5, p.across * 0.5);
        label(&mut s, lbl, if down { "DN" } else { "UP" }, text_height);
    } else if p.shape == "l_shaped" {
        // Quarter-turn: main flight along the run, a short return flight at the
        // landing running perpendicular (along +v). The return is typically 3
        // treads; the main flight uses the rest.
        let return_treads = 3.min(p.num_treads.saturating_sub(1)).max(1);
        let main_treads = p.num_treads - return_treads;
        let main_len = (main_treads as f32 * tread).min(p.run);
        let return_len = (return_treads as f32 * tread).min(p.run - main_len);
        let flight_clear = (p.across - return_len).max(tread);

        // Main flight nosings, spanning the clear width.
        for i in 1..=main_treads {
            let u = (i as f32 * tread).min(main_len);
            line(&mut s, p.pt(u, 0.0), p.pt(u, flight_clear), TREAD_COLOR, 12.0);
        }
        // Landing line across the full width at the top of the main flight.
        line(&mut s, p.pt(main_len, 0.0), p.pt(main_len, p.across), WELL_COLOR, 16.0);
        // Return flight nosings perpendicular to the main flight, on the landing.
        for j in 1..=return_treads {
            let v = (flight_clear + j as f32 * tread).min(p.across);
            line(&mut s, p.pt(main_len, v), p.pt(main_len + return_len, v), TREAD_COLOR, 12.0);
        }
        // Direction arrow up the main flight.
        if down {
            arrow(&mut s, p, main_len, tread * 0.5, flight_clear * 0.5);
        } else {
            arrow(&mut s, p, tread * 0.5, main_len, flight_clear * 0.5);
        }
        let lbl = p.pt((main_len + p.run) * 0.5, p.across * 0.5);
        label(&mut s, lbl, if down { "DN" } else { "UP" }, text_height);
    } else {
        // Straight run: nosing lines spanning the full well width.
        let top = (p.num_treads as f32 * tread).min(p.run);
        for i in 1..=p.num_treads {
            let u = (i as f32 * tread).min(p.run);
            line(&mut s, p.pt(u, 0.0), p.pt(u, p.across), TREAD_COLOR, 12.0);
        }
        let vc = p.across * 0.5;
        if down {
            arrow(&mut s, p, top, tread * 0.5, vc);
        } else {
            arrow(&mut s, p, tread * 0.5, top, vc);
        }
        let lbl = p.pt(tread * 0.5, p.across * 0.5);
        label(&mut s, lbl, if down { "DN" } else { "UP" }, text_height);
    }

    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn switchback() -> StairPlan {
        StairPlan {
            x: 0.0,
            y: 0.0,
            across: 1828.8,
            run: 3352.8,
            run_dir: "+y".into(),
            num_treads: 15,
            tread_run: 255.0,
            shape: "switchback".into(),
            going: "up".into(),
        }
    }

    #[test]
    fn switchback_emits_both_columns_and_landing_and_label() {
        let svg = render_stair_symbol(&switchback(), 250.0);
        // 15 nosing lines (8 + 7) + a UP label + a direction arrow.
        assert!(svg.matches("<line").count() >= 15);
        assert!(svg.contains("UP"));
        assert!(svg.contains("<polygon"), "direction arrowhead present");
    }

    #[test]
    fn down_going_labels_dn_and_reverses_arrow() {
        let mut p = switchback();
        p.going = "down".into();
        let svg = render_stair_symbol(&p, 250.0);
        assert!(svg.contains("DN"));
        assert!(!svg.contains(">UP<"));
    }

    #[test]
    fn straight_run_draws_one_nosing_per_tread() {
        let p = StairPlan {
            run: 4000.0,
            num_treads: 12,
            shape: "straight".into(),
            ..switchback()
        };
        let svg = render_stair_symbol(&p, 250.0);
        // 12 nosing lines + 1 arrow shaft = 13 <line>s.
        assert_eq!(svg.matches("<line").count(), 13);
    }

    #[test]
    fn l_shaped_draws_main_and_return_flights() {
        let p = StairPlan {
            run: 4000.0,
            num_treads: 15,
            tread_run: 255.0,
            shape: "l_shaped".into(),
            ..switchback()
        };
        let svg = render_stair_symbol(&p, 250.0);
        // Main flight (12 treads) + return flight (3 treads) + landing line + arrow.
        assert!(svg.matches("<line").count() >= 16, "expected main + return nosings + landing");
        assert!(svg.contains("UP"));
        assert!(svg.contains("<polygon"), "direction arrowhead present");
    }

    #[test]
    fn geometry_stays_within_the_bay() {
        // Every emitted coordinate sits inside the (negated-Y) bay box.
        let p = switchback();
        let svg = render_stair_symbol(&p, 250.0);
        for tok in svg.split(['"', ' ', ',', '<', '>']) {
            if let Ok(v) = tok.parse::<f32>() {
                // X within [0, across]; Y (negated Z) within [-run, 0] (allow a
                // small margin for the label baseline + arrowhead).
                assert!(v >= -p.run - 400.0 && v <= p.across + 400.0, "coord {v} out of bay");
            }
        }
    }
}
