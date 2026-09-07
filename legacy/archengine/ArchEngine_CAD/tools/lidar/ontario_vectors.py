"""
Ontario Vector Data Downloader
==============================
Download roads, water bodies, and other vector data from Ontario GeoHub.

Uses ArcGIS REST API to query features within a bounding box.

Data sources:
- Ontario Road Network (ORN): https://geohub.lio.gov.on.ca
- Ontario Hydro Network (OHN): https://geohub.lio.gov.on.ca
"""

import json
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ArcGIS REST API endpoints for Ontario open data
# LIO Open Data MapServer contains multiple layers
LIO_OPEN_DATA_BASE = "https://ws.lioservices.lrc.gov.on.ca/arcgis2/rest/services/LIO_OPEN_DATA/LIO_Open01/MapServer"

# Layer IDs in LIO_Open01 MapServer
LAYER_IDS = {
    "roads": 12,        # Ontario Road Network Segment
    "waterbody": 25,    # OHN Waterbody (lakes, ponds)
    "watercourse": 26,  # OHN Watercourse (rivers, streams)
    "municipal": 5,     # Municipal Boundary
    "township": 6,      # Geographic Township
}

# Alternative: Ontario Road Network Composite (more detailed)
ORN_COMPOSITE_URL = "https://services1.arcgis.com/TJH5KDher0W13Kgo/ArcGIS/rest/services/Ontario_Road_Network_Composite_Service/FeatureServer/5"


@dataclass
class VectorFeature:
    """A single vector feature (road segment, water body, etc.)"""
    geometry_type: str  # "polyline", "polygon", "point"
    coordinates: List[Any]  # Coordinate arrays
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_geojson_feature(self) -> Dict:
        """Convert to GeoJSON feature format."""
        if self.geometry_type == "polyline":
            geom_type = "MultiLineString" if len(self.coordinates) > 1 else "LineString"
            coords = self.coordinates if len(self.coordinates) > 1 else self.coordinates[0]
        elif self.geometry_type == "polygon":
            geom_type = "Polygon"
            coords = self.coordinates
        else:
            geom_type = "Point"
            coords = self.coordinates

        return {
            "type": "Feature",
            "geometry": {
                "type": geom_type,
                "coordinates": coords
            },
            "properties": self.attributes
        }


@dataclass
class VectorDataset:
    """Collection of vector features."""
    name: str
    features: List[VectorFeature] = field(default_factory=list)
    crs: str = "EPSG:4326"

    def to_geojson(self) -> Dict:
        """Convert to GeoJSON FeatureCollection."""
        return {
            "type": "FeatureCollection",
            "name": self.name,
            "crs": {
                "type": "name",
                "properties": {"name": self.crs}
            },
            "features": [f.to_geojson_feature() for f in self.features]
        }

    def save_geojson(self, path: str):
        """Save as GeoJSON file."""
        with open(path, 'w') as f:
            json.dump(self.to_geojson(), f, indent=2)


class OntarioVectorDownloader:
    """
    Download vector data from Ontario GeoHub.

    Usage:
        downloader = OntarioVectorDownloader()
        roads = downloader.get_roads(lat=46.26, lng=-80.45, radius_km=1)
        water = downloader.get_water_bodies(lat=46.26, lng=-80.45, radius_km=2)
    """

    def __init__(self):
        if not HAS_REQUESTS:
            raise RuntimeError("requests library required. Install with: pip install requests")

    def _query_layer(
        self,
        layer_url: str,
        bbox: Tuple[float, float, float, float],
        out_fields: str = "*",
        max_features: int = 5000,
    ) -> List[Dict]:
        """
        Query an ArcGIS REST layer for features within a bounding box.

        Args:
            layer_url: Full URL to the layer (MapServer/N or FeatureServer/N)
            bbox: (min_lng, min_lat, max_lng, max_lat) in WGS84
            out_fields: Fields to return ("*" for all)
            max_features: Maximum features to return

        Returns:
            List of feature dictionaries
        """
        min_lng, min_lat, max_lng, max_lat = bbox

        params = {
            "where": "1=1",
            "geometry": f"{min_lng},{min_lat},{max_lng},{max_lat}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": out_fields,
            "returnGeometry": "true",
            "resultRecordCount": max_features,
            "f": "json"
        }

        query_url = f"{layer_url}/query"

        try:
            response = requests.get(query_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                print(f"[OntarioVectors] API error: {data['error']}")
                return []

            return data.get("features", [])

        except Exception as e:
            print(f"[OntarioVectors] Query failed: {e}")
            return []

    def _bbox_from_center(
        self,
        lat: float,
        lng: float,
        radius_km: float
    ) -> Tuple[float, float, float, float]:
        """Create bounding box from center point and radius."""
        # Approximate degrees per km
        lat_per_km = 1 / 111.0
        lng_per_km = 1 / (111.0 * math.cos(math.radians(lat)))

        lat_delta = radius_km * lat_per_km
        lng_delta = radius_km * lng_per_km

        return (
            lng - lng_delta,  # min_lng
            lat - lat_delta,  # min_lat
            lng + lng_delta,  # max_lng
            lat + lat_delta,  # max_lat
        )

    def get_roads(
        self,
        lat: float,
        lng: float,
        radius_km: float = 1.0,
        max_features: int = 2000,
    ) -> VectorDataset:
        """
        Get road network within radius of a point.

        Args:
            lat: Center latitude
            lng: Center longitude
            radius_km: Search radius in kilometers
            max_features: Maximum road segments to return

        Returns:
            VectorDataset with road features
        """
        bbox = self._bbox_from_center(lat, lng, radius_km)
        layer_url = f"{LIO_OPEN_DATA_BASE}/{LAYER_IDS['roads']}"

        print(f"[OntarioVectors] Querying roads within {radius_km}km of ({lat}, {lng})...")

        raw_features = self._query_layer(
            layer_url,
            bbox,
            out_fields="FULL_STREET_NAME,ROAD_CLASS,SPEED_LIMIT,NUM_OF_LANES",
            max_features=max_features
        )

        dataset = VectorDataset(name="Ontario Roads")

        for feat in raw_features:
            geom = feat.get("geometry", {})
            attrs = feat.get("attributes", {})

            if "paths" in geom:
                dataset.features.append(VectorFeature(
                    geometry_type="polyline",
                    coordinates=geom["paths"],
                    attributes={
                        "name": attrs.get("FULL_STREET_NAME", ""),
                        "road_class": attrs.get("ROAD_CLASS", ""),
                        "speed_limit": attrs.get("SPEED_LIMIT"),
                        "lanes": attrs.get("NUM_OF_LANES"),
                    }
                ))

        print(f"[OntarioVectors] Found {len(dataset.features)} road segments")
        return dataset

    def get_water_bodies(
        self,
        lat: float,
        lng: float,
        radius_km: float = 2.0,
        max_features: int = 500,
    ) -> VectorDataset:
        """
        Get water bodies (lakes, ponds) within radius of a point.

        Args:
            lat: Center latitude
            lng: Center longitude
            radius_km: Search radius in kilometers
            max_features: Maximum features to return

        Returns:
            VectorDataset with water body features
        """
        bbox = self._bbox_from_center(lat, lng, radius_km)
        layer_url = f"{LIO_OPEN_DATA_BASE}/{LAYER_IDS['waterbody']}"

        print(f"[OntarioVectors] Querying water bodies within {radius_km}km of ({lat}, {lng})...")

        raw_features = self._query_layer(
            layer_url,
            bbox,
            out_fields="OFFICIAL_NAME,WATERBODY_TYPE,PERMANENCY",
            max_features=max_features
        )

        dataset = VectorDataset(name="Ontario Water Bodies")

        for feat in raw_features:
            geom = feat.get("geometry", {})
            attrs = feat.get("attributes", {})

            if "rings" in geom:
                dataset.features.append(VectorFeature(
                    geometry_type="polygon",
                    coordinates=geom["rings"],
                    attributes={
                        "name": attrs.get("OFFICIAL_NAME", ""),
                        "type": attrs.get("WATERBODY_TYPE", ""),
                        "permanency": attrs.get("PERMANENCY", ""),
                    }
                ))

        print(f"[OntarioVectors] Found {len(dataset.features)} water bodies")
        return dataset

    def get_watercourses(
        self,
        lat: float,
        lng: float,
        radius_km: float = 2.0,
        max_features: int = 1000,
    ) -> VectorDataset:
        """
        Get watercourses (rivers, streams) within radius of a point.

        Args:
            lat: Center latitude
            lng: Center longitude
            radius_km: Search radius in kilometers
            max_features: Maximum features to return

        Returns:
            VectorDataset with watercourse features
        """
        bbox = self._bbox_from_center(lat, lng, radius_km)
        layer_url = f"{LIO_OPEN_DATA_BASE}/{LAYER_IDS['watercourse']}"

        print(f"[OntarioVectors] Querying watercourses within {radius_km}km of ({lat}, {lng})...")

        raw_features = self._query_layer(
            layer_url,
            bbox,
            out_fields="OFFICIAL_NAME,WATERCOURSE_TYPE,PERMANENCY",
            max_features=max_features
        )

        dataset = VectorDataset(name="Ontario Watercourses")

        for feat in raw_features:
            geom = feat.get("geometry", {})
            attrs = feat.get("attributes", {})

            if "paths" in geom:
                dataset.features.append(VectorFeature(
                    geometry_type="polyline",
                    coordinates=geom["paths"],
                    attributes={
                        "name": attrs.get("OFFICIAL_NAME", ""),
                        "type": attrs.get("WATERCOURSE_TYPE", ""),
                        "permanency": attrs.get("PERMANENCY", ""),
                    }
                ))

        print(f"[OntarioVectors] Found {len(dataset.features)} watercourses")
        return dataset

    def get_municipal_boundary(
        self,
        lat: float,
        lng: float,
    ) -> Optional[VectorFeature]:
        """
        Get the municipal boundary containing a point.

        Args:
            lat: Latitude
            lng: Longitude

        Returns:
            VectorFeature for the municipality, or None
        """
        # Small bbox around the point
        bbox = self._bbox_from_center(lat, lng, 0.1)
        layer_url = f"{LIO_OPEN_DATA_BASE}/{LAYER_IDS['municipal']}"

        raw_features = self._query_layer(
            layer_url,
            bbox,
            out_fields="MUNICIPAL_NAME,UPPER_TIER_NAME",
            max_features=1
        )

        if raw_features:
            feat = raw_features[0]
            geom = feat.get("geometry", {})
            attrs = feat.get("attributes", {})

            if "rings" in geom:
                return VectorFeature(
                    geometry_type="polygon",
                    coordinates=geom["rings"],
                    attributes={
                        "name": attrs.get("MUNICIPAL_NAME", ""),
                        "upper_tier": attrs.get("UPPER_TIER_NAME", ""),
                    }
                )

        return None

    def get_all_site_data(
        self,
        lat: float,
        lng: float,
        radius_km: float = 1.0,
    ) -> Dict[str, VectorDataset]:
        """
        Get all relevant vector data for a site.

        Args:
            lat: Site center latitude
            lng: Site center longitude
            radius_km: Search radius

        Returns:
            Dict with "roads", "water_bodies", "watercourses" datasets
        """
        return {
            "roads": self.get_roads(lat, lng, radius_km),
            "water_bodies": self.get_water_bodies(lat, lng, radius_km * 2),
            "watercourses": self.get_watercourses(lat, lng, radius_km * 2),
        }


def download_ontario_site_context(
    lat: float,
    lng: float,
    output_dir: str,
    radius_km: float = 1.0,
) -> Dict[str, str]:
    """
    Download all Ontario context data for a site location.

    Args:
        lat: Site latitude
        lng: Site longitude
        output_dir: Directory to save GeoJSON files
        radius_km: Search radius

    Returns:
        Dict mapping layer name to output file path
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    downloader = OntarioVectorDownloader()
    data = downloader.get_all_site_data(lat, lng, radius_km)

    output_files = {}

    for name, dataset in data.items():
        if dataset.features:
            file_path = output_path / f"{name}.geojson"
            dataset.save_geojson(str(file_path))
            output_files[name] = str(file_path)
            print(f"[OntarioVectors] Saved {len(dataset.features)} {name} to {file_path}")

    return output_files
