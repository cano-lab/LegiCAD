//! OSM tile fetcher with on-disk cache.
//!
//! Pulls 256×256 PNG tiles from a slippy-map server, caches them under the
//! OS-standard cache directory, and decodes to RGBA for compositing into the
//! map widget's tiny-skia pixmap.
//!
//! **OSM Tile Usage Policy.** The default tile server is
//! `https://tile.openstreetmap.org/{z}/{x}/{y}.png`. OSM requires a
//! descriptive `User-Agent`, no heavy automated bulk downloading, and
//! sensible caching — all of which this fetcher does. Don't change the
//! default to a server you don't have permission to use.
//!
//! See <https://operations.osmfoundation.org/policies/tiles/>.

use std::fs;
use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::tile::TileCoord;

/// Errors the fetcher can produce.
#[derive(Debug, thiserror::Error)]
pub enum FetchError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("server returned status {0}")]
    BadStatus(u16),
    #[error("PNG decode error: {0}")]
    Decode(#[from] image::ImageError),
    #[error("could not determine cache directory")]
    NoCacheDir,
}

/// 256×256 RGBA pixels (one fetched tile, ready to blit).
#[derive(Debug, Clone)]
pub struct TileImage {
    /// `TILE_SIZE_PX * TILE_SIZE_PX * 4` RGBA bytes, row-major, top-left origin.
    pub rgba: Vec<u8>,
    /// Side length in pixels — always [`TILE_SIZE_PX`] for OSM tiles, kept as
    /// a field for consumers that don't care which server it came from.
    pub size: u32,
}

/// Default tile server (the canonical OSM endpoint). `{z}/{x}/{y}` slots get
/// substituted with the tile coordinate.
pub const OSM_TILE_URL: &str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

/// The user-agent string sent on every request. The OSM policy requires this
/// to identify the application; substitute a real contact in production
/// deploys via [`TileFetcher::with_user_agent`].
pub const DEFAULT_USER_AGENT: &str =
    "LegibleStudios/0.1 (https://github.com/jerroy/LegibleStudios)";

/// Fetches and caches map tiles.
#[derive(Debug)]
pub struct TileFetcher {
    cache_dir: PathBuf,
    client: reqwest::blocking::Client,
    url_template: String,
}

impl TileFetcher {
    /// New fetcher with OSM defaults: standard tile URL, default user-agent,
    /// cache under `<system-cache>/legible-studio/tiles/`.
    pub fn new() -> Result<Self, FetchError> {
        let cache_dir = dirs::cache_dir()
            .ok_or(FetchError::NoCacheDir)?
            .join("legible-studio")
            .join("tiles");
        Self::with_cache_dir(cache_dir)
    }

    /// New fetcher with an explicit cache directory (mostly for tests).
    pub fn with_cache_dir(cache_dir: PathBuf) -> Result<Self, FetchError> {
        fs::create_dir_all(&cache_dir)?;
        let client = reqwest::blocking::Client::builder()
            .user_agent(DEFAULT_USER_AGENT)
            .timeout(Duration::from_secs(15))
            .build()?;
        Ok(Self { cache_dir, client, url_template: OSM_TILE_URL.into() })
    }

    /// Override the User-Agent string. Use this in real deploys to include a
    /// contact e-mail per the OSM tile-usage policy.
    #[must_use]
    pub fn with_user_agent(mut self, ua: &str) -> Self {
        // Rebuild the client; reqwest doesn't expose a setter for UA.
        let new_client = reqwest::blocking::Client::builder()
            .user_agent(ua)
            .timeout(Duration::from_secs(15))
            .build();
        if let Ok(c) = new_client {
            self.client = c;
        }
        self
    }

    /// Override the tile URL template. `{z}`, `{x}`, `{y}` slots get filled.
    #[must_use]
    pub fn with_url_template(mut self, template: impl Into<String>) -> Self {
        self.url_template = template.into();
        self
    }

    /// Resolved on-disk path for a tile (cache hit or miss).
    #[must_use]
    pub fn cache_path(&self, t: TileCoord) -> PathBuf {
        self.cache_dir
            .join(t.z.to_string())
            .join(t.x.to_string())
            .join(format!("{}.png", t.y))
    }

    /// Tile URL after substituting `{z}/{x}/{y}`.
    #[must_use]
    pub fn url_for(&self, t: TileCoord) -> String {
        self.url_template
            .replace("{z}", &t.z.to_string())
            .replace("{x}", &t.x.to_string())
            .replace("{y}", &t.y.to_string())
    }

    /// Fetch a tile, returning the raw PNG bytes. Cache hit reads from disk
    /// directly; cache miss downloads from the server, writes the file, and
    /// returns the bytes.
    pub fn fetch_png(&self, t: TileCoord) -> Result<Vec<u8>, FetchError> {
        let path = self.cache_path(t);
        if path.exists() {
            return Ok(fs::read(&path)?);
        }
        let url = self.url_for(t);
        let resp = self.client.get(&url).send()?;
        if !resp.status().is_success() {
            return Err(FetchError::BadStatus(resp.status().as_u16()));
        }
        let bytes = resp.bytes()?.to_vec();
        // Write atomically: tmp file then rename, so concurrent fetchers
        // don't see partial files.
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        let tmp = path.with_extension("png.tmp");
        fs::write(&tmp, &bytes)?;
        fs::rename(&tmp, &path)?;
        Ok(bytes)
    }

    /// Fetch a tile and decode it to RGBA pixels.
    pub fn fetch(&self, t: TileCoord) -> Result<TileImage, FetchError> {
        let bytes = self.fetch_png(t)?;
        decode_png_to_rgba(&bytes)
    }
}

/// Decode an in-memory PNG byte buffer to an RGBA image. Most OSM tiles are
/// 256×256 (matching [`TILE_SIZE_PX`]) but some servers — e.g. HiDPI / @2x
/// endpoints — serve 512×512 instead. The returned `size` reflects the
/// actual decoded dimensions; callers must use it (not assume 256) when
/// indexing `rgba` or building blit pixmaps.
pub fn decode_png_to_rgba(png: &[u8]) -> Result<TileImage, FetchError> {
    let img = image::load(Cursor::new(png), image::ImageFormat::Png)?.to_rgba8();
    let size = img.width().min(img.height());
    Ok(TileImage { rgba: img.into_raw(), size })
}

/// Test-only helper: whether a tile is already cached on disk.
#[must_use]
pub fn is_cached(cache_dir: &Path, t: TileCoord) -> bool {
    cache_dir
        .join(t.z.to_string())
        .join(t.x.to_string())
        .join(format!("{}.png", t.y))
        .exists()
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{ImageBuffer, Rgba};

    fn tmp_cache(name: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("ls-site-test-{name}"));
        let _ = fs::remove_dir_all(&p);
        p
    }

    #[test]
    fn url_substitutes_z_x_y() {
        let f = TileFetcher::with_cache_dir(tmp_cache("url_subst")).unwrap();
        let u = f.url_for(TileCoord { z: 16, x: 18352, y: 23910 });
        assert_eq!(u, "https://tile.openstreetmap.org/16/18352/23910.png");
    }

    #[test]
    fn cache_path_layout_is_z_x_y_png() {
        let dir = tmp_cache("cache_layout");
        let f = TileFetcher::with_cache_dir(dir.clone()).unwrap();
        let p = f.cache_path(TileCoord { z: 16, x: 18352, y: 23910 });
        assert!(p.starts_with(&dir));
        assert!(p.ends_with("16/18352/23910.png") || p.ends_with("16\\18352\\23910.png"));
    }

    #[test]
    fn decodes_a_synthetic_png_to_256_rgba() {
        // Build a 256×256 chequerboard PNG in memory and decode it back.
        let mut img: ImageBuffer<Rgba<u8>, Vec<u8>> = ImageBuffer::new(256, 256);
        for (x, y, p) in img.enumerate_pixels_mut() {
            let on = (x / 32 + y / 32) % 2 == 0;
            *p = if on { Rgba([255, 255, 255, 255]) } else { Rgba([0, 0, 0, 255]) };
        }
        let mut buf = Cursor::new(Vec::new());
        image::DynamicImage::ImageRgba8(img)
            .write_to(&mut buf, image::ImageFormat::Png)
            .unwrap();
        let bytes = buf.into_inner();

        let ti = decode_png_to_rgba(&bytes).expect("decode");
        assert_eq!(ti.size, 256);
        assert_eq!(ti.rgba.len(), 256 * 256 * 4);
        // Top-left pixel of the chequerboard is white.
        assert_eq!(&ti.rgba[0..4], &[255, 255, 255, 255]);
    }

    #[test]
    fn fetch_png_reads_a_pre_cached_tile_without_hitting_the_network() {
        // Pre-seed the cache with a fake PNG at the tile's path, then call
        // fetch_png — it must return the bytes without making an HTTP call.
        // (The fetcher has no concept of "fake PNG"; the cache hit short-
        // circuits before any decode happens.)
        let dir = tmp_cache("prewarm");
        let t = TileCoord { z: 5, x: 11, y: 12 };
        let path = dir.join("5").join("11").join("12.png");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, b"not-a-real-png-but-the-cache-doesnt-care").unwrap();

        let f = TileFetcher::with_cache_dir(dir).unwrap();
        let bytes = f.fetch_png(t).expect("cache hit");
        assert_eq!(bytes, b"not-a-real-png-but-the-cache-doesnt-care");
    }

    /// Real OSM fetch — opt-in only. Run with `cargo test -p ls-site --
    /// --ignored`. Costs a real HTTP request to tile.openstreetmap.org.
    #[test]
    #[ignore = "hits the real OSM tile server"]
    fn fetches_a_real_tile_from_osm() {
        let dir = tmp_cache("real_fetch");
        let f = TileFetcher::with_cache_dir(dir.clone()).unwrap();
        // Sudbury at zoom 12 — small high-up tile, fast.
        let bytes = f.fetch_png(TileCoord { z: 12, x: 1162, y: 1495 }).expect("fetch");
        assert!(bytes.len() > 1000, "PNG too small ({} B)", bytes.len());
        // Decoded must be 256×256 RGBA.
        let ti = decode_png_to_rgba(&bytes).expect("decode");
        assert_eq!(ti.size, 256);
        assert_eq!(ti.rgba.len(), 256 * 256 * 4);
        // Second call is a cache hit (same file path).
        assert!(is_cached(&dir, TileCoord { z: 12, x: 1162, y: 1495 }));
    }
}
