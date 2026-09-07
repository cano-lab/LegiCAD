//! Serde helpers for the JSON wire format.
//!
//! The Python QBD generator writes `Vec3`/`Vec2` as JSON arrays `[x, y, z]`,
//! but glam's default serde representation is struct-shaped `{"x":...,
//! "y":..., "z":...}`. These helpers translate between the two.

use glam::{Vec2, Vec3};
use serde::{Deserialize, Deserializer, Serialize, Serializer};

/// `#[serde(with = "wire::vec3_array")]` — Vec3 ↔ `[x, y, z]`.
pub mod vec3_array {
    use super::{Deserialize, Deserializer, Serializer, Vec3};

    pub fn serialize<S: Serializer>(v: &Vec3, s: S) -> Result<S::Ok, S::Error> {
        [v.x, v.y, v.z].serialize(s)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec3, D::Error> {
        let arr = <[f32; 3]>::deserialize(d)?;
        Ok(Vec3::new(arr[0], arr[1], arr[2]))
    }

    // Wrap to satisfy clippy::pedantic (which wants `Serialize::serialize`).
    use serde::Serialize as _;
}

/// `#[serde(with = "wire::vec2_array")]` — Vec2 ↔ `[x, y]`.
pub mod vec2_array {
    use super::{Deserialize, Deserializer, Serializer, Vec2};

    pub fn serialize<S: Serializer>(v: &Vec2, s: S) -> Result<S::Ok, S::Error> {
        [v.x, v.y].serialize(s)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec2, D::Error> {
        let arr = <[f32; 2]>::deserialize(d)?;
        Ok(Vec2::new(arr[0], arr[1]))
    }

    use serde::Serialize as _;
}

/// `#[serde(with = "wire::vec2_xy_object")]` — Vec2 ↔ `{"x": ..., "y": ...}`.
///
/// QBD writes `center` and similar 2D points as `{x, y}` objects per the
/// locked `qbd_output.schema.json` contract. Glam's default Vec2 serde is
/// the array form, so this helper is required for object-shaped points.
pub mod vec2_xy_object {
    use super::{Deserialize, Deserializer, Serialize, Serializer, Vec2};

    #[derive(Serialize, Deserialize)]
    struct Xy {
        x: f32,
        y: f32,
    }

    pub fn serialize<S: Serializer>(v: &Vec2, s: S) -> Result<S::Ok, S::Error> {
        Xy { x: v.x, y: v.y }.serialize(s)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec2, D::Error> {
        let xy = Xy::deserialize(d)?;
        Ok(Vec2::new(xy.x, xy.y))
    }
}

/// `#[serde(default, deserialize_with = "wire::map_or_empty_array::deserialize")]`
/// for fields that the Python QBD generator writes as `[]` when empty and
/// `{...}` when populated.
pub mod map_or_empty_array {
    use serde::{Deserialize, Deserializer, de::DeserializeOwned};
    use serde_json::Value;
    use std::collections::HashMap;

    pub fn deserialize<'de, D, V>(d: D) -> Result<HashMap<String, V>, D::Error>
    where
        D: Deserializer<'de>,
        V: DeserializeOwned,
    {
        let v = Value::deserialize(d)?;
        match v {
            Value::Array(a) if a.is_empty() => Ok(HashMap::new()),
            Value::Object(_) => serde_json::from_value(v).map_err(serde::de::Error::custom),
            _ => Err(serde::de::Error::custom(
                "expected an object or empty array",
            )),
        }
    }
}

/// `#[serde(with = "wire::vec3_array_vec")]` — `Vec<Vec3>` ↔ `[[x,y,z], …]`.
pub mod vec3_array_vec {
    use super::{Deserialize, Deserializer, Serialize, Serializer, Vec3};

    pub fn serialize<S: Serializer>(v: &[Vec3], s: S) -> Result<S::Ok, S::Error> {
        let arrays: Vec<[f32; 3]> = v.iter().map(|x| [x.x, x.y, x.z]).collect();
        arrays.serialize(s)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<Vec<Vec3>, D::Error> {
        let arrays = Vec::<[f32; 3]>::deserialize(d)?;
        Ok(arrays
            .into_iter()
            .map(|a| Vec3::new(a[0], a[1], a[2]))
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::{Deserialize, Serialize};

    #[derive(Serialize, Deserialize, PartialEq, Debug)]
    struct WithVec3 {
        #[serde(with = "vec3_array")]
        p: Vec3,
    }

    #[derive(Serialize, Deserialize, PartialEq, Debug)]
    struct WithVec2 {
        #[serde(with = "vec2_array")]
        p: Vec2,
    }

    #[derive(Serialize, Deserialize, PartialEq, Debug)]
    struct WithVec3Vec {
        #[serde(with = "vec3_array_vec")]
        pts: Vec<Vec3>,
    }

    #[test]
    fn vec3_round_trips_as_array() {
        let v = WithVec3 {
            p: Vec3::new(1.0, 2.0, 3.0),
        };
        let json = serde_json::to_string(&v).unwrap();
        assert_eq!(json, r#"{"p":[1.0,2.0,3.0]}"#);
        let back: WithVec3 = serde_json::from_str(&json).unwrap();
        assert_eq!(back, v);
    }

    #[test]
    fn vec3_parses_from_python_qbd_style() {
        // Python writes integers when the value is whole; serde_json handles
        // both `1` and `1.0` as f32 for this position.
        let json = r#"{"p":[9144, 0, 12192]}"#;
        let v: WithVec3 = serde_json::from_str(json).unwrap();
        assert_eq!(v.p, Vec3::new(9144.0, 0.0, 12192.0));
    }

    #[test]
    fn vec2_round_trips_as_array() {
        let v = WithVec2 {
            p: Vec2::new(1.5, -2.5),
        };
        let json = serde_json::to_string(&v).unwrap();
        assert_eq!(json, r#"{"p":[1.5,-2.5]}"#);
        let back: WithVec2 = serde_json::from_str(&json).unwrap();
        assert_eq!(back, v);
    }

    #[test]
    fn vec3_vec_round_trips_as_array_of_arrays() {
        let v = WithVec3Vec {
            pts: vec![Vec3::ZERO, Vec3::X, Vec3::new(1.0, 2.0, 3.0)],
        };
        let json = serde_json::to_string(&v).unwrap();
        assert_eq!(
            json,
            r#"{"pts":[[0.0,0.0,0.0],[1.0,0.0,0.0],[1.0,2.0,3.0]]}"#
        );
        let back: WithVec3Vec = serde_json::from_str(&json).unwrap();
        assert_eq!(back, v);
    }
}
