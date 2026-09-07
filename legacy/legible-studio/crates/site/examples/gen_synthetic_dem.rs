//! Generate a synthetic 1 km Ontario DEM tile with a realistic relief
//! profile — used to demo the site pipeline end-to-end without pulling
//! a multi-GB live package. The output is a valid GeoTIFF (UTM 17 N,
//! NAD83) named with the Ontario `1km{zone}{ekm}{nm}` convention so
//! `LocalTileIndex` picks it up unmodified.
//!
//! Usage:
//!     gen_synthetic_dem <zone> <easting_km> <northing_m> <out_dir>
//!
//! Example (Sudbury — covers the demo parcel):
//!     gen_synthetic_dem 17 500 5148000 target/dems

use std::env;
use std::fs;
use std::io::Cursor;
use std::path::PathBuf;
use std::process::ExitCode;

use tiff::encoder::{TiffEncoder, colortype};
use tiff::tags::Tag;

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    if args.len() != 5 {
        eprintln!("usage: {} <zone> <easting_km> <northing_m> <out_dir>", args[0]);
        return ExitCode::from(2);
    }
    let zone: u8 = args[1].parse().expect("zone");
    let ekm: u32 = args[2].parse().expect("easting_km");
    let nm: u32 = args[3].parse().expect("northing_m");
    let out_dir = PathBuf::from(&args[4]);
    fs::create_dir_all(&out_dir).expect("mkdir");

    // 1 km tile at 1 m/pixel → 1000×1000 raster.
    let width: u32 = 1000;
    let height: u32 = 1000;
    let scale_xy: f64 = 1.0;
    let easting_m = f64::from(ekm) * 1000.0;
    // Tiepoint sits at the NW corner of the raster (raster y=0 is the
    // top, so the model y coord = north edge = nm + 1000).
    let origin_x = easting_m;
    let origin_y = f64::from(nm + 1000);

    // Generate a Sudbury-ish relief: base elevation 285 m (lake-Ramsey-ish),
    // gentle 5 m east-to-west slope, and two superimposed sinusoidal hills
    // for visible contour curvature.
    let base = 285.0_f32;
    let slope_total = 5.0_f32;
    let mut samples: Vec<f32> = Vec::with_capacity((width * height) as usize);
    for ry in 0..height {
        for rx in 0..width {
            let u = rx as f32 / (width - 1) as f32;
            let v = ry as f32 / (height - 1) as f32;
            // East-rising linear ramp (subtle).
            let ramp = slope_total * (u - 0.5);
            // Two hills: one near the NW, one near the SE.
            let nw_dx = u - 0.25;
            let nw_dy = v - 0.25;
            let nw_hill = 4.0 * (-((nw_dx * nw_dx + nw_dy * nw_dy) * 80.0)).exp();
            let se_dx = u - 0.75;
            let se_dy = v - 0.75;
            let se_hill = 3.0 * (-((se_dx * se_dx + se_dy * se_dy) * 120.0)).exp();
            let elev = base + ramp + nw_hill + se_hill;
            samples.push(elev);
        }
    }

    let filename = format!("1km{zone:02}{ekm:03}{nm:07}SYNTHETIC_DTM.tif");
    let path = out_dir.join(&filename);
    let mut buf = Cursor::new(Vec::<u8>::new());
    {
        let mut enc = TiffEncoder::new(&mut buf).expect("encoder");
        let mut img = enc
            .new_image::<colortype::Gray32Float>(width, height)
            .expect("image");
        img.encoder()
            .write_tag(
                Tag::ModelTiepointTag,
                &[0.0_f64, 0.0, 0.0, origin_x, origin_y, 0.0][..],
            )
            .expect("tiepoint");
        img.encoder()
            .write_tag(Tag::ModelPixelScaleTag, &[scale_xy, scale_xy, 0.0][..])
            .expect("scale");
        // GeoKey directory: ProjectedCSTypeGeoKey = 26917 (NAD83 / UTM 17N).
        img.encoder()
            .write_tag(Tag::GeoKeyDirectoryTag, &[1_u16, 1, 0, 1, 3072, 0, 1, 26917][..])
            .expect("geokeys");
        img.write_data(&samples).expect("write data");
    }
    fs::write(&path, buf.into_inner()).expect("write file");
    let min = samples.iter().copied().fold(f32::INFINITY, f32::min);
    let max = samples.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    eprintln!(
        "wrote {} ({} bytes, {}x{} px, elev {:.2}..{:.2} m)",
        path.display(),
        fs::metadata(&path).map(|m| m.len()).unwrap_or(0),
        width,
        height,
        min,
        max,
    );
    ExitCode::SUCCESS
}
