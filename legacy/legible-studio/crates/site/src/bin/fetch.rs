//! `legible-fetch` — pull Ontario LiDAR packages over HTTPS, drop the
//! extracted `.tif` tiles where `legible-stitch` can find them.
//!
//! Two trigger forms:
//! ```text
//! legible-fetch --site site.json --out C:\ontario_dems [--type dtm|dsm|both]
//! legible-fetch --bbox lat_max,lon_min,lat_min,lon_max --out C:\ontario_dems
//! ```
//!
//! `--site` reuses the JSON the map widget writes (centre derived from the
//! bbox block); `--bbox` is a direct override for headless runs. Pulls
//! every existing package in every region the centre point matches —
//! unlike the Python tool, which stops at the first 200, this guarantees
//! coverage for parcels that straddle package boundaries.

use std::path::PathBuf;

use anyhow::{Context, anyhow};
use ls_site::{
    LatLon,
    downloader::{LidarDownloader, PackageDataType},
};

const USAGE: &str = "usage: \n\
    legible-fetch --site <site.json> --out <dir> [--type dtm|dsm|both]\n\
    legible-fetch --bbox <lat_max,lon_min,lat_min,lon_max> --out <dir> [--type ...]";

#[allow(
    clippy::too_many_lines,           // argv parsing + status reporting reads top-down
    clippy::cast_possible_wrap,
    clippy::cast_precision_loss,      // human-readable progress, not numerics
    clippy::cast_sign_loss,
    clippy::assigning_clones,         // string is short; `clone_into` is noise here
)]
fn main() -> anyhow::Result<()> {
    let mut args = std::env::args().skip(1);
    let mut site: Option<PathBuf> = None;
    let mut bbox: Option<(f64, f64, f64, f64)> = None;
    let mut out: Option<PathBuf> = None;
    let mut data_types: Vec<PackageDataType> = vec![PackageDataType::Dtm];

    while let Some(a) = args.next() {
        match a.as_str() {
            "--site" => site = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
            "--bbox" => {
                let raw = args.next().ok_or_else(|| anyhow!("--bbox needs values"))?;
                let parts: Vec<f64> = raw
                    .split(',')
                    .map(|s| s.trim().parse::<f64>())
                    .collect::<Result<_, _>>()
                    .with_context(|| format!("bad --bbox: {raw}"))?;
                if parts.len() != 4 {
                    return Err(anyhow!("--bbox needs lat_max,lon_min,lat_min,lon_max"));
                }
                bbox = Some((parts[0], parts[1], parts[2], parts[3]));
            }
            "--out" => out = Some(PathBuf::from(args.next().ok_or_else(|| anyhow!(USAGE))?)),
            "--type" => {
                let kind = args.next().ok_or_else(|| anyhow!("--type needs a value"))?;
                data_types = match kind.to_ascii_lowercase().as_str() {
                    "dtm" => vec![PackageDataType::Dtm],
                    "dsm" => vec![PackageDataType::Dsm],
                    "both" => vec![PackageDataType::Dtm, PackageDataType::Dsm],
                    other => return Err(anyhow!("--type must be dtm|dsm|both (got {other})")),
                };
            }
            "-h" | "--help" => {
                println!("{USAGE}");
                return Ok(());
            }
            other => return Err(anyhow!("unknown flag {other}\n{USAGE}")),
        }
    }
    let out = out.ok_or_else(|| anyhow!("--out required\n{USAGE}"))?;
    let (nw, se) = if let Some((lat_max, lon_min, lat_min, lon_max)) = bbox {
        (
            LatLon { lat_deg: lat_max, lon_deg: lon_min },
            LatLon { lat_deg: lat_min, lon_deg: lon_max },
        )
    } else if let Some(site_path) = site {
        let txt = std::fs::read_to_string(&site_path)
            .with_context(|| format!("read {}", site_path.display()))?;
        let v: serde_json::Value = serde_json::from_str(&txt)
            .with_context(|| format!("parse {}", site_path.display()))?;
        let bb = v.get("bbox").ok_or_else(|| anyhow!("no bbox in site.json"))?;
        let lat_max = bb["lat_max"].as_f64().ok_or_else(|| anyhow!("bbox.lat_max"))?;
        let lat_min = bb["lat_min"].as_f64().ok_or_else(|| anyhow!("bbox.lat_min"))?;
        let lon_min = bb["lon_min"].as_f64().ok_or_else(|| anyhow!("bbox.lon_min"))?;
        let lon_max = bb["lon_max"].as_f64().ok_or_else(|| anyhow!("bbox.lon_max"))?;
        (
            LatLon { lat_deg: lat_max, lon_deg: lon_min },
            LatLon { lat_deg: lat_min, lon_deg: lon_max },
        )
    } else {
        return Err(anyhow!("--site or --bbox required\n{USAGE}"));
    };

    let dl = LidarDownloader::new(&out)?;
    eprintln!("output dir: {}", dl.output_dir().display());

    let centre = LatLon {
        lat_deg: (nw.lat_deg + se.lat_deg) * 0.5,
        lon_deg: (nw.lon_deg + se.lon_deg) * 0.5,
    };
    let regions = LidarDownloader::find_regions(centre);
    if regions.is_empty() {
        eprintln!(
            "no known region covers ({:.4}, {:.4}) — see ls_site::ontario::KNOWN_REGIONS",
            centre.lat_deg, centre.lon_deg,
        );
        return Ok(());
    }
    eprintln!("centre {:.4},{:.4} → region(s): {regions:?}", centre.lat_deg, centre.lon_deg);

    let pkgs = LidarDownloader::packages_for(centre, &data_types);
    eprintln!("planning {} package(s)", pkgs.len());

    let mut downloaded = 0_usize;
    let mut last_pct: i64 = -1;
    let mut last_pkg = String::new();
    let on_progress = |pkg: &ls_site::downloader::PackageInfo, done: u64, total: u64| {
        let pct = if total > 0 { (done * 100 / total) as i64 } else { -1 };
        let full = pkg.full_name();
        if full != last_pkg {
            last_pkg = full.clone();
            last_pct = -1;
            eprintln!("→ {full}");
        }
        if pct != last_pct && pct % 10 == 0 {
            last_pct = pct;
            eprintln!(
                "   {pct}%  ({:.1} / {:.1} MB)",
                done as f64 / 1_048_576.0,
                total as f64 / 1_048_576.0,
            );
        }
    };
    let dirs = dl.download_for_location(centre, &data_types, on_progress)?;
    downloaded += dirs.len();
    eprintln!("✓ {downloaded} package(s) extracted to {}", dl.output_dir().display());
    if downloaded == 0 {
        eprintln!(
            "  (every candidate package 404'd — confirm region {regions:?} \
             still publishes packages, or try --type both)"
        );
    }
    Ok(())
}
