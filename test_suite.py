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

from transliterator import transliterate_uk, transliterate_house_number, transliterate_hromada
from parser import DistrictMatcher, StreetNormalizer, CityParser, AddressParser
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

    # Territorial communities (hromadas)
    assert transliterate_hromada("Гатненська сільська громада") == "Hatne Hromada"
    assert transliterate_hromada("Бишівська сільська громада") == "Byshiv Hromada"
    assert transliterate_hromada("Макарівська селищна громада") == "Makariv Hromada"
    assert transliterate_hromada("Київ") == "Kyiv Hromada"
    print("Transliteration tests passed.")

def test_district_matcher():
    # Test Rayony GeoJSON
    with open("boundaries/rayony.geojson", "r", encoding="utf-8") as f:
        data = json.load(f)
    assert len(data.get("features", [])) == 136
    for feat in data["features"]:
        props = feat["properties"]
        assert "rayon" in props and len(props["rayon"]) > 0
        assert "rayon_en" in props and len(props["rayon_en"]) > 0
        assert props["rayon_en"].endswith("Raion")

    # Test Hromady GeoJSON
    with open("boundaries/hromady.geojson", "r", encoding="utf-8") as f:
        h_data = json.load(f)
    assert len(h_data.get("features", [])) == 1472

    matcher = DistrictMatcher(
        geojson_path=Path("boundaries/rayony.geojson"),
        hromady_path=Path("boundaries/hromady.geojson")
    )
    if matcher.enabled and not isinstance(sys.modules.get("shapely"), MagicMock):
        # 1. Yurivka near Gatne (former Kyiv-Svyatoshyn raion -> Fastiv raion, Gatnenska hromada)
        c_uk, c_en, d_uk, d_en = matcher.find_boundaries(50.354, 30.366)
        assert c_uk == "Гатненська сільська громада"
        assert c_en == "Hatne Hromada"
        assert d_uk == "Фастівський район"
        assert d_en == "Fastivskyi Raion"

        # 2. Yurivka near Byshiv (former Makariv raion -> Fastiv raion, Byshivska hromada)
        c_uk2, c_en2, d_uk2, d_en2 = matcher.find_boundaries(50.315, 29.808)
        assert c_uk2 == "Бишівська сільська громада"
        assert c_en2 == "Byshiv Hromada"
        assert d_uk2 == "Фастівський район"
        assert d_en2 == "Fastivskyi Raion"

        # 3. Check Kyiv municipality polygon detection
        assert matcher.is_in_kyiv(50.447, 30.522) is True    # Khreshchatyk
        assert matcher.is_in_kyiv(50.50, 30.50) is True     # Obolon
        assert matcher.is_in_kyiv(50.51, 30.79) is False    # Brovary (outside Kyiv)
    print("DistrictMatcher, hromady and rayony validation tests passed.")

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

    # Test old_name cleaning & localization
    # 1. "Kreschatic" for "Хрещатик" must be ignored (returns None for both old_name and old_name_en)
    uk, en = StreetNormalizer.clean_old_names(
        raw_name="Хрещатик",
        raw_name_en="Khreshchatyk",
        old_name="Kreschatic"
    )
    assert uk is None
    assert en is None

    # 2. Real Soviet/historical decommunized name in Ukrainian
    uk, en = StreetNormalizer.clean_old_names(
        raw_name="Князів Острозьких",
        raw_name_en="Kniaziv Ostrozkykh",
        old_name="вулиця Московська"
    )
    assert uk == "Московська"
    assert en == "Moskovska"

    # 3. Ukrainian old name with explicit English old_name:en
    uk, en = StreetNormalizer.clean_old_names(
        raw_name="Соборна",
        raw_name_en="Soborna",
        old_name="Леніна",
        old_name_en="Lenin St."
    )
    assert uk == "Леніна"
    assert en == "Lenin"

    # 4. "Карла Маркса"
    uk, en = StreetNormalizer.clean_old_names(
        raw_name="Миру",
        raw_name_en="Myru",
        old_name="Карла Маркса"
    )
    assert uk == "Карла Маркса"
    assert en == "Karla Marksa"

    print("StreetNormalizer & old_name cleaning tests passed.")

def test_kyiv_street_binding():
    """Verify that streets in Kyiv bind to Kyiv (place=city) instead of suburbs like 'Центр'."""
    cities = [
        {
            "db_id": 1,
            "osm_id": 101,
            "name": "Київ",
            "name_en": "Kyiv",
            "city_type": "місто",
            "city_type_en": "city",
            "place": "city",
            "community": "Київ",
            "community_en": "Kyiv",
            "district": None,
            "district_en": None,
            "region": "Київ",
            "region_en": "Kyiv",
            "lat": 50.4501,
            "lon": 30.5234
        },
        {
            "db_id": 2,
            "osm_id": 102,
            "name": "Центр",
            "name_en": "Centre",
            "city_type": "передмістя",
            "city_type_en": "suburb",
            "place": "suburb",
            "community": "Київ",
            "community_en": "Kyiv",
            "district": None,
            "district_en": None,
            "region": "Київ",
            "region_en": "Kyiv",
            "lat": 50.4475,   # Spatially closer to Khreshchatyk than Kyiv center node
            "lon": 30.5220
        }
    ]

    matcher = DistrictMatcher(
        geojson_path=Path("boundaries/rayony.geojson"),
        hromady_path=Path("boundaries/hromady.geojson")
    )
    parser = AddressParser(cities, boundary_matcher=matcher)

    # Process Khreshchatyk (lat: 50.4474, lon: 30.5222)
    street = parser._process_street(
        osm_id=999,
        raw_name="вулиця Хрещатик",
        raw_name_en="Khreshchatyk Street",
        old_name="Kreschatic",
        lat=50.4474,
        lon=30.5222
    )

    assert street is not None
    # Must link to Kyiv (id 1), NOT "Центр" (id 2)
    assert street["city_id"] == 1
    assert street["name"] == "Хрещатик"
    assert street["name_en"] == "Khreshchatyk"
    # "Kreschatic" was discarded
    assert street["old_name"] is None
    assert street["old_name_en"] is None
    print("Kyiv street city binding test passed.")

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
                "community": "Київ",
                "community_en": "Kyiv",
                "district": None,
                "district_en": None,
                "region": "Київ",
                "region_en": "Kyiv",
                "postcode": "01001",
                "lat": 50.4501,
                "lon": 30.5234
            },
            {
                "db_id": 2,
                "osm_id": 101,
                "name": "Юрівка",
                "name_en": "Yurivka",
                "city_type": "село",
                "city_type_en": "village",
                "community": "Гатненська сільська громада",
                "community_en": "Hatne Hromada",
                "district": "Фастівський район",
                "district_en": "Fastivskyi Raion",
                "region": "Київська область",
                "region_en": "Kyiv Oblast",
                "postcode": "08170",
                "lat": 50.3540,
                "lon": 30.3660
            },
            {
                "db_id": 3,
                "osm_id": 102,
                "name": "Юрівка",
                "name_en": "Yurivka",
                "city_type": "село",
                "city_type_en": "village",
                "community": "Бишівська сільська громада",
                "community_en": "Byshiv Hromada",
                "district": "Фастівський район",
                "district_en": "Fastivskyi Raion",
                "region": "Київська область",
                "region_en": "Kyiv Oblast",
                "postcode": "08072",
                "lat": 50.3150,
                "lon": 29.8080
            }
        ]

        streets = [
            {
                "db_id": 1,
                "city_id": 1,
                "name": "Князів Острозьких",
                "name_en": "Kniaziv Ostrozkykh",
                "old_name": "Московська",
                "old_name_en": "Moskovska",
                "type_id": 1,
                "lat": 50.4400,
                "lon": 30.5400,
                "osm_id": 200
            },
            {
                "db_id": 2,
                "city_id": 1,
                "name": "Хрещатик",
                "name_en": "Khreshchatyk",
                "old_name": None,
                "old_name_en": None,
                "type_id": 1,
                "lat": 50.4474,
                "lon": 30.5222,
                "osm_id": 201
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
        assert "community" in city_cols
        assert "community_en" in city_cols
        assert "district" in city_cols
        assert "district_en" in city_cols
        assert "region_en" in city_cols
        assert "postcode" in city_cols

        cur.execute("PRAGMA table_info(streets)")
        street_cols = [row[1] for row in cur.fetchall()]
        assert "name_en" in street_cols
        assert "old_name" in street_cols
        assert "old_name_en" in street_cols

        cur.execute("PRAGMA table_info(houses)")
        house_cols = [row[1] for row in cur.fetchall()]
        assert "number_en" in house_cols
        assert "postcode" in house_cols

        # Test selecting the two different Yurivkas in Fastiv Raion by community
        cur.execute("SELECT id, community, community_en FROM cities WHERE name='Юрівка' AND district='Фастівський район'")
        yurivkas = cur.fetchall()
        assert len(yurivkas) == 2
        communities = {y[1] for y in yurivkas}
        assert "Гатненська сільська громада" in communities
        assert "Бишівська сільська громада" in communities

        # Test Reverse Geocoding with R*Tree
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

        # Test FTS5 search for DECOMMUNIZED old street name in Ukrainian and English
        cur.execute("SELECT entity_id, type FROM places_fts WHERE places_fts MATCH 'Московська'")
        assert len(cur.fetchall()) == 1

        cur.execute("SELECT entity_id, type FROM places_fts WHERE places_fts MATCH 'Moskovska'")
        assert len(cur.fetchall()) == 1

        # Test FTS5 search for Khreshchatyk - ensure 'Kreschatic' doesn't match
        cur.execute("SELECT entity_id, type FROM places_fts WHERE places_fts MATCH 'Kreschatic'")
        assert len(cur.fetchall()) == 0

        # Test FTS5 search for house number in Ukrainian and English
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
    test_kyiv_street_binding()
    test_database_build_and_queries()
    test_manifest_generation()
    print("\nALL V2.1 TESTS PASSED SUCCESSFULLY!")

