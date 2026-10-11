import sqlite3
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

STREET_TYPES = [
    (1, "вулиця", "вул.", "Street", "St."),
    (2, "проспект", "просп.", "Avenue", "Ave."),
    (3, "провулок", "пров.", "Lane", "Ln."),
    (4, "бульвар", "бул.", "Boulevard", "Blvd."),
    (5, "площа", "пл.", "Square", "Sq."),
    (6, "набережна", "наб.", "Embankment", "Emb."),
    (7, "шосе", "шосе", "Highway", "Hwy."),
    (8, "узвіз", "узвіз", "Descent", "Desc."),
    (9, "проїзд", "пр-д", "Drive", "Dr."),
    (10, "тупик", "туп.", "Cul-de-sac", "Cds."),
    (11, "алея", "алея", "Alley", "Aly."),
    (12, "лінія", "лінія", "Line", "Ln."),
    (13, "дорога", "дор.", "Road", "Rd."),
    (14, "тракт", "тракт", "Tract", "Tr."),
    (15, "квартал", "кв-л", "Quarter", "Qtr."),
    (16, "масив", "масив", "Microraion", "Mrn.")
]

def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS street_types (
            id INTEGER PRIMARY KEY,
            name_uk TEXT NOT NULL,
            short_uk TEXT NOT NULL,
            name_en TEXT NOT NULL,
            short_en TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS cities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            name_en TEXT,
            city_type TEXT,
            city_type_en TEXT,
            community TEXT,
            community_en TEXT,
            district TEXT,
            district_en TEXT,
            region TEXT,
            region_en TEXT,
            postcode TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            osm_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS streets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_id INTEGER,
            name TEXT NOT NULL,
            name_en TEXT,
            old_name TEXT,
            old_name_en TEXT,
            type_id INTEGER DEFAULT 1,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            osm_id INTEGER,
            FOREIGN KEY(city_id) REFERENCES cities(id),
            FOREIGN KEY(type_id) REFERENCES street_types(id)
        );

        CREATE TABLE IF NOT EXISTS houses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            street_id INTEGER,
            number TEXT NOT NULL,
            number_en TEXT,
            postcode TEXT,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            osm_id INTEGER,
            FOREIGN KEY(street_id) REFERENCES streets(id)
        );

        -- R-Tree spatial index for reverse geocoding (GPS -> House)
        CREATE VIRTUAL TABLE IF NOT EXISTS houses_rtree USING rtree(
            id,
            min_lat, max_lat,
            min_lon, max_lon
        );

        -- Full-text search (FTS5) supporting bilingual names and old names
        CREATE VIRTUAL TABLE IF NOT EXISTS places_fts USING fts5(
            name,
            name_en,
            old_name,
            old_name_en,
            type,        -- 'city', 'street', 'house'
            entity_id
        );

        CREATE INDEX IF NOT EXISTS idx_cities_name ON cities(name);
        CREATE INDEX IF NOT EXISTS idx_cities_district ON cities(district);
        CREATE INDEX IF NOT EXISTS idx_cities_community ON cities(community);
        CREATE INDEX IF NOT EXISTS idx_streets_city_id ON streets(city_id);
        CREATE INDEX IF NOT EXISTS idx_streets_name ON streets(name);
        CREATE INDEX IF NOT EXISTS idx_streets_type_id ON streets(type_id);
        CREATE INDEX IF NOT EXISTS idx_houses_street_id ON houses(street_id);
    """)

def seed_street_types(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.executemany(
        "INSERT OR IGNORE INTO street_types (id, name_uk, short_uk, name_en, short_en) VALUES (?, ?, ?, ?, ?)",
        STREET_TYPES
    )

def insert_cities(conn: sqlite3.Connection, cities: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    for city in cities:
        cursor.execute(
            """INSERT INTO cities (
                id, name, name_en, city_type, city_type_en,
                community, community_en,
                district, district_en, region, region_en, postcode,
                lat, lon, osm_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                city['db_id'],
                city['name'],
                city.get('name_en'),
                city.get('city_type'),
                city.get('city_type_en'),
                city.get('community'),
                city.get('community_en'),
                city.get('district'),
                city.get('district_en'),
                city.get('region'),
                city.get('region_en'),
                city.get('postcode'),
                city['lat'],
                city['lon'],
                city['osm_id']
            )
        )
        cursor.execute(
            "INSERT INTO places_fts (name, name_en, old_name, old_name_en, type, entity_id) VALUES (?, ?, ?, ?, ?, ?)",
            (city['name'], city.get('name_en'), None, None, 'city', city['db_id'])
        )

def insert_streets(conn: sqlite3.Connection, streets: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    for street in streets:
        cursor.execute(
            """INSERT INTO streets (
                id, city_id, name, name_en, old_name, old_name_en, type_id, lat, lon, osm_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                street['db_id'],
                street['city_id'],
                street['name'],
                street.get('name_en'),
                street.get('old_name'),
                street.get('old_name_en'),
                street.get('type_id', 1),
                street['lat'],
                street['lon'],
                street['osm_id']
            )
        )
        cursor.execute(
            "INSERT INTO places_fts (name, name_en, old_name, old_name_en, type, entity_id) VALUES (?, ?, ?, ?, ?, ?)",
            (street['name'], street.get('name_en'), street.get('old_name'), street.get('old_name_en'), 'street', street['db_id'])
        )

def insert_houses(conn: sqlite3.Connection, houses: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    for house in houses:
        cursor.execute(
            """INSERT INTO houses (
                street_id, number, number_en, postcode, lat, lon, osm_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                house['street_id'],
                house['number'],
                house.get('number_en'),
                house.get('postcode'),
                house['lat'],
                house['lon'],
                house['osm_id']
            )
        )
        house_id = cursor.lastrowid
        if house_id is not None:
            lat = house['lat']
            lon = house['lon']
            cursor.execute(
                "INSERT INTO houses_rtree (id, min_lat, max_lat, min_lon, max_lon) VALUES (?, ?, ?, ?, ?)",
                (house_id, lat, lat, lon, lon)
            )
            cursor.execute(
                "INSERT INTO places_fts (name, name_en, old_name, old_name_en, type, entity_id) VALUES (?, ?, ?, ?, ?, ?)",
                (house['number'], house.get('number_en'), None, None, 'house', house_id)
            )

def build_database(
    db_path: Path,
    cities: List[Dict[str, Any]],
    streets: List[Dict[str, Any]],
    houses: List[Dict[str, Any]]
) -> None:
    logger.info(f"Building SQLite database at {db_path}...")
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    # Optimizations for fast batch inserts
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")

    create_schema(conn)

    conn.execute("BEGIN TRANSACTION")
    seed_street_types(conn)
    insert_cities(conn, cities)
    insert_streets(conn, streets)
    insert_houses(conn, houses)
    conn.execute("COMMIT")

    logger.info("Optimizing database (VACUUM)...")
    conn.execute("VACUUM")
    conn.close()
    logger.info("Database built successfully.")
