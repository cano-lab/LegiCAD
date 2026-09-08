//! Overpass API client for OSM road network around a parcel.
//!
//! The Overpass API (<https://overpass-api.de>) lets us query OpenStreetMap
//! by bounding box and tag — perfect for "give me the streets visible
//! around this lot." We pull `highway=*` ways within the parcel's WGS84
//! bbox, parse the JSON response into a flat list of `RoadWay`s, and let
//! the site-plan renderer project each way into lot-local feet.
//!
//! ## Endpoint + courtesy
//!
//! Default endpoint is the public Overpass instance. The same OSM tile
//! policy applies — descriptive User-Agent, sensible caching, and don't
//! hammer the server. Responses are typically a few hundred KB per
//! parcel-sized bbox; cache by bbox to avoid repeats.

use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::coord::LatLon;

/// Default Overpass endpoint.
pub const DEFAULT_OVERPASS_URL: &str = "https://overpass-api.de/api/interpreter";

/// User-Agent for Overpass requests (same convention as the OSM tile fetcher).
pub const DEFAULT_USER_AGENT: &str =
    "LegibleStudios/0.1 (https://github.com/jerroy/LegibleStudios)";

/// One road or path returned from Overpass — ordered list of WGS84 node
/// positions, plus the OSM tags we care about.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RoadWay {
    pub nodes: Vec<LatLon>,
    /// `name=*` tag if present.
    #[serde(default)]
    pub name: Option<String>,
    /// `highway=*` tag (`residential`, `service`, `tertiary`, …) — drives
    /// line-weight + style choices in the renderer.
    pub highway: String,
}

/// Errors the Overpass client can produce.
#[derive(Debug, thiserror::Error)]
pub enum OverpassError {
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),
    #[error("server returned status {0}")]
    BadStatus(u16),
    #[error("JSON parse error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("response missing field: {0}")]
    MissingField(&'static str),
}

/// Overpass HTTP client.
#[derive(Debug)]
pub struct OverpassClient {
    endpoint: String,
    client: reqwest::blocking::Client,
}

impl OverpassClient {
    /// New client pointing at the public Overpass endpoint.
    pub fn new() -> Result<Self, OverpassError> {
        let client = reqwest::blocking::Client::builder()
            .user_agent(DEFAULT_USER_AGENT)
            .timeout(Duration::from_secs(60))
            .build()?;
        Ok(Self { endpoint: DEFAULT_OVERPASS_URL.into(), client })
    }

    /// Override the Overpass endpoint URL (mirrors or self-hosted).
    #[must_use]
    pub fn with_endpoint(mut self, url: impl Into<String>) -> Self {
        self.endpoint = url.into();
        self
    }

    /// Override the User-Agent string.
    #[must_use]
    pub fn with_user_agent(mut self, ua: &str) -> Self {
        if let Ok(c) = reqwest::blocking::Client::builder()
            .user_agent(ua)
            .timeout(Duration::from_secs(60))
            .build()
        {
            self.client = c;
        }
        self
    }

    /// Build the Overpass QL query for highway ways inside the given bbox.
    /// Overpass bbox syntax is `(south, west, north, east)` — opposite of
    /// the slippy-map convention.
    #[must_use]
    pub fn highway_query(&self, nw: LatLon, se: LatLon) -> String {
        let south = se.lat_deg;
        let west = nw.lon_deg;
        let north = nw.lat_deg;
        let east = se.lon_deg;
        // out body + (._;>;) brings node geometry for each way; out skel qt;
        // streams compact coords.
        format!(
            "[out:json][timeout:30];way[\"highway\"]({south},{west},{north},{east});(._;>;);out body geom;"
        )
    }

    /// Fetch + parse `highway=*` ways inside the bbox.
    pub fn fetch_highways(&self, nw: LatLon, se: LatLon) -> Result<Vec<RoadWay>, OverpassError> {
        let q = self.highway_query(nw, se);
        let resp = self
            .client
            .post(&self.endpoint)
            .body(q)
            .header("Content-Type", "text/plain; charset=utf-8")
            .send()?;
        if !resp.status().is_success() {
            return Err(OverpassError::BadStatus(resp.status().as_u16()));
        }
        let text = resp.text()?;
        parse_overpass_json(&text)
    }
}

/// Parse an Overpass JSON response into `RoadWay`s. Public so callers can
/// drop in cached responses without the network.
pub fn parse_overpass_json(text: &str) -> Result<Vec<RoadWay>, OverpassError> {
    #[derive(Deserialize)]
    struct Resp {
        elements: Vec<Element>,
    }
    #[derive(Deserialize)]
    struct Element {
        #[serde(rename = "type")]
        kind: String,
        #[serde(default)]
        tags: std::collections::HashMap<String, String>,
        // For "out body geom;" ways carry an inline `geometry` array.
        #[serde(default)]
        geometry: Vec<NodeRef>,
    }
    #[derive(Deserialize)]
    struct NodeRef {
        lat: f64,
        lon: f64,
    }
    let parsed: Resp = serde_json::from_str(text)?;
    let mut out = Vec::new();
    for e in parsed.elements {
        if e.kind != "way" {
            continue;
        }
        let Some(highway) = e.tags.get("highway").cloned() else { continue; };
        let nodes: Vec<LatLon> = e
            .geometry
            .into_iter()
            .map(|n| LatLon { lat_deg: n.lat, lon_deg: n.lon })
            .collect();
        if nodes.len() < 2 {
            continue;
        }
        out.push(RoadWay {
            nodes,
            name: e.tags.get("name").cloned(),
            highway,
        });
    }
    Ok(out)
}

/// Pixel weight + colour hint for a `highway=` tag — informs the
/// renderer without binding it to a specific style.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RoadClass {
    /// Major arterial (`motorway`, `trunk`, `primary`).
    Arterial,
    /// Mid-tier (`secondary`, `tertiary`, `unclassified`).
    Connector,
    /// Local residential / `service` streets.
    Local,
    /// Walkways / cycle paths / footways.
    Path,
}

impl RoadClass {
    /// Map an OSM `highway=` value into our four-tier classification.
    #[must_use]
    pub fn from_highway_tag(tag: &str) -> Self {
        match tag {
            "motorway" | "motorway_link" | "trunk" | "trunk_link" | "primary" | "primary_link" => {
                Self::Arterial
            }
            "secondary" | "secondary_link" | "tertiary" | "tertiary_link" | "unclassified" => {
                Self::Connector
            }
            "residential" | "living_street" | "service" => Self::Local,
            _ => Self::Path,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn highway_query_uses_overpass_bbox_order() {
        let c = OverpassClient::new().expect("client");
        let q = c.highway_query(
            LatLon { lat_deg: 46.495, lon_deg: -80.999 },
            LatLon { lat_deg: 46.492, lon_deg: -80.989 },
        );
        // (south, west, north, east) per Overpass bbox convention.
        assert!(q.contains("(46.492,-80.999,46.495,-80.989)"), "query: {q}");
        assert!(q.contains(r#"way["highway"]"#));
        assert!(q.contains("out body geom;"));
    }

    #[test]
    fn parses_a_canned_overpass_response() {
        // Minimal "out body geom" response: one way (a residential street)
        // with two nodes inline.
        let canned = r#"{
            "version": 0.6,
            "generator": "test",
            "elements": [
                {
                    "type": "way",
                    "id": 1,
                    "tags": { "highway": "residential", "name": "Birch Ave" },
                    "geometry": [
                        { "lat": 46.4920, "lon": -80.9950 },
                        { "lat": 46.4925, "lon": -80.9940 }
                    ]
                },
                {
                    "type": "node",
                    "id": 100,
                    "lat": 46.4920,
                    "lon": -80.9950
                }
            ]
        }"#;
        let ways = parse_overpass_json(canned).unwrap();
        assert_eq!(ways.len(), 1);
        assert_eq!(ways[0].highway, "residential");
        assert_eq!(ways[0].name.as_deref(), Some("Birch Ave"));
        assert_eq!(ways[0].nodes.len(), 2);
        assert!((ways[0].nodes[0].lat_deg - 46.4920).abs() < 1e-7);
    }

    #[test]
    fn ways_without_highway_tag_are_dropped() {
        let canned = r#"{
            "elements": [
                {
                    "type": "way",
                    "tags": { "building": "yes" },
                    "geometry": [{"lat":0,"lon":0},{"lat":1,"lon":1}]
                }
            ]
        }"#;
        let ways = parse_overpass_json(canned).unwrap();
        assert!(ways.is_empty());
    }

    #[test]
    fn ways_with_fewer_than_two_nodes_are_dropped() {
        let canned = r#"{
            "elements": [
                {
                    "type": "way",
                    "tags": { "highway": "service" },
                    "geometry": [{"lat":0,"lon":0}]
                }
            ]
        }"#;
        let ways = parse_overpass_json(canned).unwrap();
        assert!(ways.is_empty());
    }

    #[test]
    fn road_class_buckets_match_osm_conventions() {
        assert_eq!(RoadClass::from_highway_tag("motorway"), RoadClass::Arterial);
        assert_eq!(RoadClass::from_highway_tag("tertiary"), RoadClass::Connector);
        assert_eq!(RoadClass::from_highway_tag("residential"), RoadClass::Local);
        assert_eq!(RoadClass::from_highway_tag("footway"), RoadClass::Path);
    }

    /// Real Overpass query — opt-in. Hits the public API; expect a few
    /// hundred KB of JSON for a residential bbox.
    #[test]
    #[ignore = "hits the real Overpass API"]
    fn fetches_real_streets_for_sudbury_bbox() {
        let c = OverpassClient::new().expect("client");
        let ways = c
            .fetch_highways(
                LatLon { lat_deg: 46.495, lon_deg: -80.999 },
                LatLon { lat_deg: 46.490, lon_deg: -80.985 },
            )
            .expect("fetch");
        assert!(!ways.is_empty(), "no streets returned");
        // Sudbury parcels at this zoom should have at least one named road.
        assert!(ways.iter().any(|w| w.name.is_some()));
    }
}
