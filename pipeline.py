import argparse
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Any
from parser import CityParser, AddressParser, DistrictMatcher, StreetNormalizer
from db_builder import build_database

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def run_clip(input_pbf: Path, output_pbf: Path, bbox: str) -> None:
    logger.info(f"Clipping {input_pbf} to {output_pbf} using bbox {bbox}...")
    subprocess.run([
        "osmium", "extract", "-b", bbox, str(input_pbf), "-o", str(output_pbf), "--overwrite"
    ], check=True)

def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Geocoding DB Generator")
    parser.add_argument("--input", type=str, required=True, help="Path to input OSM PBF file")
    parser.add_argument("--region", type=str, required=True, help="Region name to process (must be in regions.json)")
    parser.add_argument("--regions-file", type=str, default="regions.json", help="Path to regions.json")
    parser.add_argument("--output-dir", type=str, default="output", help="Directory to save the DB")
    args = parser.parse_args()

    input_pbf = Path(args.input)
    if not input_pbf.exists():
        raise FileNotFoundError(f"Input file {input_pbf} does not exist.")

    with open(args.regions_file, 'r', encoding='utf-8') as f:
        regions: Dict[str, Any] = json.load(f)

    if args.region not in regions:
        raise ValueError(f"Region {args.region} not found in {args.regions_file}")

    region_info = regions[args.region]
    bbox = region_info['bbox']
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    clipped_pbf = output_dir / f"{args.region}-latest.osm.pbf"
    db_path = output_dir / f"{args.region}_region.db"

    # Step 1: Clip
    run_clip(input_pbf, clipped_pbf, bbox)

    # Step 2: Parse Cities (Pass 1)
    logger.info("Pass 1: Extracting cities...")
    region_name_uk = region_info.get('name_uk', args.region)
    region_name_en = region_info.get('name_en', args.region)
    district_matcher = DistrictMatcher(Path("boundaries/rayony.geojson"))
    city_parser = CityParser(
        region_name_uk=region_name_uk,
        region_name_en=region_name_en,
        district_matcher=district_matcher
    )
    city_parser.apply_file(str(clipped_pbf))
    logger.info(f"Extracted {len(city_parser.cities)} cities.")

    # Step 3: Parse Streets & Houses (Pass 2 & 3 combined using node cache)
    logger.info("Pass 2: Extracting streets and houses...")
    address_parser = AddressParser(city_parser.cities)
    address_parser.apply_file(str(clipped_pbf), locations=True)
    logger.info(f"Extracted {len(address_parser.streets)} streets and {len(address_parser.houses)} houses.")

    # Post-process: Link houses to valid street IDs
    logger.info("Linking houses to streets...")
    valid_houses: List[Dict[str, Any]] = []
    for house in address_parser.houses:
        raw_key = f"{house['city_id']}_{house['raw_street_name']}"
        street_key = address_parser.raw_to_street_key.get(raw_key)

        # Fallback via normalized name
        if not street_key:
            clean_name, type_id = StreetNormalizer.normalize(house['raw_street_name'])
            candidate_key = f"{house['city_id']}_{clean_name}_{type_id}"
            if candidate_key in address_parser.streets:
                street_key = candidate_key
            else:
                street_key = address_parser.raw_to_street_key.get(f"{house['city_id']}_{clean_name}")

        if street_key and street_key in address_parser.streets:
            street_id = address_parser.streets[street_key]['db_id']
            house['street_id'] = street_id
            valid_houses.append(house)

    logger.info(f"Linked {len(valid_houses)} houses to known streets.")

    # Step 4: Build SQLite Database
    build_database(db_path, city_parser.cities, list(address_parser.streets.values()), valid_houses)

if __name__ == "__main__":
    main()
