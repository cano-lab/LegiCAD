//! Sketch-pad state for the hybrid pad. Two modes share one canvas:
//!
//! - **Boundary** (constraint mode): a polygon that becomes a kernel `Region`,
//!   an *input* to the room solver — strokes are constraints, not geometry.
//! - **Freeform** (Increment 5): closed profiles that become freeform `Object`s
//!   (extruded prisms) — strokes *are* the geometry. This is the "design
//!   anything" half: a drawn shape is a real kernel object, built by
//!   `catalog::FreeformGenerator` through the same registry as everything else.

use catalog::freeform_object;
use glam::Vec2;
use pk_object::{Region, RegionId, Scene};

/// Extrusion height (mm) given to a freeform profile when it becomes an object.
const FREEFORM_HEIGHT_MM: f32 = 2500.0;

/// What a left-click does. The pad opens in `View` so clicks navigate/inspect
/// instead of dropping vertices; the user opts into a drawing mode explicitly.
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Clicks don't draw — just view/pan/zoom the plan.
    #[default]
    View,
    /// Strokes build the solver-input boundary region.
    Boundary,
    /// Strokes build freeform geometry objects.
    Freeform,
}

/// A boundary being sketched plus any finalized freeform shapes. Points are
/// in world mm.
#[derive(Debug, Default, Clone)]
pub struct Sketch {
    pub mode: Mode,
    /// The boundary polygon (constraint mode).
    pub points: Vec<(f32, f32)>,
    pub closed: bool,
    /// Finalized freeform profiles, each a closed polygon.
    pub freeforms: Vec<Vec<(f32, f32)>>,
    /// The freeform profile currently being drawn (not yet finalized).
    pub current: Vec<(f32, f32)>,
}

impl Sketch {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Switch the active mode, dropping any half-drawn freeform stroke so the
    /// modes don't bleed into each other.
    pub fn set_mode(&mut self, mode: Mode) {
        self.mode = mode;
        self.current.clear();
    }

    /// Add a vertex to whatever the current mode is drawing. A no-op in
    /// `View` — clicks there don't draw.
    pub fn add_point(&mut self, x: f32, y: f32) {
        match self.mode {
            Mode::View => {}
            Mode::Boundary => {
                if !self.closed {
                    self.points.push((x, y));
                }
            }
            Mode::Freeform => self.current.push((x, y)),
        }
    }

    /// Finalize the current shape. In boundary mode this closes the region;
    /// in freeform mode it banks the current profile as a new freeform shape.
    /// Returns whether anything was finalized (needs 3+ vertices).
    pub fn close(&mut self) -> bool {
        match self.mode {
            Mode::View => false,
            Mode::Boundary => {
                if self.points.len() >= 3 {
                    self.closed = true;
                }
                self.closed
            }
            Mode::Freeform => {
                if self.current.len() >= 3 {
                    self.freeforms.push(std::mem::take(&mut self.current));
                    true
                } else {
                    false
                }
            }
        }
    }

    /// Clear everything in the current mode (boundary or all freeforms),
    /// leaving the other mode's work intact. A no-op in `View`.
    pub fn clear(&mut self) {
        match self.mode {
            Mode::View => {}
            Mode::Boundary => {
                self.points.clear();
                self.closed = false;
            }
            Mode::Freeform => {
                self.current.clear();
                self.freeforms.clear();
            }
        }
    }

    /// Build a kernel `Scene`: the boundary as a `Region` (solver input) plus
    /// one freeform `Object` per finalized profile. The room solver consumes
    /// the region; `catalog::FreeformGenerator` builds the freeform objects.
    #[must_use]
    pub fn to_scene(&self) -> Scene {
        let mut scene = Scene::new();
        if self.points.len() >= 3 {
            scene.regions.push(Region {
                id: RegionId(0),
                polygon: self.points.iter().map(|&(x, y)| Vec2::new(x, y)).collect(),
            });
        }
        for (i, poly) in self.freeforms.iter().enumerate() {
            let profile: Vec<Vec2> = poly.iter().map(|&(x, y)| Vec2::new(x, y)).collect();
            // ids above any room the solver will mint, to avoid collisions.
            scene.add(freeform_object(10_000 + i as u64, &profile, FREEFORM_HEIGHT_MM));
        }
        scene
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use catalog::{design_registry, room_rect, GridRoomSolver};
    use pk_object::Solver;

    #[test]
    fn add_point_respects_closed() {
        let mut s = Sketch::new();
        s.set_mode(Mode::Boundary);
        s.add_point(0.0, 0.0);
        s.add_point(1.0, 0.0);
        s.add_point(1.0, 1.0);
        assert!(s.close());
        s.add_point(2.0, 2.0); // ignored — closed
        assert_eq!(s.points.len(), 3);
    }

    #[test]
    fn close_needs_three_points() {
        let mut s = Sketch::new();
        s.set_mode(Mode::Boundary);
        s.add_point(0.0, 0.0);
        s.add_point(1.0, 0.0);
        assert!(!s.close());
        assert!(!s.closed);
    }

    #[test]
    fn to_scene_emits_a_region_when_closed_enough() {
        let mut s = Sketch::new();
        s.set_mode(Mode::Boundary);
        assert!(s.to_scene().regions.is_empty());
        for p in [(0.0, 0.0), (6000.0, 0.0), (6000.0, 4000.0), (0.0, 4000.0)] {
            s.add_point(p.0, p.1);
        }
        assert_eq!(s.to_scene().regions.len(), 1);
    }

    #[test]
    fn sketch_to_solver_yields_rooms() {
        // The full Increment-3 loop, headless: boundary → scene → solver → rooms.
        let mut s = Sketch::new();
        s.set_mode(Mode::Boundary);
        for p in [(0.0, 0.0), (6000.0, 0.0), (6000.0, 4000.0), (0.0, 4000.0)] {
            s.add_point(p.0, p.1);
        }
        s.close();
        let mut scene = s.to_scene();
        GridRoomSolver::default().solve(&mut scene);
        let rooms: Vec<_> = scene
            .objects
            .iter()
            .filter(|o| o.kind == "room")
            .filter_map(room_rect)
            .collect();
        assert!(!rooms.is_empty(), "solver produced no rooms from the sketch");
    }

    #[test]
    fn freeform_mode_banks_profiles_separately_from_boundary() {
        let mut s = Sketch::new();
        // Draw a boundary first.
        s.set_mode(Mode::Boundary);
        for p in [(0.0, 0.0), (6000.0, 0.0), (6000.0, 4000.0)] {
            s.add_point(p.0, p.1);
        }
        s.close();
        // Switch to freeform and draw a triangle.
        s.set_mode(Mode::Freeform);
        assert_eq!(s.mode, Mode::Freeform);
        for p in [(1000.0, 1000.0), (2000.0, 1000.0), (1500.0, 2000.0)] {
            s.add_point(p.0, p.1);
        }
        assert!(s.close());
        assert_eq!(s.freeforms.len(), 1);
        // Boundary survived the mode switch.
        assert!(s.closed);
        assert_eq!(s.points.len(), 3);
    }

    #[test]
    fn freeform_objects_build_through_the_registry() {
        let mut s = Sketch::new();
        s.set_mode(Mode::Freeform);
        for p in [(0.0, 0.0), (2000.0, 0.0), (2000.0, 2000.0), (0.0, 2000.0)] {
            s.add_point(p.0, p.1);
        }
        s.close();
        let mut scene = s.to_scene();
        let geo = design_registry().build(&mut scene);
        // One freeform object → one non-empty mesh.
        assert_eq!(geo.per_object.len(), 1);
        assert!(geo.per_object[0].1.mesh.as_ref().is_some_and(|m| m.triangle_count() > 0));
    }

    #[test]
    fn clear_is_scoped_to_the_active_mode() {
        let mut s = Sketch::new();
        s.set_mode(Mode::Boundary);
        for p in [(0.0, 0.0), (6000.0, 0.0), (6000.0, 4000.0)] {
            s.add_point(p.0, p.1);
        }
        s.close();
        s.set_mode(Mode::Freeform);
        for p in [(0.0, 0.0), (1000.0, 0.0), (500.0, 1000.0)] {
            s.add_point(p.0, p.1);
        }
        s.close();
        s.clear(); // clears freeforms only
        assert!(s.freeforms.is_empty());
        assert!(s.closed); // boundary untouched
    }
}
