# Offline Geocoding DB Generator (v2.0)

An automated pipeline that converts OpenStreetMap (OSM) data into highly optimized SQLite databases with FTS5 and R*Tree for offline forward and reverse geocoding in mobile applications.

## Overview
This project fetches raw OSM data (e.g., from Geofabrik), clips it by region, extracts addresses (cities, streets, houses), and compiles them into a compact SQLite database using Python and `pyosmium`. 

Key features in v2.0:
- **Full Bilingual Localization (UA / EN):** Official KMU №55 (2010) transliteration and OSM English names for cities, districts, regions, streets, and houses.
- **Decommunization & Old Names Support (`old_name`):** Indexing former street names (e.g. *Московська* -> *Князів Острозьких*).
- **Reverse Geocoding (SQLite R*Tree):** Sub-millisecond GPS-to-address lookups using `houses_rtree`.
- **Postal Codes (`postcode`):** Included for cities and houses.
- **Compression & Release Manifest:** Automated `gzip -9` compression (`.db.gz`) and generation of `manifest.json` with SHA-256 hashes and file sizes for client auto-updates.

## Database Schema (v2.0)
```sql
CREATE TABLE street_types (
    id INTEGER PRIMARY KEY,
    name_uk TEXT NOT NULL,
    short_uk TEXT NOT NULL,
    name_en TEXT NOT NULL,
    short_en TEXT NOT NULL
);

CREATE TABLE cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_en TEXT,
    city_type TEXT,
    city_type_en TEXT,
    district TEXT,
    district_en TEXT,
    region TEXT,
    region_en TEXT,
    postcode TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    osm_id INTEGER
);

CREATE TABLE streets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER,
    name TEXT NOT NULL,
    name_en TEXT,
    old_name TEXT,
    type_id INTEGER DEFAULT 1,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    osm_id INTEGER,
    FOREIGN KEY(city_id) REFERENCES cities(id),
    FOREIGN KEY(type_id) REFERENCES street_types(id)
);

CREATE TABLE houses (
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

-- R-Tree Spatial Index for GPS -> House
CREATE VIRTUAL TABLE houses_rtree USING rtree(
    id,
    min_lat, max_lat,
    min_lon, max_lon
);

-- Full-text search (FTS5) supporting UA/EN and old_name
CREATE VIRTUAL TABLE places_fts USING fts5(
    name,
    name_en,
    old_name,
    type,        -- 'city', 'street', 'house'
    entity_id
);

-- Indexes
CREATE INDEX idx_streets_city_id ON streets(city_id);
CREATE INDEX idx_streets_type_id ON streets(type_id);
CREATE INDEX idx_houses_street_id ON houses(street_id);
```

## Setup & Local Usage

### Requirements
- Python 3.10+
- `osmium-tool` (For region clipping)
  - Ubuntu/Debian: `sudo apt-get install osmium-tool`
  - macOS: `brew install osmium-tool`

### Installation
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Running the Pipeline
1. **Download Raw Data:**
   ```bash
   python download.py
   ```
   *Fetches `ukraine-latest.osm.pbf` (caches for 24 hours).*

2. **Run Pipeline (Clip -> Parse -> Compile DB):**
   ```bash
   python pipeline.py --input data/ukraine-latest.osm.pbf --region kyiv
   ```
   *This outputs `output/kyiv_region.db`*

3. **Compress & Generate Manifest:**
   ```bash
   gzip -9 output/*.db
   python generate_manifest.py --output-dir output
   ```

## Mobile App Integration

### Reverse Geocoding Query (GPS -> Nearest House)
```sql
SELECT h.id, h.number, h.number_en, s.name as street_uk, s.name_en as street_en, c.name as city_uk, c.name_en as city_en
FROM houses_rtree r
JOIN houses h ON r.id = h.id
JOIN streets s ON h.street_id = s.id
JOIN cities c ON s.city_id = c.id
WHERE r.min_lat <= :lat + 0.001 AND r.max_lat >= :lat - 0.001
  AND r.min_lon <= :lon + 0.001 AND r.max_lon >= :lon - 0.001
ORDER BY ((h.lat - :lat) * (h.lat - :lat) + (h.lon - :lon) * (h.lon - :lon)) ASC
LIMIT 1;
```

### Forward Search Query (FTS5)
```sql
SELECT fts.type, fts.name, fts.name_en, fts.old_name, fts.entity_id
FROM places_fts fts
WHERE places_fts MATCH 'Ostrozkykh'
LIMIT 20;
```

## Automation
The `.github/workflows/build-dbs.yml` workflow automatically builds all regional databases every Sunday, compresses them (`.db.gz`), computes `manifest.json`, and attaches them to GitHub Releases.
