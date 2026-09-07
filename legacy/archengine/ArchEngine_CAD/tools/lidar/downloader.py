"""
Ontario LiDAR Data Downloader
=============================
Download DTM and DSM GeoTIFF tiles from Ontario's open data portal.

Data sources:
- Ontario GeoHub: https://geohub.lio.gov.on.ca
- Download server: https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/
"""

import os
import json
import zipfile
import tempfile
import shutil
from dataclasses import dataclass
from typing import List, Optional, Callable, Tuple
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from .transform import UtmTransformer

# Ontario LiDAR package download base URL
PACKAGE_BASE_URL = "https://ws.gisetl.lrc.gov.on.ca/fmedatadownload/Packages/"

# Tile index URL (contains boundaries for all packages)
TILE_INDEX_URL = "https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioDSM_LidarDerived_TileIndex.zip"
PROJECT_EXTENTS_URL = "https://www.publicdocs.mnr.gov.on.ca/mirb/OntarioLidarProjectExtents.zip"

# Known packages with approximate coverage (lat_min, lat_max, lng_min, lng_max)
# This is a subset - the full index should be downloaded for complete coverage
KNOWN_PACKAGES = {
    # Lake Nipissing area
    "LakeNipissing": {
        "bounds": (46.0, 46.5, -80.8, -79.8),
        "packages": ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"],
    },
    # Sudbury area
    "Sudbury": {
        "bounds": (46.3, 46.7, -81.2, -80.6),
        "packages": ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10"],
    },
    # Toronto/GTA area
    "GTA-Peel": {
        "bounds": (43.4, 44.0, -80.0, -79.2),
        "packages": ["01", "02", "03", "04", "05"],
    },
    "GTA-York": {
        "bounds": (43.7, 44.3, -79.8, -79.2),
        "packages": ["01", "02", "03", "04", "05"],
    },
    # Ottawa area
    "Ottawa": {
        "bounds": (45.2, 45.6, -76.0, -75.4),
        "packages": ["01", "02", "03", "04", "05", "06", "07", "08"],
    },
    # Peterborough area
    "Peterborough": {
        "bounds": (44.0, 44.6, -78.6, -77.8),
        "packages": ["01", "02", "03", "04", "05", "06", "07", "08"],
    },
    # Thunder Bay area
    "ThunderBay": {
        "bounds": (48.2, 48.6, -89.6, -88.8),
        "packages": ["01", "02", "03", "04", "05"],
    },
}


@dataclass
class PackageInfo:
    """Information about a LiDAR data package."""
    name: str  # e.g., "LakeNipissing"
    number: str  # e.g., "05"
    data_type: str  # "DSM" or "DTM"

    @property
    def full_name(self) -> str:
        """Full package name like 'LakeNipissing-DSM-05'."""
        return f"{self.name}-{self.data_type}-{self.number}"

    @property
    def filename(self) -> str:
        """ZIP filename."""
        return f"{self.full_name}.zip"

    @property
    def download_url(self) -> str:
        """Full download URL."""
        return urljoin(PACKAGE_BASE_URL, self.filename)


class LidarDownloader:
    """
    Download Ontario LiDAR data packages.

    Usage:
        downloader = LidarDownloader(output_dir="/path/to/lidar")
        packages = downloader.find_packages(lat=46.2615, lng=-80.4548)
        downloader.download_packages(packages, data_types=["DTM", "DSM"])
    """

    def __init__(self, output_dir: str):
        """
        Initialize downloader.

        Args:
            output_dir: Directory to save downloaded data
        """
        if not HAS_REQUESTS:
            raise RuntimeError("requests library required. Install with: pip install requests")

        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._transformer = UtmTransformer(17, northern=True)

    def find_packages(self, lat: float, lng: float) -> List[str]:
        """
        Find which package regions cover the given coordinates.

        Args:
            lat: Latitude
            lng: Longitude

        Returns:
            List of region names (e.g., ["LakeNipissing"])
        """
        matching = []

        for name, info in KNOWN_PACKAGES.items():
            bounds = info["bounds"]
            lat_min, lat_max, lng_min, lng_max = bounds

            if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
                matching.append(name)

        return matching

    def find_package_numbers(
        self,
        lat: float,
        lng: float,
        region: str,
        search_radius_km: float = 2.0,
    ) -> List[str]:
        """
        Find which package numbers within a region likely contain the coordinates.

        This uses a heuristic based on UTM coordinates - for exact matching,
        the tile index should be downloaded and parsed.

        Args:
            lat: Latitude
            lng: Longitude
            region: Region name (e.g., "LakeNipissing")
            search_radius_km: Search radius in km

        Returns:
            List of package numbers to try (e.g., ["05", "06"])
        """
        if region not in KNOWN_PACKAGES:
            return []

        # For now, return all packages in the region
        # A more sophisticated approach would use the tile index
        return KNOWN_PACKAGES[region]["packages"]

    def get_package_info(
        self,
        lat: float,
        lng: float,
        data_types: List[str] = None,
    ) -> List[PackageInfo]:
        """
        Get package info for downloading data at coordinates.

        Args:
            lat: Latitude
            lng: Longitude
            data_types: List of data types ["DTM", "DSM"], default both

        Returns:
            List of PackageInfo objects
        """
        if data_types is None:
            data_types = ["DTM", "DSM"]

        packages = []
        regions = self.find_packages(lat, lng)

        for region in regions:
            numbers = self.find_package_numbers(lat, lng, region)
            for num in numbers:
                for dtype in data_types:
                    packages.append(PackageInfo(
                        name=region,
                        number=num,
                        data_type=dtype,
                    ))

        return packages

    def check_package_exists(self, package: PackageInfo) -> bool:
        """Check if a package exists on the server."""
        try:
            response = requests.head(package.download_url, timeout=10)
            return response.status_code == 200
        except:
            return False

    def download_package(
        self,
        package: PackageInfo,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        extract: bool = True,
    ) -> Optional[Path]:
        """
        Download a single package.

        Args:
            package: Package info
            progress_callback: Optional callback(bytes_downloaded, total_bytes, message)
            extract: Whether to extract the ZIP file

        Returns:
            Path to extracted folder or ZIP file, None on failure
        """
        output_folder = self.output_dir / package.full_name

        # Check if already downloaded
        if output_folder.exists() and any(output_folder.glob("*.tif")):
            if progress_callback:
                progress_callback(100, 100, f"{package.full_name} already downloaded")
            return output_folder

        # Download
        zip_path = self.output_dir / package.filename

        try:
            if progress_callback:
                progress_callback(0, 100, f"Downloading {package.full_name}...")

            response = requests.get(package.download_url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total_size > 0:
                        pct = int(downloaded * 100 / total_size)
                        mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        progress_callback(
                            downloaded, total_size,
                            f"Downloading {package.full_name}: {mb:.1f}/{total_mb:.1f} MB"
                        )

            # Extract
            if extract:
                if progress_callback:
                    progress_callback(100, 100, f"Extracting {package.full_name}...")

                output_folder.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(output_folder)

                # Clean up ZIP
                zip_path.unlink()

                if progress_callback:
                    tif_count = len(list(output_folder.rglob("*.tif")))
                    progress_callback(100, 100, f"Extracted {tif_count} tiles to {package.full_name}")

                return output_folder
            else:
                return zip_path

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                if progress_callback:
                    progress_callback(0, 100, f"Package {package.full_name} not found (404)")
                return None
            raise
        except Exception as e:
            if progress_callback:
                progress_callback(0, 100, f"Error: {e}")
            if zip_path.exists():
                zip_path.unlink()
            return None

    def download_for_location(
        self,
        lat: float,
        lng: float,
        data_types: List[str] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[Path]:
        """
        Download all relevant packages for a location.

        Args:
            lat: Latitude
            lng: Longitude
            data_types: List of data types ["DTM", "DSM"]
            progress_callback: Progress callback

        Returns:
            List of paths to downloaded/extracted folders
        """
        if data_types is None:
            data_types = ["DTM"]  # Default to just DTM for terrain

        packages = self.get_package_info(lat, lng, data_types)
        downloaded = []

        # Try to find and download the right package
        for pkg in packages:
            if progress_callback:
                progress_callback(0, 100, f"Checking {pkg.full_name}...")

            if self.check_package_exists(pkg):
                path = self.download_package(pkg, progress_callback)
                if path:
                    downloaded.append(path)
                    # For now, stop after first successful download per type
                    # (we found the right package number)
                    break

        return downloaded


def find_available_regions() -> List[str]:
    """Get list of known regions with LiDAR data."""
    return list(KNOWN_PACKAGES.keys())


def get_region_bounds(region: str) -> Optional[Tuple[float, float, float, float]]:
    """Get approximate bounds for a region."""
    if region in KNOWN_PACKAGES:
        return KNOWN_PACKAGES[region]["bounds"]
    return None
