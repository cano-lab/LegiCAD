//! `archgeometry_dump` — Rust counterpart to the C++ tool of the same name.
//!
//! Output is line-oriented and byte-equivalent to the C++ tool's so the
//! M1 diff oracle (`rust/tests/m1_diff.py`) can compare them directly.
//! Categories whose generators haven't been ported yet emit
//! `UNIMPLEMENTED` instead — the diff harness treats that as yellow.

use archgeometry::dump_hash::{Hasher, hash_mesh, hash_room};
use archgeometry::geometry_types::{
    BuildingGeometry, DoorGeometry, FloorGeometry, Mesh3D, RoofGeometry, RoomBoundary,
    WallGeometry, WindowGeometry,
};
use archgeometry::{generate_from_schema, parse_file};
use std::path::Path;
use std::process::ExitCode;

const FORMAT_VERSION: &str = "ARCHGEOMETRY_DUMP v1";

/// Categories with ported generators emit real hashes; the rest emit
/// `UNIMPLEMENTED` until their crate modules land.
const IMPLEMENTED_ROOFS: bool = true;
const IMPLEMENTED_DOORS: bool = true;
const IMPLEMENTED_WINDOWS: bool = true;
const IMPLEMENTED_ROOMS: bool = true;

#[allow(clippy::too_many_lines)] // CLI argument parsing + dispatch reads top-down.
fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mut path_arg: Option<String> = None;
    let mut verbose = false;
    let mut bytes_of_wall: Option<i32> = None;
    let mut dump_rooms = false;
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--verbose" | "-v" => {
                verbose = true;
                i += 1;
            }
            "--bytes-of-wall" if i + 1 < args.len() => {
                bytes_of_wall = Some(args[i + 1].parse().unwrap_or(-1));
                i += 2;
            }
            "--dump-rooms" => {
                dump_rooms = true;
                i += 1;
            }
            other => {
                if path_arg.is_none() {
                    path_arg = Some(other.to_string());
                }
                i += 1;
            }
        }
    }
    let Some(path_arg) = path_arg else {
        eprintln!("usage: archgeometry_dump [--verbose] [--bytes-of-wall N] <building.json>");
        return ExitCode::from(2);
    };

    let path = Path::new(&path_arg);
    if !path.exists() {
        eprintln!("error: file not found: {}", path.display());
        return ExitCode::from(2);
    }

    let filename = path.file_name().and_then(|n| n.to_str()).unwrap_or("?");

    let doc = match parse_file(path) {
        Ok(d) => d,
        Err(e) => {
            eprintln!("error: {e}");
            return ExitCode::from(1);
        }
    };

    let g = generate_from_schema(&doc);

    if let Some(target) = bytes_of_wall {
        return dump_bytes_of_wall(&g, target);
    }
    if dump_rooms {
        return dump_rooms_data(&g);
    }

    println!("{FORMAT_VERSION}");
    println!("INPUT {filename}");
    print_building(&g);

    print_mesh_category(
        "WALLS",
        &g.walls,
        |w| (w.wall_index, w.wall_id.as_str()),
        |w| &w.mesh_3d,
        verbose,
    );
    print_mesh_category(
        "FLOORS",
        &g.floors,
        |f| (f.floor_index, f.floor_id.as_str()),
        |f| &f.mesh_3d,
        verbose,
    );

    if IMPLEMENTED_ROOFS {
        print_mesh_category(
            "ROOFS",
            &g.roofs,
            |r| (r.roof_index, r.roof_id.as_str()),
            |r| &r.mesh_3d,
            verbose,
        );
    } else {
        unimpl_mesh_category("ROOFS", &g.roofs);
    }
    if IMPLEMENTED_DOORS {
        print_mesh_category(
            "DOORS",
            &g.doors,
            |d| (d.door_index, d.door_id.as_str()),
            |d| &d.mesh_3d,
            verbose,
        );
    } else {
        unimpl_mesh_category("DOORS", &g.doors);
    }
    if IMPLEMENTED_WINDOWS {
        print_mesh_category(
            "WINDOWS",
            &g.windows,
            |w| (w.window_index, w.window_id.as_str()),
            |w| &w.mesh_3d,
            verbose,
        );
    } else {
        unimpl_mesh_category("WINDOWS", &g.windows);
    }
    if IMPLEMENTED_ROOMS {
        print_room_category(&g.rooms);
    } else {
        println!("{:<8} UNIMPLEMENTED", "ROOMS");
    }

    println!("END");
    ExitCode::SUCCESS
}

fn print_building(g: &BuildingGeometry) {
    let id = if g.building_id.is_empty() {
        "-"
    } else {
        g.building_id.as_str()
    };
    println!(
        "BUILDING id={id} bounds_min={:.4},{:.4},{:.4} bounds_max={:.4},{:.4},{:.4}",
        g.bounds_min.x,
        g.bounds_min.y,
        g.bounds_min.z,
        g.bounds_max.x,
        g.bounds_max.y,
        g.bounds_max.z,
    );
}

/// Stable-sort by `(index, id)` and accumulate vertex/triangle counts and
/// an FNV-1a hash of each mesh's vertex+index byte sequence.
fn print_mesh_category<T, K, M>(label: &str, items: &[T], key_of: K, mesh_of: M, verbose: bool)
where
    K: for<'a> Fn(&'a T) -> (i32, &'a str),
    M: for<'a> Fn(&'a T) -> &'a Mesh3D,
{
    let mut order: Vec<usize> = (0..items.len()).collect();
    // Stable sort by (index, id) to match `std::stable_sort` in the C++.
    order.sort_by(|&a, &b| {
        let (ai, an) = key_of(&items[a]);
        let (bi, bn) = key_of(&items[b]);
        (ai, an).cmp(&(bi, bn))
    });

    let mut h = Hasher::new();
    let mut total_v: usize = 0;
    let mut total_t: usize = 0;
    for (rank, &idx) in order.iter().enumerate() {
        let m = mesh_of(&items[idx]);
        if verbose {
            // Per-item hash — feed JUST this mesh into a fresh hasher so the
            // value is independent of preceding items. Useful for bisecting
            // a category-level mismatch down to a specific element.
            let mut per = Hasher::new();
            hash_mesh(&mut per, m);
            eprintln!(
                "  {label}[{rank}] src_idx={idx} verts={vc} tris={tc} per_hash=0x{ph:016x} cumulative=0x{ch:016x}",
                vc = m.vertices.len(),
                tc = m.faces.len(),
                ph = per.state,
                ch = h.state,
            );
        }
        hash_mesh(&mut h, m);
        total_v += m.vertices.len();
        total_t += m.faces.len();
    }

    println!(
        "{label:<8} count={count} vertices={total_v} triangles={total_t} hash=0x{state:016x}",
        count = items.len(),
        state = h.state,
    );
}

/// Same line format as `print_mesh_category` but with zero counts and the
/// FNV offset hash — so a yet-to-be-ported category whose schema input is
/// empty already matches the C++ output, and only the `UNIMPLEMENTED`
/// sentinel marks "this generator hasn't landed yet."
fn unimpl_mesh_category<T>(label: &str, _items: &[T]) {
    println!("{label:<8} UNIMPLEMENTED");
}

fn print_room_category(rooms: &[RoomBoundary]) {
    let mut order: Vec<usize> = (0..rooms.len()).collect();
    order.sort_by(|&a, &b| rooms[a].room_id.cmp(&rooms[b].room_id));

    let mut h = Hasher::new();
    for &idx in &order {
        hash_room(&mut h, &rooms[idx]);
    }

    println!(
        "{:<8} count={count} hash=0x{state:016x}",
        "ROOMS",
        count = rooms.len(),
        state = h.state,
    );
}

// Silence dead-code warnings on the type parameters used only as compile-
// time hints in the generic signature.
#[allow(dead_code)]
fn _type_hints() {
    let _w: &WallGeometry;
    let _f: &FloorGeometry;
    let _r: &RoofGeometry;
    let _d: &DoorGeometry;
    let _wn: &WindowGeometry;
}

/// Per-room data in the same `%.4f` format used for the FNV stream.
fn dump_rooms_data(g: &BuildingGeometry) -> ExitCode {
    let mut order: Vec<usize> = (0..g.rooms.len()).collect();
    order.sort_by(|&a, &b| g.rooms[a].room_id.cmp(&g.rooms[b].room_id));

    let mut h = Hasher::new();
    for &idx in &order {
        let r = &g.rooms[idx];
        println!(
            "ROOM id={} area={:.4} center={:.4},{:.4} points={}",
            r.room_id,
            r.area,
            r.center.x,
            r.center.y,
            r.boundary.points.len(),
        );
        for (i, p) in r.boundary.points.iter().enumerate() {
            println!("  p[{i}] {:.4} {:.4}", p.x, p.y);
        }
        hash_room(&mut h, r);
    }
    println!("ROOMS_TOTAL hash=0x{:016x}", h.state);
    ExitCode::SUCCESS
}

/// Dump every vertex and face of the Nth wall (after sort) in the same
/// `%.4f` format the C++ uses, so the two can be diffed line-by-line.
/// Matches the C++ `dumpBytesOfWall` in `archgeometry_dump.cpp:201`.
fn dump_bytes_of_wall(g: &BuildingGeometry, target: i32) -> ExitCode {
    let mut order: Vec<usize> = (0..g.walls.len()).collect();
    order.sort_by(|&a, &b| {
        (g.walls[a].wall_index, g.walls[a].wall_id.as_str())
            .cmp(&(g.walls[b].wall_index, g.walls[b].wall_id.as_str()))
    });
    let Ok(target_us) = usize::try_from(target) else {
        eprintln!("wall index {target} out of range");
        return ExitCode::from(2);
    };
    if target_us >= order.len() {
        eprintln!("wall index {target} out of range [0,{})", order.len());
        return ExitCode::from(2);
    }
    let w = &g.walls[order[target_us]];
    let m = &w.mesh_3d;
    println!(
        "WALL {target}: {} verts, {} tris, wall_id={}",
        m.vertices.len(),
        m.faces.len(),
        w.wall_id,
    );
    for (i, v) in m.vertices.iter().enumerate() {
        println!(
            "v[{i}] pos {:.4} {:.4} {:.4} | n {:.4} {:.4} {:.4} | c {:.4} {:.4} {:.4} | uv {:.4} {:.4} | s {:.4}",
            v.position.x,
            v.position.y,
            v.position.z,
            v.normal.x,
            v.normal.y,
            v.normal.z,
            v.color.x,
            v.color.y,
            v.color.z,
            v.uv.x,
            v.uv.y,
            v.stress,
        );
    }
    for (i, t) in m.faces.iter().enumerate() {
        println!("t[{i}] {} {} {}", t.v0, t.v1, t.v2);
    }
    ExitCode::SUCCESS
}
