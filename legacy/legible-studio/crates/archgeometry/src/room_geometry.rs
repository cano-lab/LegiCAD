//! Room boundary generator.
//!
//! Port of `Shared/ArchGeometry/src/room_geometry.cpp`.
//!
//! Coordinate convention (inherited from C++):
//! - `RoomBounds.x` is plan-view X (= 3D X).
//! - `RoomBounds.y` is plan-view Y, **which is Z in 3D space** — pure
//!   plan-view convention from the C++. Don't conflate with 3D Y.
//! - `RoomBounds.width` is X extent, `RoomBounds.height` is Z extent.

use crate::geometry_types::{Point2D, Polygon2D, RoomBoundary, Text2D};
use crate::schema_types::{RoomBounds, SchemaRoom, SchemaWall};
use glam::Vec3;

/// Zone name → render colour. Matches `room_geometry.cpp:160`.
#[must_use]
pub fn zone_color(zone: &str) -> Vec3 {
    match zone {
        "living" | "public" => Vec3::new(0.9, 0.95, 0.85),
        "sleeping" | "private" => Vec3::new(0.85, 0.9, 0.95),
        "wet" | "service" => Vec3::new(0.9, 0.9, 0.95),
        "circulation" => Vec3::new(0.95, 0.95, 0.9),
        "utility" | "garage" => Vec3::new(0.9, 0.9, 0.9),
        "outdoor" => Vec3::new(0.85, 0.95, 0.85),
        _ => Vec3::new(0.95, 0.95, 0.95),
    }
}

/// Centre point of a `RoomBounds`. The returned `y` field is Z in 3D space.
#[must_use]
pub fn center(bounds: &RoomBounds) -> Point2D {
    Point2D::new(
        bounds.x + bounds.width * 0.5,
        bounds.y + bounds.height * 0.5,
    )
}

/// Plan-view area in mm².
#[must_use]
pub fn area(bounds: &RoomBounds) -> f32 {
    bounds.width * bounds.height
}

/// Convert 2D bounds to 3D bounding box at the given `elevation` (Y) and
/// ceiling `height` (Y extent).
#[must_use]
pub fn bounds_2d_to_3d(bounds: &RoomBounds, elevation: f32, height: f32) -> (Vec3, Vec3) {
    let min = Vec3::new(bounds.x, elevation, bounds.y);
    let max = Vec3::new(
        bounds.x + bounds.width,
        elevation + height,
        bounds.y + bounds.height,
    );
    (min, max)
}

/// True if `point` (plan view; `point.y` is Z in 3D) is inside the room's
/// rectangular bounds.
#[must_use]
pub fn contains_point(point: Point2D, room: &SchemaRoom) -> bool {
    let b = &room.bounds;
    point.x >= b.x && point.x <= b.x + b.width && point.y >= b.y && point.y <= b.y + b.height
}

/// Build the room boundary from its rectangular bounds. The wall list is
/// ignored — the C++ leaves the wall-tracing path as a future enhancement
/// (`room_geometry.cpp:29-34`).
#[must_use]
pub fn generate_boundary(room: &SchemaRoom, _walls: &[SchemaWall]) -> RoomBoundary {
    generate_from_bounds(room)
}

/// Build the room boundary from bounds only.
#[must_use]
pub fn generate_from_bounds(room: &SchemaRoom) -> RoomBoundary {
    let b = &room.bounds;
    let min_x = b.x;
    let max_x = b.x + b.width;
    let min_z = b.y;
    let max_z = b.y + b.height;

    let zc = zone_color(&room.zone);

    let poly = Polygon2D {
        points: vec![
            Point2D::new(min_x, min_z),
            Point2D::new(max_x, min_z),
            Point2D::new(max_x, max_z),
            Point2D::new(min_x, max_z),
        ],
        closed: true,
        layer: "rooms".to_string(),
        fill_pattern: "solid".to_string(),
        fill_color: [zc.x, zc.y, zc.z, 0.15],
    };

    RoomBoundary {
        boundary: poly,
        center: center(b),
        area: area(b),
        label: room.name.clone(),
        room_type: room.room_type.clone(),
        room_id: room.id.clone(),
    }
}

/// Centered text label for the room. Falls back to room_type when name is
/// empty (matches `room_geometry.cpp:131-133`).
#[must_use]
pub fn generate_label(room: &SchemaRoom) -> Text2D {
    let text = if room.name.is_empty() {
        room.room_type.clone()
    } else {
        room.name.clone()
    };
    Text2D {
        layer: "room_labels".to_string(),
        position: center(&room.bounds),
        text,
        font_size: 150.0,
        height: 150.0,
        alignment: "center".to_string(),
        anchor: "middle".to_string(),
        rotation: 0.0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_room() -> SchemaRoom {
        SchemaRoom {
            id: "primary_bedroom".into(),
            name: "Primary Bedroom".into(),
            room_type: "bedroom".into(),
            bounds: RoomBounds {
                x: 0.0,
                y: 0.0,
                width: 4000.0,
                height: 3500.0,
            },
            zone: "private".into(),
            ..Default::default()
        }
    }

    #[test]
    fn area_is_width_times_height() {
        let b = RoomBounds {
            width: 4000.0,
            height: 3500.0,
            ..Default::default()
        };
        assert_eq!(area(&b), 14_000_000.0);
    }

    #[test]
    fn center_is_midpoint_of_bounds() {
        let b = RoomBounds {
            x: 100.0,
            y: 200.0,
            width: 4000.0,
            height: 3500.0,
        };
        let c = center(&b);
        assert_eq!(c.x, 2100.0);
        assert_eq!(c.y, 1950.0);
    }

    #[test]
    fn generate_from_bounds_produces_4_corner_polygon() {
        let r = test_room();
        let rb = generate_from_bounds(&r);
        assert_eq!(rb.boundary.points.len(), 4);
        assert_eq!(rb.area, 14_000_000.0);
        assert_eq!(rb.room_id, "primary_bedroom");
        assert_eq!(rb.label, "Primary Bedroom");
        assert_eq!(rb.boundary.layer, "rooms");
        // Private zone → light blue, alpha 0.15.
        assert_eq!(rb.boundary.fill_color, [0.85, 0.9, 0.95, 0.15]);
    }

    #[test]
    fn label_falls_back_to_room_type_when_name_empty() {
        let mut r = test_room();
        r.name.clear();
        let label = generate_label(&r);
        assert_eq!(label.text, "bedroom");
    }

    #[test]
    fn contains_point_inside_and_outside() {
        let r = test_room();
        assert!(contains_point(Point2D::new(100.0, 100.0), &r));
        assert!(contains_point(Point2D::new(0.0, 0.0), &r)); // corner
        assert!(!contains_point(Point2D::new(-1.0, 100.0), &r));
        assert!(!contains_point(Point2D::new(100.0, 4000.0), &r));
    }

    #[test]
    fn bounds_2d_to_3d_maps_y_axis_to_z_axis() {
        let b = RoomBounds {
            x: 0.0,
            y: 1000.0, // y here is Z in 3D
            width: 4000.0,
            height: 3500.0,
        };
        let (min, max) = bounds_2d_to_3d(&b, 2700.0, 2400.0);
        assert_eq!(min, Vec3::new(0.0, 2700.0, 1000.0));
        assert_eq!(max, Vec3::new(4000.0, 5100.0, 4500.0));
    }

    #[test]
    fn unknown_zone_returns_default_off_white() {
        assert_eq!(zone_color("unknown"), Vec3::new(0.95, 0.95, 0.95));
    }
}
