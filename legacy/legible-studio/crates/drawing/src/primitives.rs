//! 2D drawing primitives.
//!
//! Ported from `slicer_2d.hpp:16-100`. Note: these are intentionally
//! distinct from `archgeometry::geometry_types::{Line2D, …}` —  the
//! slicer's primitives carry colour and line-weight so they can be
//! emitted directly to SVG/DXF without further enrichment.

use glam::{Vec2, Vec3};

/// 2D point alias for plan-view / section-view geometry.
pub type Point2D = Vec2;

/// 2D line segment.
#[derive(Debug, Clone, PartialEq)]
pub struct Line2D {
    pub start: Point2D,
    pub end: Point2D,
    pub layer: String,
    /// `"continuous"`, `"dashed"`, `"center"`, `"hidden"`.
    pub line_type: String,
    /// In mm.
    pub line_weight: f32,
    /// RGB. Default = black.
    pub color: Vec3,
}

impl Default for Line2D {
    fn default() -> Self {
        Self {
            start: Vec2::ZERO,
            end: Vec2::ZERO,
            layer: String::new(),
            line_type: "continuous".to_string(),
            line_weight: 0.25,
            color: Vec3::ZERO,
        }
    }
}

impl Line2D {
    #[must_use]
    pub fn length(&self) -> f32 {
        (self.end - self.start).length()
    }

    #[must_use]
    pub fn midpoint(&self) -> Point2D {
        (self.start + self.end) * 0.5
    }
}

/// Connected polyline. `closed = true` means the last point connects
/// back to the first (rendered as a polygon).
#[derive(Debug, Clone, PartialEq)]
pub struct Polyline2D {
    pub points: Vec<Point2D>,
    pub closed: bool,
    pub layer: String,
    pub line_type: String,
    pub line_weight: f32,
    pub color: Vec3,
}

impl Default for Polyline2D {
    fn default() -> Self {
        Self {
            points: Vec::new(),
            closed: false,
            layer: String::new(),
            line_type: "continuous".to_string(),
            line_weight: 0.25,
            color: Vec3::ZERO,
        }
    }
}

impl Polyline2D {
    pub fn add_point(&mut self, p: Point2D) {
        self.points.push(p);
    }

    /// A polyline needs ≥ 2 points to draw.
    #[must_use]
    pub fn is_drawable(&self) -> bool {
        self.points.len() >= 2
    }
}

/// 2D arc (portion of a circle).
#[derive(Debug, Clone, PartialEq)]
pub struct Arc2D {
    pub center: Point2D,
    pub radius: f32,
    /// Radians.
    pub start_angle: f32,
    pub end_angle: f32,
    pub layer: String,
    pub line_weight: f32,
    pub color: Vec3,
}

impl Default for Arc2D {
    fn default() -> Self {
        Self {
            center: Vec2::ZERO,
            radius: 0.0,
            start_angle: 0.0,
            end_angle: 0.0,
            layer: String::new(),
            line_weight: 0.25,
            color: Vec3::ZERO,
        }
    }
}

/// 2D circle.
#[derive(Debug, Clone, PartialEq, Default)]
pub struct Circle2D {
    pub center: Point2D,
    pub radius: f32,
    pub layer: String,
    pub line_weight: f32,
    pub color: Vec3,
}

/// Text annotation.
#[derive(Debug, Clone, PartialEq)]
pub struct Text2D {
    pub position: Point2D,
    pub text: String,
    /// Text height in mm.
    pub height: f32,
    /// Rotation in radians.
    pub rotation: f32,
    pub layer: String,
    pub style: String,
    /// `"left"`, `"center"`, `"right"`.
    pub justification: String,
    pub color: Vec3,
}

impl Default for Text2D {
    fn default() -> Self {
        Self {
            position: Vec2::ZERO,
            text: String::new(),
            height: 2.5,
            rotation: 0.0,
            layer: String::new(),
            style: "Standard".to_string(),
            justification: "left".to_string(),
            color: Vec3::ZERO,
        }
    }
}

/// Linear dimension.
#[derive(Debug, Clone, PartialEq)]
pub struct Dimension2D {
    pub point1: Point2D,
    pub point2: Point2D,
    pub text_position: Point2D,
    /// Override text — empty = auto-calculate from `point1`/`point2`.
    pub text: String,
    pub text_height: f32,
    pub layer: String,
    pub style: String,
}

impl Default for Dimension2D {
    fn default() -> Self {
        Self {
            point1: Vec2::ZERO,
            point2: Vec2::ZERO,
            text_position: Vec2::ZERO,
            text: String::new(),
            text_height: 2.5,
            layer: "DIMS".to_string(),
            style: "Standard".to_string(),
        }
    }
}

/// Hatch / fill pattern bounded by one or more polylines.
#[derive(Debug, Clone, PartialEq)]
pub struct Hatch2D {
    pub boundaries: Vec<Polyline2D>,
    /// `"SOLID"`, `"ANSI31"`, `"INSULATION"`, `"CONCRETE"`, …
    pub pattern: String,
    pub scale: f32,
    pub angle: f32,
    pub layer: String,
    pub color: Vec3,
}

impl Default for Hatch2D {
    fn default() -> Self {
        Self {
            boundaries: Vec::new(),
            pattern: String::new(),
            scale: 1.0,
            angle: 0.0,
            layer: String::new(),
            color: Vec3::new(0.8, 0.8, 0.8),
        }
    }
}

/// Result of slicing one element or a whole building. Accumulates
/// every primitive the SVG/DXF emitter will draw.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct SliceResult {
    pub element_id: String,
    /// `"wall"`, `"floor"`, `"beam"`, …
    pub element_type: String,
    pub lines: Vec<Line2D>,
    pub polylines: Vec<Polyline2D>,
    pub arcs: Vec<Arc2D>,
    pub circles: Vec<Circle2D>,
    pub hatches: Vec<Hatch2D>,
    pub annotations: Vec<Text2D>,
    pub dimensions: Vec<Dimension2D>,
}

impl SliceResult {
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.lines.is_empty()
            && self.polylines.is_empty()
            && self.arcs.is_empty()
            && self.circles.is_empty()
            && self.hatches.is_empty()
    }

    /// Append all primitives from `other` to `self`.
    pub fn merge(&mut self, other: SliceResult) {
        self.lines.extend(other.lines);
        self.polylines.extend(other.polylines);
        self.arcs.extend(other.arcs);
        self.circles.extend(other.circles);
        self.hatches.extend(other.hatches);
        self.annotations.extend(other.annotations);
        self.dimensions.extend(other.dimensions);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn line2d_length_and_midpoint() {
        let l = Line2D {
            start: Vec2::ZERO,
            end: Vec2::new(3.0, 4.0),
            ..Default::default()
        };
        assert_eq!(l.length(), 5.0);
        assert_eq!(l.midpoint(), Vec2::new(1.5, 2.0));
    }

    #[test]
    fn polyline_needs_two_points_to_draw() {
        let mut p = Polyline2D::default();
        assert!(!p.is_drawable());
        p.add_point(Vec2::ZERO);
        assert!(!p.is_drawable());
        p.add_point(Vec2::X);
        assert!(p.is_drawable());
    }

    #[test]
    fn slice_result_merge_appends_everything() {
        let mut a = SliceResult::default();
        a.lines.push(Line2D::default());

        let mut b = SliceResult::default();
        b.lines.push(Line2D::default());
        b.polylines.push(Polyline2D::default());
        b.annotations.push(Text2D::default());

        a.merge(b);
        assert_eq!(a.lines.len(), 2);
        assert_eq!(a.polylines.len(), 1);
        assert_eq!(a.annotations.len(), 1);
    }
}
