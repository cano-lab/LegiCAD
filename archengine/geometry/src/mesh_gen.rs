//! Procedural mesh generators for structural primitives.
//!
//! Port of the `arch::Geometry` namespace in `ArchEngine_kernel/src/mesh.cpp`
//! (the GPU `Mesh` buffer class is *not* ported — it belongs to the future
//! renderer crate, see `archengine-viewer`).
//!
//! Every generator returns a [`PrimitiveMesh`]: CPU vertices (position,
//! normal, colour, tex coord) plus `u32` indices, matching the C++ vertex
//! order and winding exactly so output can be diffed against legacy meshes.
//!
//! Winding convention (inherited): faces are **CW when viewed along the
//! stored vertex normal** — the legacy Vulkan renderer used CW front faces
//! via the viewport Y-flip. A future `wgpu` renderer must either set
//! `FrontFace::Cw` or flip the indices.

use crate::domain::{StressColors, Vertex};
use glam::{Vec2, Vec3};

/// Extrude a 2D polygon footprint into a 3D prism mesh.
/// 
/// This is the key function for converting massing envelopes from regime-params
/// into renderable geometry. The footprint is in XZ plane, extruded along +Y.
#[must_use]
pub fn create_extruded_polygon(footprint: &[Vec2], height: f32, color: Vec3) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();
    
    if footprint.len() < 3 {
        return mesh;
    }
    
    // Create bottom and top vertices
    let mut bottom_verts = Vec::with_capacity(footprint.len());
    let mut top_verts = Vec::with_capacity(footprint.len());
    
    for &pt in footprint {
        bottom_verts.push(Vec3::new(pt.x, 0.0, pt.y));
        top_verts.push(Vec3::new(pt.x, height, pt.y));
    }
    
    // Generate cap normals (up/down)
    let up_normal = Vec3::Y;
    let down_normal = -Vec3::Y;
    
    // Top cap (CCW when viewed from above)
    let base = mesh.vertices.len() as u32;
    for &vert in top_verts.iter() {
        let uv = Vec2::new(vert.x * 0.1, vert.z * 0.1);
        mesh.vertices.push(v(vert, up_normal, color, uv));
    }
    // Triangulate top cap (fan from first vertex)
    for i in 1..top_verts.len() - 1 {
        mesh.indices.extend_from_slice(&[base, base + i as u32, base + (i + 1) as u32]);
    }
    
    // Bottom cap (CW when viewed from below)
    let base = mesh.vertices.len() as u32;
    for &vert in bottom_verts.iter().rev() {
        let uv = Vec2::new(vert.x * 0.1, vert.z * 0.1);
        mesh.vertices.push(v(vert, down_normal, color, uv));
    }
    // Triangulate bottom cap
    let bottom_base = base;
    let n = bottom_verts.len();
    for i in 1..n - 1 {
        mesh.indices.extend_from_slice(&[bottom_base, bottom_base + (n - 1 - i) as u32, bottom_base + (n - i) as u32]);
    }
    
    // Side walls
    for i in 0..footprint.len() {
        let j = (i + 1) % footprint.len();
        let p0_bottom = bottom_verts[i];
        let p1_bottom = bottom_verts[j];
        let p0_top = top_verts[i];
        let p1_top = top_verts[j];
        
        // Compute outward normal for this edge
        let edge = Vec3::new(p1_bottom.x - p0_bottom.x, 0.0, p1_bottom.z - p0_bottom.z);
        let side_normal = Vec3::new(-edge.z, 0.0, edge.x).normalize();
        
        let base = mesh.vertices.len() as u32;
        
        // Add four corners of the quad
        for (pt, normal) in [
            (p0_bottom, side_normal),
            (p1_bottom, side_normal),
            (p1_top, side_normal),
            (p0_top, side_normal),
        ] {
            let uv = Vec2::new(pt.x * 0.1, pt.y * 0.1);
            mesh.vertices.push(v(pt, normal, color, uv));
        }
        
        // Add two triangles for the quad
        mesh.indices.extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    }
    
    mesh
}

/// Vertices + indices produced by a generator (the C++ returns
/// `std::pair<std::vector<Vertex>, std::vector<u32>>`).
#[derive(Debug, Clone, Default, PartialEq, serde::Serialize, serde::Deserialize)]
pub struct PrimitiveMesh {
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
}

impl PrimitiveMesh {
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.vertices.is_empty() || self.indices.is_empty()
    }
}

fn v(position: Vec3, normal: Vec3, color: Vec3, tex_coord: Vec2) -> Vertex {
    Vertex { position, normal, color, tex_coord, ..Default::default() }
}

/// World-projected UVs: 1 world unit = 1 texture tile. The C++ notes that
/// `fract()` breaks interpolation — wrapping is left to the sampler.
fn world_uv(pos: Vec3, normal: Vec3, uv_scale: f32) -> Vec2 {
    let (u_axis, v_axis) = if normal.y.abs() > 0.9 {
        (Vec3::X, Vec3::Z) // horizontal face — XZ
    } else if normal.x.abs() > normal.z.abs() {
        (Vec3::Z, Vec3::Y) // facing X — ZY
    } else {
        (Vec3::X, Vec3::Y) // facing Z — XY
    };
    Vec2::new(pos.dot(u_axis) * uv_scale, pos.dot(v_axis) * uv_scale)
}

/// Beam mesh: a box from `start` to `end`, keeping the "top" face upward
/// when the beam isn't near-vertical.
#[must_use]
pub fn create_beam(start: Vec3, end: Vec3, width: f32, height: f32, color: Vec3) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();

    let dir = (end - start).normalize();
    let world_up = Vec3::Y;

    let (right, local_up) = if dir.dot(world_up).abs() > 0.99 {
        // Nearly vertical — use world X as reference.
        let local_up = Vec3::X.cross(dir).normalize();
        let right = dir.cross(local_up).normalize();
        (right, local_up)
    } else {
        // Project world up onto the plane perpendicular to the beam.
        let local_up = (world_up - dir * world_up.dot(dir)).normalize();
        let right = dir.cross(local_up).normalize();
        (right, local_up)
    };

    let hw = width * 0.5;
    let hh = height * 0.5;

    let corners = [
        start - right * hw - local_up * hh, // 0 back-bottom-left
        start + right * hw - local_up * hh, // 1 back-bottom-right
        start + right * hw + local_up * hh, // 2 back-top-right
        start - right * hw + local_up * hh, // 3 back-top-left
        end - right * hw - local_up * hh,   // 4 front-bottom-left
        end + right * hw - local_up * hh,   // 5 front-bottom-right
        end + right * hw + local_up * hh,   // 6 front-top-right
        end - right * hw + local_up * hh,   // 7 front-top-left
    ];

    // C++ uses uvScale = 0.001 here ("1mm to UV units").
    let mut add_face = |i0: usize, i1: usize, i2: usize, i3: usize, normal: Vec3| {
        let base = mesh.vertices.len() as u32;
        for &i in &[i0, i1, i2, i3] {
            mesh.vertices
                .push(v(corners[i], normal, color, world_uv(corners[i], normal, 0.001)));
        }
        mesh.indices
            .extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    };

    add_face(0, 1, 2, 3, -dir); // back
    add_face(5, 4, 7, 6, dir); // front
    add_face(4, 0, 3, 7, -right); // left
    add_face(1, 5, 6, 2, right); // right
    add_face(3, 2, 6, 7, local_up); // top
    add_face(4, 5, 1, 0, -local_up); // bottom

    mesh
}

/// Column mesh: vertical box with `position` at the bottom centre.
#[must_use]
pub fn create_column(
    position: Vec3,
    width: f32,
    depth: f32,
    height: f32,
    color: Vec3,
) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();
    let hw = width * 0.5;
    let hd = depth * 0.5;

    let corners = [
        position + Vec3::new(-hw, 0.0, -hd), // 0 bottom-back-left
        position + Vec3::new(hw, 0.0, -hd),  // 1 bottom-back-right
        position + Vec3::new(hw, 0.0, hd),   // 2 bottom-front-right
        position + Vec3::new(-hw, 0.0, hd),  // 3 bottom-front-left
        position + Vec3::new(-hw, height, -hd), // 4 top-back-left
        position + Vec3::new(hw, height, -hd),  // 5 top-back-right
        position + Vec3::new(hw, height, hd),   // 6 top-front-right
        position + Vec3::new(-hw, height, hd),  // 7 top-front-left
    ];

    let mut add_face = |i0: usize, i1: usize, i2: usize, i3: usize, normal: Vec3| {
        let base = mesh.vertices.len() as u32;
        for &i in &[i0, i1, i2, i3] {
            mesh.vertices
                .push(v(corners[i], normal, color, world_uv(corners[i], normal, 1.0)));
        }
        mesh.indices
            .extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    };

    add_face(0, 1, 5, 4, Vec3::NEG_Z); // back
    add_face(2, 3, 7, 6, Vec3::Z); // front
    add_face(3, 0, 4, 7, Vec3::NEG_X); // left
    add_face(1, 2, 6, 5, Vec3::X); // right
    add_face(4, 5, 6, 7, Vec3::Y); // top
    add_face(3, 2, 1, 0, Vec3::NEG_Y); // bottom

    mesh
}

/// Floor slab: a column box dropped by its own thickness, so `position` is
/// the slab's top surface centre.
#[must_use]
pub fn create_floor_slab(
    position: Vec3,
    width: f32,
    depth: f32,
    thickness: f32,
    color: Vec3,
) -> PrimitiveMesh {
    create_column(position - Vec3::new(0.0, thickness, 0.0), width, depth, thickness, color)
}

/// Deflected beam: segmented box curving downward under load, with a
/// parabolic deflection profile (max at centre, zero at ends).
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn create_deflected_beam(
    start: Vec3,
    end: Vec3,
    width: f32,
    height: f32,
    deflection: f32,
    segments: u32,
    color: Vec3,
) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();

    let length = (end - start).length();
    let dir = (end - start).normalize();

    let mut up = Vec3::Y;
    if dir.dot(up).abs() > 0.99 {
        up = Vec3::X;
    }
    let right = dir.cross(up).normalize();
    let local_up = right.cross(dir).normalize();

    let hw = width * 0.5;
    let hh = height * 0.5;

    for i in 0..=segments {
        let t = i as f32 / segments as f32;
        let mut pos = start + dir * (length * t);
        let deflection_factor = 4.0 * t * (1.0 - t); // parabola
        pos -= local_up * (deflection * deflection_factor);

        mesh.vertices.push(v(pos - right * hw - local_up * hh, -local_up, color, Vec2::ZERO));
        mesh.vertices.push(v(pos + right * hw - local_up * hh, -local_up, color, Vec2::ZERO));
        mesh.vertices.push(v(pos + right * hw + local_up * hh, local_up, color, Vec2::ZERO));
        mesh.vertices.push(v(pos - right * hw + local_up * hh, local_up, color, Vec2::ZERO));
    }

    for i in 0..segments {
        let base = i * 4;
        // Bottom
        mesh.indices.extend_from_slice(&[base, base + 4, base + 5, base, base + 5, base + 1]);
        // Right
        mesh.indices.extend_from_slice(&[base + 1, base + 5, base + 6, base + 1, base + 6, base + 2]);
        // Top
        mesh.indices.extend_from_slice(&[base + 2, base + 6, base + 7, base + 2, base + 7, base + 3]);
        // Left
        mesh.indices.extend_from_slice(&[base + 3, base + 7, base + 4, base + 3, base + 4, base]);
    }

    // Start cap (reversed winding, faces −dir).
    let start_base = mesh.vertices.len() as u32;
    mesh.vertices.push(v(start - right * hw - local_up * hh, -dir, color, Vec2::ZERO));
    mesh.vertices.push(v(start + right * hw - local_up * hh, -dir, color, Vec2::ZERO));
    mesh.vertices.push(v(start + right * hw + local_up * hh, -dir, color, Vec2::ZERO));
    mesh.vertices.push(v(start - right * hw + local_up * hh, -dir, color, Vec2::ZERO));
    mesh.indices.extend_from_slice(&[
        start_base, start_base + 2, start_base + 1,
        start_base, start_base + 3, start_base + 2,
    ]);

    // End cap.
    let end_base = mesh.vertices.len() as u32;
    mesh.vertices.push(v(end - right * hw - local_up * hh, dir, color, Vec2::ZERO));
    mesh.vertices.push(v(end + right * hw - local_up * hh, dir, color, Vec2::ZERO));
    mesh.vertices.push(v(end + right * hw + local_up * hh, dir, color, Vec2::ZERO));
    mesh.vertices.push(v(end - right * hw + local_up * hh, dir, color, Vec2::ZERO));
    mesh.indices.extend_from_slice(&[
        end_base, end_base + 1, end_base + 2,
        end_base, end_base + 2, end_base + 3,
    ]);

    mesh
}

/// Reference grid: thin quads just below Y=0 to avoid Z-fighting.
#[must_use]
pub fn create_grid(size: f32, spacing: f32, color: Vec3) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();
    let half_size = size * 0.5;
    let line_count = (size / spacing) as i32 + 1;
    let normal = Vec3::Y;
    let grid_y = -0.05;

    for i in 0..line_count {
        let z = -half_size + i as f32 * spacing;
        let base = mesh.vertices.len() as u32;
        mesh.vertices.push(v(Vec3::new(-half_size, grid_y, z), normal, color, Vec2::ZERO));
        mesh.vertices.push(v(Vec3::new(half_size, grid_y, z), normal, color, Vec2::ZERO));
        mesh.vertices.push(v(Vec3::new(-half_size, grid_y + 0.01, z), normal, color, Vec2::ZERO));
        mesh.vertices.push(v(Vec3::new(half_size, grid_y + 0.01, z), normal, color, Vec2::ZERO));
        mesh.indices
            .extend_from_slice(&[base, base + 1, base + 3, base, base + 3, base + 2]);
    }

    for i in 0..line_count {
        let x = -half_size + i as f32 * spacing;
        let base = mesh.vertices.len() as u32;
        mesh.vertices.push(v(Vec3::new(x, grid_y, -half_size), normal, color, Vec2::ZERO));
        mesh.vertices.push(v(Vec3::new(x, grid_y, half_size), normal, color, Vec2::ZERO));
        mesh.vertices.push(v(Vec3::new(x, grid_y + 0.01, -half_size), normal, color, Vec2::ZERO));
        mesh.vertices.push(v(Vec3::new(x, grid_y + 0.01, half_size), normal, color, Vec2::ZERO));
        mesh.indices
            .extend_from_slice(&[base, base + 1, base + 3, base, base + 3, base + 2]);
    }

    mesh
}

/// UV sphere (equirectangular projection), centred at the origin.
#[must_use]
pub fn create_sphere(radius: f32, rings: u32, sectors: u32, color: Vec3) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();
    let pi = std::f32::consts::PI;

    for r in 0..=rings {
        let theta = r as f32 / rings as f32 * pi; // 0..PI
        let (sin_theta, cos_theta) = theta.sin_cos();
        for s in 0..=sectors {
            let phi = s as f32 / sectors as f32 * 2.0 * pi; // 0..2PI
            let (sin_phi, cos_phi) = phi.sin_cos();
            let pos = Vec3::new(
                radius * sin_theta * cos_phi,
                radius * cos_theta,
                radius * sin_theta * sin_phi,
            );
            let uv = Vec2::new(s as f32 / sectors as f32, r as f32 / rings as f32);
            mesh.vertices.push(v(pos, pos.normalize(), color, uv));
        }
    }

    for r in 0..rings {
        for s in 0..sectors {
            let i0 = r * (sectors + 1) + s;
            let i1 = i0 + 1;
            let i2 = (r + 1) * (sectors + 1) + s;
            let i3 = i2 + 1;
            mesh.indices.extend_from_slice(&[i0, i2, i1]);
            mesh.indices.extend_from_slice(&[i1, i2, i3]);
        }
    }

    mesh
}

/// Arrow for load visualisation: box shaft + 6-sided cone head.
#[must_use]
pub fn create_arrow(start: Vec3, end: Vec3, head_size: f32, color: Vec3) -> PrimitiveMesh {
    let dir = (end - start).normalize();
    let mut up = Vec3::Y;
    if dir.dot(up).abs() > 0.99 {
        up = Vec3::X;
    }
    let right = dir.cross(up).normalize();
    let local_up = right.cross(dir).normalize();

    let shaft_radius = head_size * 0.15;
    let head_base = end - dir * head_size;

    // Shaft.
    let mut mesh = create_beam(start, head_base, shaft_radius * 2.0, shaft_radius * 2.0, color);

    // Cone head.
    let base_index = mesh.vertices.len() as u32;
    let cone_segments = 6;
    mesh.vertices.push(v(end, dir, color, Vec2::ZERO)); // tip
    for i in 0..cone_segments {
        let angle = i as f32 / cone_segments as f32 * 2.0 * std::f32::consts::PI;
        let offset = right * angle.cos() * head_size * 0.5 + local_up * angle.sin() * head_size * 0.5;
        mesh.vertices
            .push(v(head_base + offset, (offset + dir * 0.5).normalize(), color, Vec2::ZERO));
    }
    for i in 0..cone_segments {
        let next = (i + 1) % cone_segments;
        mesh.indices
            .extend_from_slice(&[base_index, base_index + 1 + i, base_index + 1 + next]);
    }

    // Base cap.
    let center_index = mesh.vertices.len() as u32;
    mesh.vertices.push(v(head_base, -dir, color, Vec2::ZERO));
    for i in 0..cone_segments {
        let next = (i + 1) % cone_segments;
        mesh.indices
            .extend_from_slice(&[center_index, base_index + 1 + next, base_index + 1 + i]);
    }

    mesh
}

/// Apply stress colouring to every vertex (green → yellow → red gradient).
pub fn apply_stress_coloring(vertices: &mut [Vertex], stress: f32) {
    let color = StressColors::from_stress(stress);
    for vertex in vertices {
        vertex.color = color;
    }
}

/// Shared helper from the door/window generators: append an axis-aligned
/// box (`min_p`..`max_p`) with per-face normals and no UVs.
fn add_box(mesh: &mut PrimitiveMesh, min_p: Vec3, max_p: Vec3, color: Vec3) {
    let c = [
        Vec3::new(min_p.x, min_p.y, min_p.z),
        Vec3::new(max_p.x, min_p.y, min_p.z),
        Vec3::new(max_p.x, min_p.y, max_p.z),
        Vec3::new(min_p.x, min_p.y, max_p.z),
        Vec3::new(min_p.x, max_p.y, min_p.z),
        Vec3::new(max_p.x, max_p.y, min_p.z),
        Vec3::new(max_p.x, max_p.y, max_p.z),
        Vec3::new(min_p.x, max_p.y, max_p.z),
    ];

    let mut add_face = |i0: usize, i1: usize, i2: usize, i3: usize, n: Vec3| {
        let b = mesh.vertices.len() as u32;
        for &i in &[i0, i1, i2, i3] {
            mesh.vertices.push(v(c[i], n, color, Vec2::ZERO));
        }
        mesh.indices.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
    };

    add_face(0, 1, 5, 4, Vec3::NEG_Z); // front
    add_face(2, 3, 7, 6, Vec3::Z); // back
    add_face(3, 0, 4, 7, Vec3::NEG_X); // left
    add_face(1, 2, 6, 5, Vec3::X); // right
    add_face(4, 5, 6, 7, Vec3::Y); // top
    add_face(3, 2, 1, 0, Vec3::NEG_Y); // bottom
}

/// Door with frame, recessed panel, and a brass handle at ~3 ft.
/// `position` is the bottom centre of the opening.
#[must_use]
pub fn create_door(
    position: Vec3,
    width: f32,
    height: f32,
    depth: f32,
    color: Vec3,
) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();
    let hw = width * 0.5;
    let hd = depth * 0.5;

    let frame_color = Vec3::new(0.35, 0.22, 0.12); // dark wood frame
    let panel_color = color;
    let handle_color = Vec3::new(0.7, 0.55, 0.2); // brass

    let frame_width = 0.25;

    // Frame: left vertical, right vertical, top horizontal.
    add_box(
        &mut mesh,
        position + Vec3::new(-hw, 0.0, -hd),
        position + Vec3::new(-hw + frame_width, height, hd),
        frame_color,
    );
    add_box(
        &mut mesh,
        position + Vec3::new(hw - frame_width, 0.0, -hd),
        position + Vec3::new(hw, height, hd),
        frame_color,
    );
    add_box(
        &mut mesh,
        position + Vec3::new(-hw + frame_width, height - frame_width, -hd),
        position + Vec3::new(hw - frame_width, height, hd),
        frame_color,
    );

    // Main panel, recessed slightly.
    let panel_inset = frame_width * 0.5;
    add_box(
        &mut mesh,
        position + Vec3::new(-hw + frame_width, 0.0, -hd + panel_inset),
        position + Vec3::new(hw - frame_width, height - frame_width, hd - panel_inset),
        panel_color,
    );

    // Handle (right side, ~3 ft up) — only if it fits.
    let handle_height = 3.0;
    let handle_size = 0.15;
    if handle_height < height - frame_width {
        add_box(
            &mut mesh,
            position + Vec3::new(hw - frame_width - 0.4, handle_height - handle_size, hd - 0.1),
            position + Vec3::new(hw - frame_width - 0.1, handle_height + handle_size, hd + 0.15),
            handle_color,
        );
    }

    mesh
}

/// Window with frame, protruding sill, recessed glass, and cross mullions.
/// `position` is the bottom centre of the opening.
#[must_use]
pub fn create_window(
    position: Vec3,
    width: f32,
    height: f32,
    depth: f32,
    color: Vec3,
) -> PrimitiveMesh {
    let _ = color; // C++ ignores the passed colour too — parts have fixed colours
    let mut mesh = PrimitiveMesh::default();
    let hw = width * 0.5;
    let hd = depth * 0.5;

    let frame_color = Vec3::new(0.9, 0.9, 0.92); // white painted frame
    let glass_color = Vec3::new(0.7, 0.85, 0.95); // light blue tinted glass
    let sill_color = Vec3::new(0.85, 0.85, 0.87);

    let frame_width = 0.15;
    let mullion_width = 0.08;

    // Frame: left, right, top.
    add_box(
        &mut mesh,
        position + Vec3::new(-hw, 0.0, -hd),
        position + Vec3::new(-hw + frame_width, height, hd),
        frame_color,
    );
    add_box(
        &mut mesh,
        position + Vec3::new(hw - frame_width, 0.0, -hd),
        position + Vec3::new(hw, height, hd),
        frame_color,
    );
    add_box(
        &mut mesh,
        position + Vec3::new(-hw + frame_width, height - frame_width, -hd),
        position + Vec3::new(hw - frame_width, height, hd),
        frame_color,
    );

    // Sill: slightly thicker and protruding.
    let sill_protrusion = 0.1;
    add_box(
        &mut mesh,
        position + Vec3::new(-hw - sill_protrusion, 0.0, -hd - sill_protrusion),
        position + Vec3::new(hw + sill_protrusion, frame_width * 1.2, hd),
        sill_color,
    );

    // Glass pane: thin, recessed.
    let glass_inset = depth * 0.3;
    add_box(
        &mut mesh,
        position + Vec3::new(-hw + frame_width, frame_width * 1.2, -glass_inset),
        position + Vec3::new(hw - frame_width, height - frame_width, glass_inset),
        glass_color,
    );

    // Mullions (cross dividers).
    let inner_height = height - frame_width - frame_width * 1.2;
    let mid_height = frame_width * 1.2 + inner_height * 0.5;
    add_box(
        &mut mesh,
        position + Vec3::new(-hw + frame_width, mid_height - mullion_width * 0.5, -hd * 0.5),
        position + Vec3::new(hw - frame_width, mid_height + mullion_width * 0.5, hd * 0.5),
        frame_color,
    );
    add_box(
        &mut mesh,
        position + Vec3::new(-mullion_width * 0.5, frame_width * 1.2, -hd * 0.5),
        position + Vec3::new(mullion_width * 0.5, height - frame_width, hd * 0.5),
        frame_color,
    );

    mesh
}

/// Roof: flat box (with 2 ft eaves) for `pitch <= 0.01`, otherwise a hip
/// roof — pyramid when the footprint is nearly square, ridged otherwise.
#[must_use]
pub fn create_roof(
    position: Vec3,
    width: f32,
    depth: f32,
    height: f32,
    pitch: f32,
    color: Vec3,
) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();

    let overhang = 2.0; // 2 ft
    let hw = width * 0.5 + overhang;
    let hd = depth * 0.5 + overhang;

    if pitch <= 0.01 {
        // Flat roof with overhang.
        let corners = [
            position + Vec3::new(-hw, 0.0, -hd),
            position + Vec3::new(hw, 0.0, -hd),
            position + Vec3::new(hw, 0.0, hd),
            position + Vec3::new(-hw, 0.0, hd),
            position + Vec3::new(-hw, height, -hd),
            position + Vec3::new(hw, height, -hd),
            position + Vec3::new(hw, height, hd),
            position + Vec3::new(-hw, height, hd),
        ];
        let mut add_face = |i0: usize, i1: usize, i2: usize, i3: usize, n: Vec3| {
            let b = mesh.vertices.len() as u32;
            for &i in &[i0, i1, i2, i3] {
                mesh.vertices.push(v(corners[i], n, color, Vec2::ZERO));
            }
            mesh.indices.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
        };
        add_face(0, 1, 5, 4, Vec3::NEG_Z);
        add_face(2, 3, 7, 6, Vec3::Z);
        add_face(3, 0, 4, 7, Vec3::NEG_X);
        add_face(1, 2, 6, 5, Vec3::X);
        add_face(4, 5, 6, 7, Vec3::Y);
        add_face(3, 2, 1, 0, Vec3::NEG_Y);
    } else {
        let ridge_height = height + pitch * hw.min(hd);
        let p0 = position + Vec3::new(-hw, 0.0, -hd); // back-left
        let p1 = position + Vec3::new(hw, 0.0, -hd); // back-right
        let p2 = position + Vec3::new(hw, 0.0, hd); // front-right
        let p3 = position + Vec3::new(-hw, 0.0, hd); // front-left

        let ridge_len = ((width - depth) * 0.5).max(0.0);

        let add_tri = |mesh: &mut PrimitiveMesh, a: Vec3, b: Vec3, c: Vec3, n: Vec3| {
            let base = mesh.vertices.len() as u32;
            for &p in &[a, b, c] {
                mesh.vertices.push(v(p, n, color, Vec2::ZERO));
            }
            mesh.indices.extend_from_slice(&[base, base + 1, base + 2]);
        };
        let add_quad = |mesh: &mut PrimitiveMesh, a: Vec3, b: Vec3, c: Vec3, d: Vec3, n: Vec3| {
            let base = mesh.vertices.len() as u32;
            for &p in &[a, b, c, d] {
                mesh.vertices.push(v(p, n, color, Vec2::ZERO));
            }
            mesh.indices
                .extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
        };

        if ridge_len < 1.0 {
            // Pyramid: 4 triangular faces at an apex.
            let apex = position + Vec3::new(0.0, ridge_height, 0.0);
            add_tri(&mut mesh, p3, p2, apex, (p2 - p3).cross(apex - p3).normalize()); // front
            add_tri(&mut mesh, p2, p1, apex, (p1 - p2).cross(apex - p2).normalize()); // right
            add_tri(&mut mesh, p1, p0, apex, (p0 - p1).cross(apex - p1).normalize()); // back
            add_tri(&mut mesh, p0, p3, apex, (p3 - p0).cross(apex - p0).normalize()); // left
        } else {
            // Hip roof with a ridge line.
            let r0 = position + Vec3::new(-ridge_len, ridge_height, 0.0);
            let r1 = position + Vec3::new(ridge_len, ridge_height, 0.0);
            add_quad(&mut mesh, p3, p2, r1, r0, (p2 - p3).cross(r0 - p3).normalize()); // front
            add_quad(&mut mesh, p1, p0, r0, r1, (p0 - p1).cross(r1 - p1).normalize()); // back
            add_tri(&mut mesh, p2, p1, r1, (p1 - p2).cross(r1 - p2).normalize()); // right hip
            add_tri(&mut mesh, p0, p3, r0, (p3 - p0).cross(r0 - p0).normalize()); // left hip
        }
    }

    mesh
}

/// Gable roof: two sloped planes meeting at a ridge running along Z.
/// `position` is the footprint centre at the wall base; slopes start at
/// `wall_height`.
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn create_gable_roof(
    position: Vec3,
    width: f32,
    depth: f32,
    wall_height: f32,
    pitch: f32,
    overhang: f32,
    color: Vec3,
) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();

    let hw = width * 0.5 + overhang;
    let hd = depth * 0.5 + overhang;
    let ridge_height = wall_height + pitch * (width * 0.5);

    let p0 = position + Vec3::new(-hw, wall_height, -hd);
    let p1 = position + Vec3::new(hw, wall_height, -hd);
    let p2 = position + Vec3::new(hw, wall_height, hd);
    let p3 = position + Vec3::new(-hw, wall_height, hd);
    let r0 = position + Vec3::new(0.0, ridge_height, -hd);
    let r1 = position + Vec3::new(0.0, ridge_height, hd);

    let mut add_quad = |a: Vec3, b: Vec3, c: Vec3, d: Vec3, n: Vec3| {
        let base = mesh.vertices.len() as u32;
        for &p in &[a, b, c, d] {
            mesh.vertices.push(v(p, n, color, Vec2::ZERO));
        }
        mesh.indices
            .extend_from_slice(&[base, base + 1, base + 2, base, base + 2, base + 3]);
    };

    // Left slope (−X side).
    add_quad(p0, p3, r1, r0, (p3 - p0).cross(r0 - p0).normalize());
    // Right slope (+X side).
    add_quad(p1, r0, r1, p2, (r0 - p1).cross(p2 - p1).normalize());

    mesh
}

/// Gable wall: pentagon (rectangle with triangular top), front and back
/// faces at ±thickness/2. `position` is the bottom centre.
#[must_use]
pub fn create_gable_wall(
    position: Vec3,
    width: f32,
    wall_height: f32,
    gable_height: f32,
    thickness: f32,
    color: Vec3,
) -> PrimitiveMesh {
    let mut mesh = PrimitiveMesh::default();
    let hw = width * 0.5;
    let ht = thickness * 0.5;

    let p0 = position + Vec3::new(-hw, 0.0, 0.0);
    let p1 = position + Vec3::new(hw, 0.0, 0.0);
    let p2 = position + Vec3::new(hw, wall_height, 0.0);
    let p3 = position + Vec3::new(0.0, wall_height + gable_height, 0.0);
    let p4 = position + Vec3::new(-hw, wall_height, 0.0);

    // Front pentagon (+Z), fan-triangulated from p0.
    let base = mesh.vertices.len() as u32;
    for &p in &[p0, p1, p2, p3, p4] {
        mesh.vertices.push(v(p + Vec3::new(0.0, 0.0, ht), Vec3::Z, color, Vec2::ZERO));
    }
    mesh.indices.extend_from_slice(&[
        base, base + 1, base + 2,
        base, base + 2, base + 3,
        base, base + 3, base + 4,
    ]);

    // Back pentagon (−Z), reversed order for outward winding.
    let base = mesh.vertices.len() as u32;
    for &p in &[p0, p4, p3, p2, p1] {
        mesh.vertices.push(v(p + Vec3::new(0.0, 0.0, -ht), Vec3::NEG_Z, color, Vec2::ZERO));
    }
    mesh.indices.extend_from_slice(&[
        base, base + 1, base + 2,
        base, base + 2, base + 3,
        base, base + 3, base + 4,
    ]);

    mesh
}

/// CSG helpers. The C++ "CSG" here is mesh combination + analytic wall
/// openings — true BSP boolean ops live in `pk-csg` (vendored as
/// `crate::object`'s sibling in the parametric kernel; see
/// `docs/PARAMETRIC_KERNEL_SPEC.md`).
pub mod csg {
    use super::{PrimitiveMesh, v};
    use glam::{Vec3, Vec3Swizzles};

    /// Union: concatenate two meshes (index-offset append, as in the C++).
    #[must_use]
    pub fn mesh_union(a: &PrimitiveMesh, b: &PrimitiveMesh) -> PrimitiveMesh {
        let mut vertices = a.vertices.clone();
        let mut indices = a.indices.clone();
        let offset = vertices.len() as u32;
        vertices.extend_from_slice(&b.vertices);
        indices.extend(b.indices.iter().map(|i| i + offset));
        PrimitiveMesh { vertices, indices }
    }

    /// Wall with one rectangular opening, built from 4 analytic strips
    /// (bottom / top / left / right around the cutout).
    ///
    /// `opening_pos.x` = offset along the wall from `wall_start`;
    /// `opening_pos.y` = height of the opening's sill from the floor.
    #[must_use]
    #[allow(clippy::too_many_arguments)]
    pub fn wall_with_opening(
        wall_start: Vec3,
        wall_end: Vec3,
        wall_height: f32,
        thickness: f32,
        opening_pos: Vec3,
        opening_width: f32,
        opening_height: f32,
        color: Vec3,
    ) -> PrimitiveMesh {
        let mut mesh = PrimitiveMesh::default();

        let wall_dir = wall_end - wall_start;
        let wall_length = wall_dir.xz().length();
        if wall_length < 0.01 {
            return mesh;
        }
        let dir = wall_dir.xz().normalize();
        let dir3 = Vec3::new(dir.x, 0.0, dir.y);
        let perp = Vec3::new(-dir.y, 0.0, dir.x);
        let ht = thickness * 0.5;

        let open_left = opening_pos.x.clamp(0.0, wall_length);
        let open_right = (opening_pos.x + opening_width).clamp(0.0, wall_length);
        let open_bottom = opening_pos.y.clamp(0.0, wall_height);
        let open_top = (opening_pos.y + opening_height).clamp(0.0, wall_height);

        let mut add_segment = |along_start: f32, along_end: f32, y_start: f32, y_end: f32| {
            if along_end <= along_start || y_end <= y_start {
                return;
            }
            let mut corners = [Vec3::ZERO; 8];
            for (i, corner) in corners.iter_mut().enumerate() {
                let along = if i & 1 != 0 { along_end } else { along_start };
                let y = if i & 2 != 0 { y_end } else { y_start };
                let p = if i & 4 != 0 { ht } else { -ht };
                *corner = wall_start + dir3 * along + Vec3::new(0.0, y, 0.0) + perp * p;
            }
            let add_face = |mesh: &mut PrimitiveMesh, i0: usize, i1: usize, i2: usize, i3: usize, n: Vec3| {
                let b = mesh.vertices.len() as u32;
                for &i in &[i0, i1, i2, i3] {
                    mesh.vertices.push(v(corners[i], n, color, glam::Vec2::ZERO));
                }
                mesh.indices.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
            };
            add_face(&mut mesh, 4, 5, 7, 6, perp); // front
            add_face(&mut mesh, 1, 0, 2, 3, -perp); // back
            add_face(&mut mesh, 2, 6, 7, 3, Vec3::Y); // top
            add_face(&mut mesh, 0, 1, 5, 4, Vec3::NEG_Y); // bottom
            add_face(&mut mesh, 0, 4, 6, 2, -dir3); // left (toward wall start)
            add_face(&mut mesh, 5, 1, 3, 7, dir3); // right (toward wall end)
        };

        // 1. Bottom strip (full width, floor → sill).
        if open_bottom > 0.01 {
            add_segment(0.0, wall_length, 0.0, open_bottom);
        }
        // 2. Top strip (full width, opening top → ceiling).
        if open_top < wall_height - 0.01 {
            add_segment(0.0, wall_length, open_top, wall_height);
        }
        // 3. Left strip (start → opening left, at opening height).
        if open_left > 0.01 {
            add_segment(0.0, open_left, open_bottom, open_top);
        }
        // 4. Right strip (opening right → end, at opening height).
        if open_right < wall_length - 0.01 {
            add_segment(open_right, wall_length, open_bottom, open_top);
        }

        mesh
    }

    /// Wall with multiple rectangular cutouts. Each opening is
    /// `[offset_along_wall, width, sill_height, height]`.
    ///
    /// Splits the wall into vertical columns at every opening edge, then
    /// fills each column around the gaps that overlap it.
    #[must_use]
    pub fn wall_with_multiple_openings(
        wall_start: Vec3,
        wall_end: Vec3,
        wall_height: f32,
        thickness: f32,
        openings: &[[f32; 4]],
        color: Vec3,
    ) -> PrimitiveMesh {
        let mut mesh = PrimitiveMesh::default();

        let wall_dir = wall_end - wall_start;
        let wall_length = wall_dir.xz().length();
        if wall_length < 0.01 {
            return mesh;
        }
        let dir = wall_dir.xz().normalize();
        let dir3 = Vec3::new(dir.x, 0.0, dir.y);
        let perp = Vec3::new(-dir.y, 0.0, dir.x);
        let ht = thickness * 0.5;

        let mut add_segment = |along_start: f32, along_end: f32, y_start: f32, y_end: f32| {
            if along_end <= along_start + 0.01 || y_end <= y_start + 0.01 {
                return;
            }
            let mut corners = [Vec3::ZERO; 8];
            for (i, corner) in corners.iter_mut().enumerate() {
                let along = if i & 1 != 0 { along_end } else { along_start };
                let y = if i & 2 != 0 { y_end } else { y_start };
                let p = if i & 4 != 0 { ht } else { -ht };
                *corner = wall_start + dir3 * along + Vec3::new(0.0, y, 0.0) + perp * p;
            }
            let add_face = |mesh: &mut PrimitiveMesh, i0: usize, i1: usize, i2: usize, i3: usize, n: Vec3| {
                let b = mesh.vertices.len() as u32;
                for &i in &[i0, i1, i2, i3] {
                    mesh.vertices.push(v(corners[i], n, color, glam::Vec2::ZERO));
                }
                mesh.indices.extend_from_slice(&[b, b + 1, b + 2, b, b + 2, b + 3]);
            };
            add_face(&mut mesh, 4, 5, 7, 6, perp);
            add_face(&mut mesh, 1, 0, 2, 3, -perp);
            add_face(&mut mesh, 2, 6, 7, 3, Vec3::Y);
            add_face(&mut mesh, 0, 1, 5, 4, Vec3::NEG_Y);
            add_face(&mut mesh, 0, 4, 6, 2, -dir3);
            add_face(&mut mesh, 5, 1, 3, 7, dir3);
        };

        if openings.is_empty() {
            add_segment(0.0, wall_length, 0.0, wall_height);
            return mesh;
        }

        // Sort openings by offset.
        let mut sorted = openings.to_vec();
        sorted.sort_by(|a, b| a[0].partial_cmp(&b[0]).unwrap_or(std::cmp::Ordering::Equal));

        // Column boundaries at every opening edge.
        let mut x_boundaries = vec![0.0];
        for op in &sorted {
            x_boundaries.push(op[0].clamp(0.0, wall_length));
            x_boundaries.push((op[0] + op[1]).clamp(0.0, wall_length));
        }
        x_boundaries.push(wall_length);
        x_boundaries.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        x_boundaries.dedup_by(|a, b| (*a - *b).abs() < f32::EPSILON);

        for pair in x_boundaries.windows(2) {
            let (col_left, col_right) = (pair[0], pair[1]);

            // Openings overlapping this column → vertical gaps.
            let mut y_gaps: Vec<(f32, f32)> = sorted
                .iter()
                .filter_map(|op| {
                    let op_left = op[0].clamp(0.0, wall_length);
                    let op_right = (op[0] + op[1]).clamp(0.0, wall_length);
                    if op_left < col_right && op_right > col_left {
                        let bottom = op[2].clamp(0.0, wall_height);
                        let top = (op[2] + op[3]).clamp(0.0, wall_height);
                        Some((bottom, top))
                    } else {
                        None
                    }
                })
                .collect();

            if y_gaps.is_empty() {
                add_segment(col_left, col_right, 0.0, wall_height);
            } else {
                y_gaps.sort_by(|a, b| a.0.partial_cmp(&b.0).unwrap_or(std::cmp::Ordering::Equal));
                let mut current_y = 0.0;
                for (bottom, top) in y_gaps {
                    if bottom > current_y {
                        add_segment(col_left, col_right, current_y, bottom);
                    }
                    current_y = current_y.max(top);
                }
                if current_y < wall_height {
                    add_segment(col_left, col_right, current_y, wall_height);
                }
            }
        }

        mesh
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const GREY: Vec3 = Vec3::new(0.7, 0.7, 0.7);

    /// Stored vertex normals must be unit-length and finite. (Winding is
    /// *not* asserted: the C++ generators mix conventions — see module docs.)
    fn normals_are_unit(mesh: &PrimitiveMesh) -> bool {
        mesh.vertices
            .iter()
            .all(|vt| vt.normal.is_finite() && (vt.normal.length() - 1.0).abs() < 1e-4)
    }

    #[test]
    fn beam_has_6_faces_and_outward_normals() {
        let m = create_beam(Vec3::ZERO, Vec3::new(10.0, 0.0, 0.0), 0.5, 1.0, GREY);
        assert_eq!(m.vertices.len(), 24); // 4 per face, 6 faces
        assert_eq!(m.indices.len(), 36);
        assert!(normals_are_unit(&m));
    }

    #[test]
    fn vertical_beam_uses_x_reference() {
        // Near-vertical beam must not produce degenerate normals.
        let m = create_beam(Vec3::ZERO, Vec3::new(0.0, 9.0, 0.0), 0.5, 0.5, GREY);
        assert!(m.vertices.iter().all(|vt| vt.normal.is_finite()));
        assert!(normals_are_unit(&m));
    }

    #[test]
    fn column_and_slab_dimensions() {
        let col = create_column(Vec3::ZERO, 2.0, 2.0, 9.0, GREY);
        assert_eq!(col.vertices.len(), 24);
        let top_y = col.vertices.iter().map(|v| v.position.y).fold(0.0, f32::max);
        assert!((top_y - 9.0).abs() < 1e-6);

        // Slab position is the top surface: a 0.5-thick slab tops out at y=0.
        let slab = create_floor_slab(Vec3::ZERO, 30.0, 40.0, 0.5, GREY);
        let slab_top = slab.vertices.iter().map(|v| v.position.y).fold(f32::NEG_INFINITY, f32::max);
        assert!(slab_top.abs() < 1e-6);
    }

    #[test]
    fn deflected_beam_sags_most_at_centre() {
        let m = create_deflected_beam(Vec3::ZERO, Vec3::new(20.0, 0.0, 0.0), 1.0, 1.0, 0.5, 16, GREY);
        // 4 verts × 17 sections + 8 cap verts.
        assert_eq!(m.vertices.len(), 4 * 17 + 8);
        // Centre vertices sit lower than end vertices.
        let end_y = m.vertices[0].position.y;
        let mid_base = 16 * 4 / 2; // section 8 of 16
        let mid_y = m.vertices[mid_base].position.y;
        assert!(mid_y < end_y - 0.4, "parabolic sag at midspan");
    }

    #[test]
    fn grid_lines_cover_both_axes() {
        let m = create_grid(10.0, 1.0, GREY);
        assert_eq!(m.vertices.len(), 2 * 11 * 4); // 11 lines each way, 4 verts per line
    }

    #[test]
    fn sphere_counts_and_normals() {
        let m = create_sphere(1.0, 8, 16, GREY);
        assert_eq!(m.vertices.len(), 9 * 17);
        assert_eq!(m.indices.len(), 8 * 16 * 6);
        // Unit sphere: normal ≈ position.
        let p = m.vertices[20].position;
        assert!((m.vertices[20].normal - p.normalize()).length() < 1e-5);
    }

    #[test]
    fn arrow_is_shaft_plus_cone() {
        let m = create_arrow(Vec3::ZERO, Vec3::new(0.0, -5.0, 0.0), 0.6, Vec3::new(1.0, 0.5, 0.0));
        // Beam (24) + tip + 6 base + cap centre = 32 verts.
        assert_eq!(m.vertices.len(), 32);
        assert!(!m.is_empty());
    }

    #[test]
    fn stress_coloring_overwrites_all_vertices() {
        let mut m = create_column(Vec3::ZERO, 1.0, 1.0, 5.0, GREY);
        apply_stress_coloring(&mut m.vertices, 1.2); // past limit → red-ish
        assert!(m.vertices.iter().all(|vt| vt.color == StressColors::from_stress(1.2)));
    }

    #[test]
    fn door_and_window_have_parts() {
        let door = create_door(Vec3::ZERO, 3.0, 7.0, 0.5, Vec3::new(0.55, 0.35, 0.15));
        // 3 frame boxes + panel + handle = 5 boxes × 24 verts.
        assert_eq!(door.vertices.len(), 5 * 24);

        let window = create_window(Vec3::ZERO, 4.0, 4.0, 0.5, Vec3::new(0.6, 0.8, 0.9));
        // 3 frame + sill + glass + 2 mullions = 7 boxes.
        assert_eq!(window.vertices.len(), 7 * 24);
    }

    #[test]
    fn flat_roof_is_a_box() {
        let m = create_roof(Vec3::ZERO, 30.0, 40.0, 1.0, 0.0, GREY);
        assert_eq!(m.vertices.len(), 24);
        assert!(normals_are_unit(&m));
    }

    #[test]
    fn pitched_roof_on_square_footprint_is_pyramid() {
        let m = create_roof(Vec3::ZERO, 20.0, 20.0, 1.0, 0.5, GREY);
        assert_eq!(m.vertices.len(), 12); // 4 triangles × 3 verts
        assert!(normals_are_unit(&m));
    }

    #[test]
    fn pitched_roof_on_rectangle_has_ridge() {
        let m = create_roof(Vec3::ZERO, 40.0, 20.0, 1.0, 0.5, GREY);
        assert_eq!(m.vertices.len(), 14); // 2 quads + 2 tris
        assert!(normals_are_unit(&m));
    }

    #[test]
    fn gable_roof_and_wall() {
        let roof = create_gable_roof(Vec3::ZERO, 30.0, 40.0, 9.0, 0.5, 2.0, GREY);
        assert_eq!(roof.vertices.len(), 8); // 2 quads
        assert!(normals_are_unit(&roof));

        let wall = create_gable_wall(Vec3::ZERO, 30.0, 9.0, 5.0, 0.5, GREY);
        assert_eq!(wall.vertices.len(), 10); // 2 pentagons
        assert_eq!(wall.indices.len(), 18); // 2 fans × 3 tris
        assert!(normals_are_unit(&wall));
    }

    #[test]
    fn mesh_union_offsets_indices() {
        let a = create_column(Vec3::ZERO, 1.0, 1.0, 5.0, GREY);
        let b = create_column(Vec3::new(5.0, 0.0, 0.0), 1.0, 1.0, 5.0, GREY);
        let u = csg::mesh_union(&a, &b);
        assert_eq!(u.vertices.len(), a.vertices.len() + b.vertices.len());
        assert_eq!(u.indices.len(), a.indices.len() + b.indices.len());
        let min_b_index = u.indices[a.indices.len()..].iter().min().unwrap();
        assert_eq!(*min_b_index, a.vertices.len() as u32);
    }

    #[test]
    fn wall_with_opening_leaves_a_hole() {
        let m = csg::wall_with_opening(
            Vec3::ZERO,
            Vec3::new(20.0, 0.0, 0.0),
            9.0,
            0.5,
            Vec3::new(8.0, 0.0, 0.0), // door at x=8, from floor
            3.0,
            7.0,
            GREY,
        );
        // Bottom strip skipped (sill at floor): top + left + right = 3 boxes.
        assert_eq!(m.vertices.len(), 3 * 24);
        // No vertex inside the opening region (except on its boundary).
        let inside = m.vertices.iter().any(|vt| {
            vt.position.x > 8.01 && vt.position.x < 10.99 && vt.position.y < 6.99 && vt.position.y > 0.01
        });
        assert!(!inside, "opening must be empty");
    }

    #[test]
    fn wall_with_multiple_openings_tiles_columns() {
        let m = csg::wall_with_multiple_openings(
            Vec3::ZERO,
            Vec3::new(30.0, 0.0, 0.0),
            9.0,
            0.5,
            &[[5.0, 3.0, 3.0, 4.0], [15.0, 3.0, 0.0, 7.0]],
            GREY,
        );
        assert!(!m.is_empty());
        // Every vertex is outside both opening rectangles (boundary allowed).
        for vt in &m.vertices {
            let (x, y) = (vt.position.x, vt.position.y);
            let in_first = x > 5.01 && x < 7.99 && y > 3.01 && y < 6.99;
            let in_second = x > 15.01 && x < 17.99 && y > 0.01 && y < 6.99;
            assert!(!in_first && !in_second, "vertex inside an opening: {vt:?}");
        }
    }

    #[test]
    fn openings_off_the_wall_are_clamped() {
        // Opening entirely past the wall end → solid wall.
        let m = csg::wall_with_multiple_openings(
            Vec3::ZERO,
            Vec3::new(10.0, 0.0, 0.0),
            9.0,
            0.5,
            &[[50.0, 3.0, 0.0, 9.0]],
            GREY,
        );
        assert_eq!(m.vertices.len(), 24); // single solid box
    }

    #[test]
    fn extruded_polygon_square_prism() {
        // Square footprint 10x10, height 5
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 10.0),
            Vec2::new(0.0, 10.0),
        ];
        let mesh = create_extruded_polygon(&footprint, 5.0, GREY);
        
        assert!(!mesh.is_empty());
        // Top cap: 4 verts, bottom cap: 4 verts, 4 walls × 4 verts = 24 total
        assert_eq!(mesh.vertices.len(), 24);
        // Top cap: 2 tris (6 indices), bottom cap: 2 tris (6 indices), 4 walls × 2 tris (24 indices) = 36
        assert_eq!(mesh.indices.len(), 36);
        
        // Verify heights
        let max_y = mesh.vertices.iter().map(|v| v.position.y).fold(f32::NEG_INFINITY, f32::max);
        let min_y = mesh.vertices.iter().map(|v| v.position.y).fold(f32::INFINITY, f32::min);
        assert!((max_y - 5.0).abs() < 1e-6);
        assert!((min_y - 0.0).abs() < 1e-6);
    }

    #[test]
    fn extruded_polygon_triangle_prism() {
        // Triangle footprint, height 3
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(5.0, 0.0),
            Vec2::new(2.5, 4.0),
        ];
        let mesh = create_extruded_polygon(&footprint, 3.0, GREY);
        
        assert!(!mesh.is_empty());
        // Top: 3 verts, bottom: 3 verts, 3 walls × 4 verts = 18 total
        assert_eq!(mesh.vertices.len(), 18);
        // Top: 1 tri (3 idx), bottom: 1 tri (3 idx), 3 walls × 2 tris (18 idx) = 24
        assert_eq!(mesh.indices.len(), 24);
    }

    #[test]
    fn extruded_polygon_invalid_footprint() {
        // Less than 3 vertices should return empty mesh
        let footprint = vec![Vec2::new(0.0, 0.0), Vec2::new(5.0, 0.0)];
        let mesh = create_extruded_polygon(&footprint, 3.0, GREY);
        
        assert!(mesh.is_empty());
    }

    #[test]
    fn extruded_polygon_normals_are_unit() {
        let footprint = vec![
            Vec2::new(0.0, 0.0),
            Vec2::new(10.0, 0.0),
            Vec2::new(10.0, 10.0),
            Vec2::new(0.0, 10.0),
        ];
        let mesh = create_extruded_polygon(&footprint, 5.0, GREY);
        
        assert!(normals_are_unit(&mesh));
    }
}
