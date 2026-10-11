import os
import time
import requests
from pathlib import Path
from tqdm import tqdm

GEOFABRIK_URL = "https://download.geofabrik.de/europe/ukraine-latest.osm.pbf"
RAYONY_URL = "https://raw.githubusercontent.com/slawomirmatuszak/ukrainian_geodata/main/rayony.geojson"
DATA_DIR = Path("data")
BOUNDARIES_DIR = Path("boundaries")
OSM_FILE = DATA_DIR / "ukraine-latest.osm.pbf"
RAYONY_FILE = BOUNDARIES_DIR / "rayony.geojson"
MAX_FILE_AGE_DAYS = 1

def is_file_fresh(filepath: Path, max_age_days: int) -> bool:
    """Checks if a file exists and is newer than max_age_days."""
    if not filepath.exists():
        return False
    file_age_seconds = time.time() - filepath.stat().st_mtime
    file_age_days = file_age_seconds / (24 * 3600)
    return file_age_days < max_age_days

def download_file(url: str, output_path: Path) -> None:
    """Downloads a file from url to output_path with a progress bar."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    response = requests.get(url, stream=True)
    response.raise_for_status()
    
    total_size = int(response.headers.get('content-length', 0))
    
    with open(output_path, 'wb') as file, tqdm(
        desc=output_path.name,
        total=total_size,
        unit='iB',
        unit_scale=True,
        unit_divisor=1024,
    ) as bar:
        for data in response.iter_content(chunk_size=1024*1024):
            size = file.write(data)
            bar.update(size)

def main() -> None:
    if not RAYONY_FILE.exists():
        print(f"Downloading district boundaries from {RAYONY_URL} to {RAYONY_FILE}...")
        download_file(RAYONY_URL, RAYONY_FILE)
        print("District boundaries download complete.")
    else:
        print(f"District boundaries file {RAYONY_FILE} already exists.")

    if is_file_fresh(OSM_FILE, MAX_FILE_AGE_DAYS):
        print(f"File {OSM_FILE} is less than {MAX_FILE_AGE_DAYS} day(s) old. Using cached version.")
    else:
        print(f"Downloading {GEOFABRIK_URL} to {OSM_FILE}...")
        download_file(GEOFABRIK_URL, OSM_FILE)
        print("Download complete.")

if __name__ == "__main__":
    main()
