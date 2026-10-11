import gzip
import json
import sqlite3
import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Provide lightweight mock if running on an environment without osmium/shapely installed
if "osmium" not in sys.modules:
    try:
        import osmium
    except ImportError:
        mock_osmium = MagicMock()
        class MockSimpleHandler:
            pass
        mock_osmium.SimpleHandler = MockSimpleHandler
        mock_osmium.InvalidLocationError = Exception
        sys.modules["osmium"] = mock_osmium

if "shapely" not in sys.modules:
    try:
        import shapely
    except ImportError:
        mock_shapely = MagicMock()
        mock_geom = MagicMock()
        mock_strtree = MagicMock()
        sys.modules["shapely"] = mock_shapely
        sys.modules["shapely.geometry"] = mock_geom
        sys.modules["shapely.strtree"] = mock_strtree

from transliterator import transliterate_uk, transliterate_house_number
from parser import DistrictMatcher, StreetNormalizer, CityParser
from db_builder import build_database
from generate_manifest import generate_manifest, compute_sha256

def test_transliteration():
    # KMU 55 official test cases
    assert transliterate_uk("Київ") == "Kyiv"
    assert transliterate_uk("Князів Острозьких") == "Kniaziv Ostrozkykh"
    assert transliterate_uk("Згорани") == "Zghorany"
    assert transliterate_uk("Розгон") == "Rozghon"
    assert transliterate_uk("Єнакієве") == "Yenakiieve"
    assert transliterate_uk("Мар'їне") == "Marine"
    assert transliterate_uk("Знам'янка") == "Znamianka"
    assert transliterate_uk("Юрій") == "Yurii"
    assert transliterate_uk("Московська") == "Moskovska"
    
    # House numbers
    assert transliterate_house_number("10-А") == "10-A"
    assert transliterate_house_number("12 корп. 3") == "12 bldg. 3"
    assert transliterate_house_number("5/1-Б") == "5/1-B"
    assert transliterate_house_number("10-А корп. 1") == "10-A bldg. 1"
    print("Transliteration tests passed.")

def test_district_matcher():
    # Test GeoJSON data properties integrity
    with open("boundaries/rayony.geojson", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data.get("features", [])) == 136
    for feat in data["features"]:
        props = feat["properties"]
        assert "rayon" in props and len(props["rayon"]) > 0
        assert "rayon_en" in props and len(props["rayon_en"]) > 0
        assert props["rayon_en"].endswith("Raion")

    matcher = DistrictMatcher(Path("boundaries/rayony.geojson"))
    if matcher.enabled and not isinstance(sys.modules.get("shapely"), MagicMock):
        uk, en = matcher.find_district(49.58, 34.55)
        assert uk is not None and en is not None
        assert "район" in uk.lower()
        assert "raion" in en.lower()
    print("DistrictMatcher and rayony.geojson validation tests passed.")

def test_street_normalizer():
    clean, type_id = StreetNormalizer.normalize("вулиця Хрещатик")
    assert clean == "Хрещатик"
    assert type_id == 1

    clean, type_id = StreetNormalizer.normalize("просп. Перемоги")
    assert clean == "Перемоги"
    assert type_id == 2

    clean_en = StreetNormalizer.normalize_en("Khreshchatyk Street")
    assert clean_en == "Khreshchatyk"

    clean_en = StreetNormalizer.normalize_en("Peremohy Avenue")
    assert clean_en == "Peremohy"
    print("StreetNormalizer tests passed.")

def test_database_build_and_queries():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_region.db"
        cities = [
            {
                "db_id": 1,
                "osm_id": 100,
                "name": "Київ",
                "name_en": "Kyiv",
                "city_type": "місто",
                "city_type_en": "city",
                "district": None,
                "district_en": None,
                "region": "Київська область",
                "region_en": "Kyiv Oblast",
                "postcode": "01001",
                "lat": 50.4501,
                "lon": 30.5234
            }
        ]

        streets = [
            {
                "db_id": 1,
                "city_id": 1,
                "name": "Князів Острозьких",
                "name_en": "Kniaziv Ostrozkykh",
                "old_name": "Московська",
                "type_id": 1,
                "lat": 50.4400,
                "lon": 30.5400,
                "osm_id": 200
            }
        ]

        houses = [
            {
                "street_id": 1,
                "number": "10-А",
                "number_en": "10-A",
                "postcode": "01010",
                "lat": 50.4405,
                "lon": 30.5405,
                "osm_id": 300
            }
        ]

        build_database(db_path, cities, streets, houses)
        assert db_path.exists()

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        # Check schema
        cur.execute("PRAGMA table_info(cities)")
        city_cols = [row[1] for row in cur.fetchall()]
        assert "name_en" in city_cols
        assert "city_type" in city_cols
        assert "city_type_en" in city_cols
        assert "district_en" in city_cols
        assert "region_en" in city_cols
        assert "postcode" in city_cols

        cur.execute("PRAGMA table_info(streets)")
        street_cols = [row[1] for row in cur.fetchall()]
        assert "name_en" in street_cols
        assert "old_name" in street_cols

        cur.execute("PRAGMA table_info(houses)")
        house_cols = [row[1] for row in cur.fetchall()]
        assert "number_en" in house_cols
        assert "postcode" in house_cols

        # Test Reverse Geocoding with R*Tree
        # Search bounding box containing 50.4405, 30.5405
        cur.execute("""
            SELECT id FROM houses_rtree
            WHERE min_lat <= 50.4406 AND max_lat >= 50.4404
              AND min_lon <= 30.5406 AND max_lon >= 30.5404
        """)
        rtree_res = cur.fetchall()
        assert len(rtree_res) == 1
        assert rtree_res[0][0] == 1

        # Test FTS5 search for modern street name in Ukrainian
        cur.execute("SELECT entity_id, type FROM places_fts WHERE places_fts MATCH 'Князів'")
        fts_res = cur.fetchall()
        assert len(fts_res) == 1
        assert fts_res[0][0] == 1

        # Test FTS5 search for modern street name in English
        cur.execute("SELECT entity_id, type FROM places_fts WHERE places_fts MATCH 'Ostrozkykh'")
        fts_res_en = cur.fetchall()
        assert len(fts_res_en) == 1
        assert fts_res_en[0][0] == 1

        # Test FTS5 search for DECOMMUNIZED old street name
        cur.execute("SELECT entity_id, type FROM places_fts WHERE places_fts MATCH 'Московська'")
        fts_res_old = cur.fetchall()
        assert len(fts_res_old) == 1
        assert fts_res_old[0][0] == 1

        # Test FTS5 search for house number in Ukrainian and English (double-quoted for FTS5 hyphen syntax)
        cur.execute('SELECT entity_id FROM places_fts WHERE places_fts MATCH \'"10-А"\'')
        assert len(cur.fetchall()) == 1

        cur.execute('SELECT entity_id FROM places_fts WHERE places_fts MATCH \'"10-A"\'')
        assert len(cur.fetchall()) == 1

        conn.close()
        print("Database schema, R*Tree and FTS5 tests passed.")

def test_manifest_generation():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        db_file = out_dir / "kyiv_region.db"
        db_file.write_bytes(b"dummy database content for testing manifest")

        # Compress to .db.gz
        gz_file = out_dir / "kyiv_region.db.gz"
        with open(db_file, "rb") as f_in, gzip.open(gz_file, "wb") as f_out:
            f_out.write(f_in.read())

        manifest_path = generate_manifest(out_dir, Path("regions.json"))
        assert manifest_path.exists()

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        assert "updated_at" in manifest
        assert "regions" in manifest
        assert len(manifest["regions"]) == 1

        region_item = manifest["regions"][0]
        assert region_item["id"] == "kyiv"
        assert region_item["name_uk"] == "Київська область"
        assert region_item["name_en"] == "Kyiv Oblast"
        assert region_item["filename"] == "kyiv_region.db.gz"
        assert region_item["size_bytes"] == gz_file.stat().st_size
        assert region_item["sha256"] == compute_sha256(gz_file)
        print("Manifest generation test passed.")

if __name__ == "__main__":
    test_transliteration()
    test_district_matcher()
    test_street_normalizer()
    test_database_build_and_queries()
    test_manifest_generation()
    print("\nALL V2.0 TESTS PASSED SUCCESSFULLY!")
