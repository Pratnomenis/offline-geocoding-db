# Offline Geocoding DB Generator

An automated pipeline that converts OpenStreetMap (OSM) data into highly optimized SQLite databases with FTS5 for offline forward geocoding in mobile applications.

## Overview
This project fetches raw OSM data (e.g., from Geofabrik), clips it by region, extracts addresses (cities, streets, houses), and compiles them into a compact SQLite database using Python and `pyosmium`. 
The CI/CD pipeline is fully automated via GitHub Actions, running weekly to generate and release up-to-date databases.

## Database Schema
The generated `.db` uses a simple relational model:
- `cities`: Cities, towns, villages, etc.
- `streets`: Streets mapped to their closest city.
- `houses`: House numbers mapped to their corresponding streets.
- `places_fts`: FTS5 Virtual Table for blazing-fast global text searches.

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

## Mobile App Integration

Mobile apps (e.g., React Native with `react-native-quick-sqlite`) can directly download the `.db` artifacts attached to GitHub Releases. 

Example query to search for an address:
```sql
SELECT c.name as city, s.name as street, h.number as house
FROM places_fts fts
JOIN houses h ON fts.entity_id = h.id AND fts.type = 'house'
JOIN streets s ON h.street_id = s.id
JOIN cities c ON s.city_id = c.id
WHERE fts.name MATCH '10' AND s.name = 'Main Street';
```

## Automation
The `.github/workflows/build-dbs.yml` automatically builds these databases every Sunday and publishes them to GitHub Releases.
