//! Straight-skeleton for simple rectilinear (axis-aligned) polygons.
//!
//! Given a CCW polygon whose edges are all axis-aligned and whose corners
//! are 90° (convex) or 270° (reflex), `rectilinear_straight_skeleton`
//! returns the skeleton arcs: line segments that, taken together with the
//! polygon boundary, decompose the polygon into roof facets. Each skeleton
//! arc is `(a, b)` in polygon coordinates plus a classification:
//!
//! - `Hip` — from a convex polygon corner inward to a skeleton node.
//! - `Valley` — from a reflex polygon corner inward to a skeleton node.
//! - `Ridge` — between two skeleton nodes (top of the roof).
//!
//! Algorithm: standard wavefront with two event kinds.
//!
//! 1. Each polygon edge moves inward at unit speed along its inward normal.
//! 2. Each polygon vertex moves along its angle bisector; for axis-aligned
//!    polygons every velocity is one of `(±1, ±1)` (a 45° vector).
//! 3. **Edge events** collapse adjacent vertex pairs into one new vertex.
//! 4. **Split events** fire when a reflex vertex's trajectory crosses a
//!    non-adjacent edge's offset line — the polygon splits along that line.
//!
//! The implementation prioritises clarity over raw speed: O(n²) per iteration
//! is fine for the few-vertex polygons in residential footprints.

use std::fmt::Write as _;

/// One skeleton arc with its visual role.
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct SkeletonArc {
    pub a: (f32, f32),
    pub b: (f32, f32),
    pub kind: ArcKind,
}

/// What this arc represents on the roof plan.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ArcKind {
    /// Convex-corner inward line (visible from outside as a hip).
    Hip,
    /// Reflex-corner inward line (interior valley between two roof planes).
    Valley,
    /// Between two interior skeleton nodes (top of the roof).
    Ridge,
}

/// Compute the straight skeleton of a rectilinear CCW polygon. Returns the
/// arcs; the caller renders or projects them as needed.
#[must_use]
#[allow(
    clippy::many_single_char_names,
    clippy::too_many_lines,
    clippy::cast_precision_loss,
)]
pub fn rectilinear_straight_skeleton(polygon: &[(f32, f32)]) -> Vec<SkeletonArc> {
    if polygon.len() < 4 {
        return Vec::new();
    }

    let mut verts: Vec<WV> = init_vertices(polygon);
    let mut arcs: Vec<SkeletonArc> = Vec::new();
    let mut t = 0.0_f32;
    let mut guard = 0usize;
    let max_iters = 64 * polygon.len();

    while alive_count(&verts) >= 3 && guard < max_iters {
        guard += 1;
        // Drain any zero-length edges that were created by an earlier event
        // (simultaneous edge collapses at the same time produce these — the
        // collapse-time root-finder can't see them because the length is
        // already zero, so handle them inline at the current time).
        if let Some((i, j)) = find_zero_length_edge(&verts, t) {
            process_edge_event(&mut verts, &mut arcs, i, j, t);
            continue;
        }
        let Some(ev) = next_event(&verts, t) else { break; };
        t = ev.time;
        match ev.kind {
            EventKind::Edge { i, j } => process_edge_event(&mut verts, &mut arcs, i, j, t),
            EventKind::Split { r, e_i, e_j } => process_split_event(&mut verts, &mut arcs, r, e_i, e_j, t),
        }
    }

    // Any remaining live vertices die together at the end — emit a final arc
    // from each to its death position (the wavefront's final collapse).
    let live: Vec<usize> = (0..verts.len()).filter(|&i| verts[i].alive).collect();
    if live.len() >= 2 {
        // Average the live positions at t as the meeting point.
        let mut cx = 0.0;
        let mut cy = 0.0;
        for &i in &live {
            let p = verts[i].pos_at(t);
            cx += p.0;
            cy += p.1;
        }
        cx /= live.len() as f32;
        cy /= live.len() as f32;
        for &i in &live {
            emit_arc(&verts[i], (cx, cy), &mut arcs);
            verts[i].alive = false;
        }
    }

    arcs
}

/// Wavefront vertex: where it was born, when, the velocity, and its current
/// topology (prev/next indices in the doubly-linked list).
#[derive(Debug, Clone, Copy)]
struct WV {
    born_at: (f32, f32),
    born_t: f32,
    vel: (f32, f32),
    prev: usize,
    next: usize,
    /// Convex (90°) or reflex (270°) corner — set at birth.
    reflex: bool,
    /// Was this vertex an *original* polygon corner (vs a skeleton-emitted
    /// vertex created by an event)? Determines Hip vs Ridge classification.
    original: bool,
    alive: bool,
}

impl WV {
    fn pos_at(&self, t: f32) -> (f32, f32) {
        let dt = t - self.born_t;
        (self.born_at.0 + dt * self.vel.0, self.born_at.1 + dt * self.vel.1)
    }
}

fn init_vertices(poly: &[(f32, f32)]) -> Vec<WV> {
    let n = poly.len();
    let mut out = Vec::with_capacity(n);
    for i in 0..n {
        let prev = (i + n - 1) % n;
        let next = (i + 1) % n;
        let reflex = is_reflex(poly[prev], poly[i], poly[next]);
        let vel = corner_velocity(poly[prev], poly[i], poly[next]);
        out.push(WV {
            born_at: poly[i],
            born_t: 0.0,
            vel,
            prev,
            next,
            reflex,
            original: true,
            alive: true,
        });
    }
    out
}

/// CCW polygon: a corner is reflex if the cross of the in-edge and out-edge
/// is negative (right turn). Convex if positive.
fn is_reflex(prev: (f32, f32), here: (f32, f32), next: (f32, f32)) -> bool {
    let dx1 = here.0 - prev.0;
    let dy1 = here.1 - prev.1;
    let dx2 = next.0 - here.0;
    let dy2 = next.1 - here.1;
    let cross = dx1 * dy2 - dy1 * dx2;
    cross < 0.0
}

/// Velocity of a corner under unit-speed inward edge offsetting:
/// `v = (n_in + n_out) / (1 + n_in · n_out)` for the two inward edge normals.
/// At reflex corners this still gives a finite velocity pointing inward.
fn corner_velocity(prev: (f32, f32), here: (f32, f32), next: (f32, f32)) -> (f32, f32) {
    let n_in = inward_normal(prev, here);
    let n_out = inward_normal(here, next);
    let denom = 1.0 + n_in.0 * n_out.0 + n_in.1 * n_out.1;
    if denom.abs() < 1e-6 {
        // Degenerate (anti-parallel edges) — should not happen for rectilinear.
        return (0.0, 0.0);
    }
    ((n_in.0 + n_out.0) / denom, (n_in.1 + n_out.1) / denom)
}

/// CCW polygon: inward normal of edge `a→b` is `rotate(d, +90°) = (-dy, dx)`.
fn inward_normal(a: (f32, f32), b: (f32, f32)) -> (f32, f32) {
    let dx = b.0 - a.0;
    let dy = b.1 - a.1;
    let len = (dx * dx + dy * dy).sqrt().max(1e-9);
    (-dy / len, dx / len)
}

fn alive_count(verts: &[WV]) -> usize {
    verts.iter().filter(|v| v.alive).count()
}

/// Find the first alive edge whose endpoints have effectively coincident
/// positions at time `t`. Used to drain simultaneous events.
fn find_zero_length_edge(verts: &[WV], t: f32) -> Option<(usize, usize)> {
    let eps2 = 1e-6_f32;
    for i in 0..verts.len() {
        if !verts[i].alive {
            continue;
        }
        let j = verts[i].next;
        if i == j {
            continue;
        }
        let pi = verts[i].pos_at(t);
        let pj = verts[j].pos_at(t);
        if (pi.0 - pj.0).powi(2) + (pi.1 - pj.1).powi(2) < eps2 {
            return Some((i, j));
        }
    }
    None
}

#[derive(Debug, Clone, Copy)]
enum EventKind {
    Edge { i: usize, j: usize },
    /// Reflex vertex `r` hits the edge whose endpoints are `e_i → e_j`.
    Split { r: usize, e_i: usize, e_j: usize },
}

#[derive(Debug, Clone, Copy)]
struct Event {
    time: f32,
    kind: EventKind,
}

#[allow(clippy::collapsible_if)] // the nested conditions read more clearly than `&&`'d together
fn next_event(verts: &[WV], now: f32) -> Option<Event> {
    let mut best: Option<Event> = None;
    let eps = 1e-4;
    // Edge events.
    for i in 0..verts.len() {
        if !verts[i].alive {
            continue;
        }
        let j = verts[i].next;
        if let Some(te) = edge_collapse_time(&verts[i], &verts[j], now) {
            if te > now + eps && best.is_none_or(|b| te < b.time) {
                best = Some(Event { time: te, kind: EventKind::Edge { i, j } });
            }
        }
    }
    // Split events (only reflex vertices can fire these).
    for r in 0..verts.len() {
        if !verts[r].alive || !verts[r].reflex {
            continue;
        }
        for e_i in 0..verts.len() {
            if !verts[e_i].alive {
                continue;
            }
            let e_j = verts[e_i].next;
            // An edge can't split via one of its own endpoints.
            if e_i == r || e_j == r || verts[r].next == e_i || verts[r].prev == e_j {
                continue;
            }
            if let Some(ts) = split_time(verts, r, e_i, e_j, now) {
                if ts > now + eps && best.is_none_or(|b| ts < b.time) {
                    best = Some(Event { time: ts, kind: EventKind::Split { r, e_i, e_j } });
                }
            }
        }
    }
    best
}

/// Time at which the edge `v_a → v_b` collapses (length becomes zero).
#[allow(clippy::similar_names)] // va/vb pair with dvx/dvy/dpx/dpy — local to this routine
fn edge_collapse_time(va: &WV, vb: &WV, now: f32) -> Option<f32> {
    let pa = va.pos_at(now);
    let pb = vb.pos_at(now);
    let dvx = vb.vel.0 - va.vel.0;
    let dvy = vb.vel.1 - va.vel.1;
    let dpx = pb.0 - pa.0;
    let dpy = pb.1 - pa.1;
    // Edge direction unit vector at time `now`.
    let len0 = (dpx * dpx + dpy * dpy).sqrt();
    if len0 < 1e-6 {
        return None;
    }
    let dhat = (dpx / len0, dpy / len0);
    let rate = dvx * dhat.0 + dvy * dhat.1;
    if rate > -1e-6 {
        // Edge isn't shrinking — never collapses from corner motion alone.
        return None;
    }
    Some(now + (-len0) / rate)
}

/// Time at which the reflex vertex `r`'s trajectory crosses the offset line
/// of edge `e_i → e_j` and the crossing point lies between the moving
/// endpoints.
#[allow(clippy::similar_names)] // vi/vj name the edge endpoints — math-natural here
fn split_time(verts: &[WV], r: usize, e_i: usize, e_j: usize, now: f32) -> Option<f32> {
    let pr = verts[r].pos_at(now);
    let vi = verts[e_i].pos_at(now);
    let vj = verts[e_j].pos_at(now);
    let n = inward_normal(vi, vj);
    // Offset line at time t: n · X = (n · vi_now) + (t - now). Substitute
    // X = pr + (t - now)*vel_r.
    // n · pr + dt*(n · v_r) = n · vi + dt
    // dt*(n · v_r - 1) = n · vi - n · pr
    let denom = n.0 * verts[r].vel.0 + n.1 * verts[r].vel.1 - 1.0;
    if denom.abs() < 1e-6 {
        return None;
    }
    let num = n.0 * (vi.0 - pr.0) + n.1 * (vi.1 - pr.1);
    let dt = num / denom;
    if dt <= 1e-6 {
        return None;
    }
    let t = now + dt;
    // Check that the crossing point lies on the edge at time t.
    let pr_t = (pr.0 + dt * verts[r].vel.0, pr.1 + dt * verts[r].vel.1);
    let vi_t = verts[e_i].pos_at(t);
    let vj_t = verts[e_j].pos_at(t);
    let edx = vj_t.0 - vi_t.0;
    let edy = vj_t.1 - vi_t.1;
    let elen2 = edx * edx + edy * edy;
    if elen2 < 1e-6 {
        return None;
    }
    let u = ((pr_t.0 - vi_t.0) * edx + (pr_t.1 - vi_t.1) * edy) / elen2;
    if !(0.001..=0.999).contains(&u) {
        return None;
    }
    Some(t)
}

fn emit_arc(v: &WV, end: (f32, f32), arcs: &mut Vec<SkeletonArc>) {
    let kind = if v.original {
        if v.reflex { ArcKind::Valley } else { ArcKind::Hip }
    } else {
        ArcKind::Ridge
    };
    arcs.push(SkeletonArc { a: v.born_at, b: end, kind });
}

fn process_edge_event(verts: &mut Vec<WV>, arcs: &mut Vec<SkeletonArc>, i: usize, j: usize, t: f32) {
    // Merge V_i and V_j into a new vertex at their collision point.
    let collision = verts[i].pos_at(t);
    let prev = verts[i].prev;
    let next = verts[j].next;
    emit_arc(&verts[i], collision, arcs);
    emit_arc(&verts[j], collision, arcs);
    verts[i].alive = false;
    verts[j].alive = false;
    // Compute new vertex topology + velocity from the (already-moved) wavefront.
    let p_prev = verts[prev].pos_at(t);
    let p_next = verts[next].pos_at(t);
    let new_vel = corner_velocity(p_prev, collision, p_next);
    let reflex = is_reflex(p_prev, collision, p_next);
    let new_idx = verts.len();
    verts.push(WV {
        born_at: collision,
        born_t: t,
        vel: new_vel,
        prev,
        next,
        reflex,
        original: false,
        alive: true,
    });
    verts[prev].next = new_idx;
    verts[next].prev = new_idx;
}

#[allow(clippy::similar_names)] // p_ei / p_ej name the edge endpoints — math-natural pair
fn process_split_event(
    verts: &mut Vec<WV>,
    arcs: &mut Vec<SkeletonArc>,
    r: usize,
    e_i: usize,
    e_j: usize,
    t: f32,
) {
    // The reflex vertex r at time t lies on edge (e_i → e_j). The polygon
    // splits into two loops at that point; insert two new vertices (one for
    // each loop) at the split position.
    let split = verts[r].pos_at(t);
    let r_prev = verts[r].prev;
    let r_next = verts[r].next;
    emit_arc(&verts[r], split, arcs);
    verts[r].alive = false;

    // Loop A: ... r_prev → new_a → e_j → ...   (uses outgoing half of e_i's edge)
    // Loop B: ... e_i → new_b → r_next → ...   (uses incoming half of e_j's edge)
    let p_prev = verts[r_prev].pos_at(t);
    let p_next = verts[r_next].pos_at(t);
    let p_ei = verts[e_i].pos_at(t);
    let p_ej = verts[e_j].pos_at(t);

    let vel_a = corner_velocity(p_prev, split, p_ej);
    let refl_a = is_reflex(p_prev, split, p_ej);
    let vel_b = corner_velocity(p_ei, split, p_next);
    let refl_b = is_reflex(p_ei, split, p_next);

    let a_idx = verts.len();
    verts.push(WV {
        born_at: split,
        born_t: t,
        vel: vel_a,
        prev: r_prev,
        next: e_j,
        reflex: refl_a,
        original: false,
        alive: true,
    });
    let b_idx = verts.len();
    verts.push(WV {
        born_at: split,
        born_t: t,
        vel: vel_b,
        prev: e_i,
        next: r_next,
        reflex: refl_b,
        original: false,
        alive: true,
    });
    verts[r_prev].next = a_idx;
    verts[e_j].prev = a_idx;
    verts[e_i].next = b_idx;
    verts[r_next].prev = b_idx;
}

/// Convert arcs to a single SVG `<g>` fragment for the roof plan. Hips and
/// valleys are drawn solid; ridges are emphasised in a darker tone.
#[must_use]
pub fn skeleton_to_svg_fragment(
    arcs: &[SkeletonArc],
    x_of: &dyn Fn(f32) -> f32,
    y_of: &dyn Fn(f32) -> f32,
) -> String {
    let mut s = String::with_capacity(arcs.len() * 80);
    for arc in arcs {
        let (stroke, width) = match arc.kind {
            ArcKind::Ridge => ("#222", 2.0),
            ArcKind::Hip => ("#555", 1.2),
            ArcKind::Valley => ("#a55", 1.2),
        };
        let _ = writeln!(
            s,
            r#"<line x1="{}" y1="{}" x2="{}" y2="{}" stroke="{stroke}" stroke-width="{width}"/>"#,
            x_of(arc.a.0), y_of(arc.a.1), x_of(arc.b.0), y_of(arc.b.1),
        );
    }
    s
}

#[cfg(test)]
mod tests {
    use super::*;

    fn approx(a: (f32, f32), b: (f32, f32), tol: f32) -> bool {
        (a.0 - b.0).abs() < tol && (a.1 - b.1).abs() < tol
    }

    #[test]
    fn rectangle_skeleton_meets_at_central_ridge() {
        // 10 wide × 6 tall: ridge runs along y=3, from x=3 to x=7 (short-span
        // inset = 3 either side). Four hips connect the corners to the ridge
        // endpoints.
        let rect = vec![(0.0, 0.0), (10.0, 0.0), (10.0, 6.0), (0.0, 6.0)];
        let arcs = rectilinear_straight_skeleton(&rect);
        assert!(!arcs.is_empty(), "rect produced no skeleton");
        // 4 hips from the corners → 2 skeleton nodes at (3,3) and (7,3),
        // plus a ridge between them.
        let hips: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Hip).collect();
        assert_eq!(hips.len(), 4, "expected 4 hips, got {}", hips.len());
        let ridges: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Ridge).collect();
        assert!(!ridges.is_empty(), "expected a ridge between the two nodes");
        // Each hip should end at either (3,3) or (7,3).
        for h in &hips {
            assert!(
                approx(h.b, (3.0, 3.0), 0.05) || approx(h.b, (7.0, 3.0), 0.05),
                "hip end {:?} doesn't land on a ridge endpoint", h.b,
            );
        }
    }

    #[test]
    fn square_skeleton_meets_at_centre() {
        // For a square, all 4 hips converge to a single point at the centre.
        let sq = vec![(0.0, 0.0), (6.0, 0.0), (6.0, 6.0), (0.0, 6.0)];
        let arcs = rectilinear_straight_skeleton(&sq);
        let hips: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Hip).collect();
        assert_eq!(hips.len(), 4, "square should yield 4 hips, got {}", hips.len());
        // All hips end at (3,3) (the centroid).
        for h in &hips {
            assert!(approx(h.b, (3.0, 3.0), 0.05), "hip end {:?} ≠ (3,3)", h.b);
        }
    }

    #[test]
    fn t_shape_skeleton_has_two_valleys_from_two_reflex_corners() {
        // T-shape: a 12×4 base with a 4×6 stem rising from x∈[4,8].
        //   (0,0)→(12,0)→(12,4)→(8,4)→(8,10)→(4,10)→(4,4)→(0,4)
        // Two reflex corners at (8,4) and (4,4).
        let t = vec![
            (0.0, 0.0), (12.0, 0.0), (12.0, 4.0),
            (8.0, 4.0), (8.0, 10.0), (4.0, 10.0),
            (4.0, 4.0), (0.0, 4.0),
        ];
        let arcs = rectilinear_straight_skeleton(&t);
        assert!(!arcs.is_empty(), "T produced no skeleton");
        let valleys: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Valley).collect();
        assert_eq!(valleys.len(), 2, "T should have 2 valleys, got {}", valleys.len());
        // Each valley starts at one of the reflex corners.
        let starts: Vec<_> = valleys.iter().map(|v| v.a).collect();
        assert!(starts.iter().any(|p| approx(*p, (8.0, 4.0), 0.01)));
        assert!(starts.iter().any(|p| approx(*p, (4.0, 4.0), 0.01)));
        let hips: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Hip).collect();
        // 6 convex corners → 6 hips.
        assert_eq!(hips.len(), 6, "T should have 6 hips, got {}", hips.len());
    }

    #[test]
    fn l_shape_skeleton_has_one_valley_from_reflex_corner() {
        // L-shape:
        //   (0,0) (10,0) (10,4) (6,4) (6,8) (0,8)
        // One reflex corner at (6,4) — interior angle 270°.
        let l = vec![
            (0.0, 0.0), (10.0, 0.0), (10.0, 4.0),
            (6.0, 4.0), (6.0, 8.0), (0.0, 8.0),
        ];
        let arcs = rectilinear_straight_skeleton(&l);
        assert!(!arcs.is_empty(), "L produced no skeleton");
        let valleys: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Valley).collect();
        assert_eq!(valleys.len(), 1, "L should have exactly 1 valley, got {}", valleys.len());
        // The valley originates at the reflex corner.
        assert!(approx(valleys[0].a, (6.0, 4.0), 0.01));
        let hips: Vec<_> = arcs.iter().filter(|a| a.kind == ArcKind::Hip).collect();
        // 5 convex corners → 5 hips.
        assert_eq!(hips.len(), 5, "L should have 5 hips, got {}", hips.len());
    }
}
