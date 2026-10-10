import sqlite3
import logging
from typing import List, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

def create_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            osm_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS streets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city_id INTEGER,
            name TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            osm_id INTEGER,
            FOREIGN KEY(city_id) REFERENCES cities(id)
        );

        CREATE TABLE IF NOT EXISTS houses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            street_id INTEGER,
            number TEXT NOT NULL,
            lat REAL NOT NULL,
            lon REAL NOT NULL,
            osm_id INTEGER,
            FOREIGN KEY(street_id) REFERENCES streets(id)
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS places_fts USING fts5(
            name, 
            type,        
            entity_id
        );
        
        CREATE INDEX IF NOT EXISTS idx_streets_city_id ON streets(city_id);
        CREATE INDEX IF NOT EXISTS idx_houses_street_id ON houses(street_id);
    """)

def insert_cities(conn: sqlite3.Connection, cities: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    for city in cities:
        cursor.execute(
            "INSERT INTO cities (id, name, lat, lon, osm_id) VALUES (?, ?, ?, ?, ?)",
            (city['db_id'], city['name'], city['lat'], city['lon'], city['osm_id'])
        )
        cursor.execute(
            "INSERT INTO places_fts (name, type, entity_id) VALUES (?, ?, ?)",
            (city['name'], 'city', city['db_id'])
        )

def insert_streets(conn: sqlite3.Connection, streets: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    for street in streets:
        cursor.execute(
            "INSERT INTO streets (id, city_id, name, lat, lon, osm_id) VALUES (?, ?, ?, ?, ?, ?)",
            (street['db_id'], street['city_id'], street['name'], street['lat'], street['lon'], street['osm_id'])
        )
        cursor.execute(
            "INSERT INTO places_fts (name, type, entity_id) VALUES (?, ?, ?)",
            (street['name'], 'street', street['db_id'])
        )

def insert_houses(conn: sqlite3.Connection, houses: List[Dict[str, Any]]) -> None:
    cursor = conn.cursor()
    for house in houses:
        cursor.execute(
            "INSERT INTO houses (street_id, number, lat, lon, osm_id) VALUES (?, ?, ?, ?, ?)",
            (house['street_id'], house['number'], house['lat'], house['lon'], house['osm_id'])
        )
        db_id = cursor.lastrowid
        cursor.execute(
            "INSERT INTO places_fts (name, type, entity_id) VALUES (?, ?, ?)",
            (house['number'], 'house', db_id)
        )

def build_database(db_path: Path, cities: List[Dict], streets: List[Dict], houses: List[Dict]):
    logger.info(f"Building SQLite database at {db_path}...")
    if db_path.exists():
        db_path.unlink()
        
    conn = sqlite3.connect(db_path)
    # Optimizations for fast batch inserts
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = MEMORY")
    
    create_schema(conn)
    
    conn.execute("BEGIN TRANSACTION")
    insert_cities(conn, cities)
    insert_streets(conn, streets)
    insert_houses(conn, houses)
    conn.execute("COMMIT")
    
    logger.info("Optimizing database (VACUUM)...")
    conn.execute("VACUUM")
    conn.close()
    logger.info("Database built successfully.")
