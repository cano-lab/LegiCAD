//! Centred room labels for floor plans.
//!
//! Each room gets a two-line text label at its centroid: the friendly
//! name on top, the area on the bottom. The Python pipeline does the
//! same via `intelligent_dimensions.py`'s room-aware annotation pass;
//! this module ports just the labelling, not the chain logic.

use std::fmt::Write as _;

/// One room's data, in plan-view mm. `area_mm2` is the room area in
/// mm² (the QBD JSON's `area` field is mm² when the document's `unit`
/// is `mm`).
#[derive(Debug, Clone)]
pub struct RoomLabelInput {
    pub name: String,
    pub bounds_x: f32,
    pub bounds_y: f32,
    pub width: f32,
    pub height: f32,
    pub area_mm2: f32,
}

impl RoomLabelInput {
    /// Centroid of the room's rectangular bounds.
    #[must_use]
    pub fn center(&self) -> (f32, f32) {
        (
            self.bounds_x + self.width * 0.5,
            self.bounds_y + self.height * 0.5,
        )
    }
}

/// Render a single room label: two centred text lines (name above, area
/// below). `text_height` is the font size in the surrounding SVG's
/// coordinate space (mm) — typical for a permit floor plan is 250–400 mm.
#[must_use]
pub fn render_room_label(input: &RoomLabelInput, text_height: f32) -> String {
    let (cx, cy) = input.center();
    let area_m2 = input.area_mm2 / 1_000_000.0;
    let area_sqft = area_m2 * 10.7639;
    let line_spacing = text_height * 1.2;

    let mut s = String::with_capacity(256);
    let _ = writeln!(
        s,
        r##"    <text x="{cx}" y="{y}" font-family="Arial, sans-serif" font-size="{text_height}" text-anchor="middle" fill="#222">{name}</text>"##,
        y = cy - line_spacing * 0.5,
        name = escape_xml(&input.name),
    );
    let _ = writeln!(
        s,
        r##"    <text x="{cx}" y="{y}" font-family="Arial, sans-serif" font-size="{small}" text-anchor="middle" fill="#555">{area_m2:.1} m² ({area_sqft:.0} sqft)</text>"##,
        y = cy + line_spacing * 0.5,
        small = text_height * 0.7,
    );
    s
}

/// Render every room label in one pass, concatenated into a single SVG
/// fragment. Order of input is preserved; consumers usually want the
/// rooms sorted by id for deterministic output.
#[must_use]
pub fn render_room_labels(rooms: &[RoomLabelInput], text_height: f32) -> String {
    let mut s = String::with_capacity(rooms.len() * 256);
    for r in rooms {
        s.push_str(&render_room_label(r, text_height));
    }
    s
}

/// Minimal XML attribute escaping. `>` is technically not required in
/// attribute values but Python escapes it too, so keep parity easy.
fn escape_xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry_room() -> RoomLabelInput {
        RoomLabelInput {
            name: "Entry".into(),
            bounds_x: 0.0,
            bounds_y: 0.0,
            width: 1676.4,
            height: 2438.4,
            area_mm2: 4_087_733.8,
        }
    }

    #[test]
    fn center_is_midpoint_of_bounds() {
        let r = entry_room();
        let (cx, cy) = r.center();
        assert!((cx - 838.2).abs() < 0.01);
        assert!((cy - 1219.2).abs() < 0.01);
    }

    #[test]
    fn render_room_label_emits_two_text_lines() {
        let r = entry_room();
        let svg = render_room_label(&r, 300.0);
        assert_eq!(svg.matches("<text").count(), 2);
        assert!(svg.contains("Entry"));
        // 4 m² ≈ 43 sqft.
        assert!(svg.contains("4.1 m²"));
        assert!(svg.contains("44 sqft"));
    }

    #[test]
    fn render_room_labels_concatenates() {
        let rooms = vec![
            entry_room(),
            RoomLabelInput {
                name: "Kitchen".into(),
                bounds_x: 7124.7,
                bounds_y: 0.0,
                width: 3238.5,
                height: 2438.4,
                area_mm2: 7_896_758.4,
            },
        ];
        let svg = render_room_labels(&rooms, 300.0);
        assert_eq!(svg.matches("<text").count(), 4);
        assert!(svg.contains("Entry"));
        assert!(svg.contains("Kitchen"));
    }

    #[test]
    fn xml_escapes_special_chars_in_name() {
        let r = RoomLabelInput {
            name: "Tom & Jerry's <Room>".into(),
            ..entry_room()
        };
        let svg = render_room_label(&r, 200.0);
        assert!(svg.contains("Tom &amp; Jerry&apos;s &lt;Room&gt;"));
    }
}
