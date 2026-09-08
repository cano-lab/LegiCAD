//! Shared point-cloud IO.
//!
//! ASCII XYZ is the lowest-common-denominator LiDAR export: one `x y z` triple
//! per line, metres, **y up** (x east, z north — the `SchemaWall` convention).
//! Blank lines and `#` comments are skipped; extra columns (intensity, rgb) are
//! tolerated and dropped.

use glam::Vec3;

/// Parse an ASCII XYZ cloud into points (metres, y up).
///
/// # Errors
/// Returns a human-readable message if a non-comment line lacks three parseable
/// floats, or if the file contains no points.
pub fn parse_xyz(text: &str) -> Result<Vec<Vec3>, String> {
    let mut pts = Vec::new();
    for (lineno, line) in text.lines().enumerate() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut it = line.split_whitespace();
        match (it.next(), it.next(), it.next()) {
            (Some(x), Some(y), Some(z)) => {
                let x = x.parse::<f32>().map_err(|_| bad(lineno, line))?;
                let y = y.parse::<f32>().map_err(|_| bad(lineno, line))?;
                let z = z.parse::<f32>().map_err(|_| bad(lineno, line))?;
                pts.push(Vec3::new(x, y, z));
            }
            _ => return Err(bad(lineno, line)),
        }
    }
    if pts.is_empty() {
        return Err("no XYZ points found".to_string());
    }
    Ok(pts)
}

fn bad(lineno: usize, line: &str) -> String {
    format!("line {}: expected `x y z`, got `{line}`", lineno + 1)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_with_comments_and_extra_columns() {
        let text = "# header\n0 0 0\n1.5 2.0 3.0 255 0 0\n\n  4 5 6  \n";
        let pts = parse_xyz(text).unwrap();
        assert_eq!(pts.len(), 3);
        assert_eq!(pts[1], Vec3::new(1.5, 2.0, 3.0));
        assert_eq!(pts[2], Vec3::new(4.0, 5.0, 6.0));
    }

    #[test]
    fn rejects_short_lines() {
        assert!(parse_xyz("1 2").is_err());
    }

    #[test]
    fn rejects_empty() {
        assert!(parse_xyz("# only comments\n\n").is_err());
    }
}
