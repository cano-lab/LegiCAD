"""
Coordinate transformation utilities.

Handles UTM <-> WGS84 conversions for Ontario LiDAR data.
"""

import math
from dataclasses import dataclass
from typing import Tuple, Optional

# Try to use pyproj if available (more accurate), fall back to manual formula
try:
    from pyproj import Transformer, CRS
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False


@dataclass
class UtmCoord:
    """UTM coordinate with zone info."""
    easting: float
    northing: float
    zone: int
    northern: bool = True


class UtmTransformer:
    """
    Transform coordinates between WGS84 (lat/lng) and UTM.

    Uses pyproj if available for accuracy, otherwise falls back to
    manual formulas.
    """

    def __init__(self, zone: int = 17, northern: bool = True):
        """
        Create transformer for a specific UTM zone.

        Args:
            zone: UTM zone number (1-60). Default 17 for Ontario.
            northern: True for northern hemisphere.
        """
        self.zone = zone
        self.northern = northern

        if HAS_PYPROJ:
            # EPSG codes: 326xx for north, 327xx for south
            epsg = 32600 + zone if northern else 32700 + zone
            self._to_utm = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
            self._from_utm = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
        else:
            self._to_utm = None
            self._from_utm = None

    def wgs84_to_utm(self, lat: float, lng: float) -> Tuple[float, float]:
        """
        Transform WGS84 coordinates to UTM.

        Args:
            lat: Latitude in degrees
            lng: Longitude in degrees

        Returns:
            (easting, northing) in meters
        """
        if HAS_PYPROJ and self._to_utm:
            return self._to_utm.transform(lng, lat)
        return _manual_wgs84_to_utm(lat, lng, self.zone, self.northern)

    def utm_to_wgs84(self, easting: float, northing: float) -> Tuple[float, float]:
        """
        Transform UTM coordinates to WGS84.

        Args:
            easting: UTM easting in meters
            northing: UTM northing in meters

        Returns:
            (latitude, longitude) in degrees
        """
        if HAS_PYPROJ and self._from_utm:
            lng, lat = self._from_utm.transform(easting, northing)
            return lat, lng
        return _manual_utm_to_wgs84(easting, northing, self.zone, self.northern)


def wgs84_to_utm(lat: float, lng: float, zone: int = 17, northern: bool = True) -> Tuple[float, float]:
    """
    Transform WGS84 to UTM (convenience function).

    Args:
        lat: Latitude
        lng: Longitude
        zone: UTM zone (default 17 for Ontario)
        northern: Northern hemisphere

    Returns:
        (easting, northing)
    """
    transformer = UtmTransformer(zone, northern)
    return transformer.wgs84_to_utm(lat, lng)


def utm_to_wgs84(easting: float, northing: float, zone: int = 17, northern: bool = True) -> Tuple[float, float]:
    """
    Transform UTM to WGS84 (convenience function).

    Args:
        easting: UTM easting
        northing: UTM northing
        zone: UTM zone (default 17)
        northern: Northern hemisphere

    Returns:
        (latitude, longitude)
    """
    transformer = UtmTransformer(zone, northern)
    return transformer.utm_to_wgs84(easting, northing)


def _manual_wgs84_to_utm(lat: float, lng: float, zone: int, northern: bool) -> Tuple[float, float]:
    """Manual UTM projection (when pyproj not available)."""
    # WGS84 parameters
    a = 6378137.0  # Semi-major axis
    f = 1.0 / 298.257223563  # Flattening
    k0 = 0.9996  # UTM scale factor
    e2 = 2 * f - f * f  # First eccentricity squared

    lat_rad = math.radians(lat)
    lng_rad = math.radians(lng)

    # Central meridian for this zone
    lng0 = math.radians((zone - 1) * 6 - 180 + 3)

    n = a / math.sqrt(1 - e2 * math.sin(lat_rad) ** 2)
    t = math.tan(lat_rad) ** 2
    c = e2 / (1 - e2) * math.cos(lat_rad) ** 2
    a_coef = (lng_rad - lng0) * math.cos(lat_rad)

    # Meridional arc
    e2_2 = e2 * e2
    e2_3 = e2_2 * e2
    m = a * (
        (1 - e2/4 - 3*e2_2/64 - 5*e2_3/256) * lat_rad
        - (3*e2/8 + 3*e2_2/32 + 45*e2_3/1024) * math.sin(2*lat_rad)
        + (15*e2_2/256 + 45*e2_3/1024) * math.sin(4*lat_rad)
        - (35*e2_3/3072) * math.sin(6*lat_rad)
    )

    easting = k0 * n * (
        a_coef
        + (1 - t + c) * a_coef**3 / 6
        + (5 - 18*t + t**2 + 72*c - 58*e2/(1-e2)) * a_coef**5 / 120
    ) + 500000  # False easting

    northing = k0 * (
        m + n * math.tan(lat_rad) * (
            a_coef**2 / 2
            + (5 - t + 9*c + 4*c**2) * a_coef**4 / 24
            + (61 - 58*t + t**2 + 600*c - 330*e2/(1-e2)) * a_coef**6 / 720
        )
    )

    if not northern:
        northing += 10_000_000  # False northing for southern hemisphere

    return easting, northing


def _manual_utm_to_wgs84(easting: float, northing: float, zone: int, northern: bool) -> Tuple[float, float]:
    """Manual inverse UTM projection (when pyproj not available)."""
    a = 6378137.0
    f = 1.0 / 298.257223563
    k0 = 0.9996
    e2 = 2 * f - f * f
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    # Remove false easting/northing
    x = easting - 500000
    y = northing
    if not northern:
        y -= 10_000_000

    # Central meridian
    lng0 = math.radians((zone - 1) * 6 - 180 + 3)

    # Footpoint latitude
    m = y / k0
    mu = m / (a * (1 - e2/4 - 3*e2**2/64 - 5*e2**3/256))

    phi1 = mu + (3*e1/2 - 27*e1**3/32) * math.sin(2*mu)
    phi1 += (21*e1**2/16 - 55*e1**4/32) * math.sin(4*mu)
    phi1 += (151*e1**3/96) * math.sin(6*mu)
    phi1 += (1097*e1**4/512) * math.sin(8*mu)

    n1 = a / math.sqrt(1 - e2 * math.sin(phi1)**2)
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1)**2)**1.5
    t1 = math.tan(phi1)**2
    c1 = e2 / (1 - e2) * math.cos(phi1)**2
    d = x / (n1 * k0)

    lat = phi1 - (n1 * math.tan(phi1) / r1) * (
        d**2 / 2
        - (5 + 3*t1 + 10*c1 - 4*c1**2 - 9*e2/(1-e2)) * d**4 / 24
        + (61 + 90*t1 + 298*c1 + 45*t1**2 - 252*e2/(1-e2) - 3*c1**2) * d**6 / 720
    )

    lng = lng0 + (
        d
        - (1 + 2*t1 + c1) * d**3 / 6
        + (5 - 2*c1 + 28*t1 - 3*c1**2 + 8*e2/(1-e2) + 24*t1**2) * d**5 / 120
    ) / math.cos(phi1)

    return math.degrees(lat), math.degrees(lng)


def latlon_distance_meters(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate distance between two WGS84 points in meters.

    Uses Haversine formula.
    """
    R = 6371000  # Earth radius in meters

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)

    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlng/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return R * c


def meters_to_degrees(meters: float, latitude: float) -> Tuple[float, float]:
    """
    Convert meters to degrees at a given latitude.

    Returns:
        (lat_degrees, lng_degrees) for the given distance in meters
    """
    lat_deg = meters / 111000  # ~111km per degree latitude
    lng_deg = meters / (111000 * math.cos(math.radians(latitude)))
    return lat_deg, lng_deg
