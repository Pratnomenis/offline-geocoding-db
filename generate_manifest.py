import argparse
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

def compute_sha256(file_path: Path) -> str:
    """Computes SHA-256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256_hash.update(chunk)
    return sha256_hash.hexdigest()

def generate_manifest(output_dir: Path, regions_file: Path = Path("regions.json")) -> Path:
    """Generates manifest.json with metadata for all compressed database files."""
    regions_meta: Dict[str, Any] = {}
    if regions_file.exists():
        with open(regions_file, "r", encoding="utf-8") as f:
            regions_meta = json.load(f)

    manifest_path = output_dir / "manifest.json"
    files_list: List[Dict[str, Any]] = []

    # Look for all .db.gz files in output directory
    gz_files = sorted(output_dir.glob("*.db.gz"))
    if not gz_files:
        # Fallback to .db if uncompressed files are found
        gz_files = sorted(output_dir.glob("*.db"))

    for file_path in gz_files:
        # Region name can be extracted from filename e.g. "kyiv_region.db.gz" -> "kyiv"
        file_stem = file_path.name
        region_id = file_stem.split("_region.db")[0]
        region_info = regions_meta.get(region_id, {})

        size_bytes = file_path.stat().st_size
        sha256 = compute_sha256(file_path)

        entry = {
            "id": region_id,
            "name_uk": region_info.get("name_uk", region_id),
            "name_en": region_info.get("name_en", region_id),
            "filename": file_path.name,
            "size_bytes": size_bytes,
            "sha256": sha256
        }
        files_list.append(entry)

    manifest = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "regions": files_list
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    logger.info(f"Manifest generated successfully at {manifest_path} with {len(files_list)} items.")
    return manifest_path

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate manifest.json for offline geocoding databases")
    parser.add_argument("--output-dir", type=str, default="output", help="Directory containing database files")
    parser.add_argument("--regions-file", type=str, default="regions.json", help="Path to regions.json")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generate_manifest(output_dir, Path(args.regions_file))

if __name__ == "__main__":
    main()
