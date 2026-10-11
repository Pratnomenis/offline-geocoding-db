import osmium
import logging
import math
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

import json
from pathlib import Path
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

class DistrictMatcher:
    def __init__(self, geojson_path: Path):
        self.enabled = False
        self.geoms = []
        self.names = []
        self.tree = None
        
        if geojson_path.exists():
            try:
                with open(geojson_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self.geoms = [shape(f['geometry']) for f in data.get('features', [])]
                self.names = [f['properties'].get('rayon', '') for f in data.get('features', [])]
                if self.geoms:
                    self.tree = STRtree(self.geoms)
                    self.enabled = True
                    logger.info(f"Loaded {len(self.geoms)} district boundaries from {geojson_path}")
            except Exception as e:
                logger.warning(f"Could not load district boundaries from {geojson_path}: {e}")
        else:
            logger.warning(f"District boundaries file not found at {geojson_path}")

    def find_district(self, lat: float, lon: float) -> Optional[str]:
        if not self.enabled or self.tree is None:
            return None
        
        pt = Point(lon, lat)
        idx = self.tree.query(pt, predicate='intersects')
        if len(idx) > 0:
            return self.names[idx[0]]
        
        # Check nearest within ~5km threshold if on boundary
        nearest_idx = self.tree.nearest(pt)
        if self.geoms[nearest_idx].distance(pt) < 0.05:
            return self.names[nearest_idx]
            
        return None

class CityParser(osmium.SimpleHandler):
    def __init__(self, region_name: Optional[str] = None, district_matcher: Optional[DistrictMatcher] = None):
        super().__init__()
        self.cities: List[Dict[str, Any]] = []
        self._next_db_id = 1
        self.region_name = region_name
        self.district_matcher = district_matcher

    def node(self, n):
        if n.tags.get('place') in ('city', 'town', 'village', 'hamlet', 'suburb'):
            if 'name' in n.tags:
                lat = n.location.lat
                lon = n.location.lon
                
                district = None
                if self.district_matcher:
                    district = self.district_matcher.find_district(lat, lon)
                
                if not district:
                    district = n.tags.get('addr:district') or n.tags.get('is_in:district')
                
                region = self.region_name or n.tags.get('addr:province') or n.tags.get('is_in:state')
                
                self.cities.append({
                    'db_id': self._next_db_id,
                    'osm_id': n.id,
                    'name': n.tags['name'],
                    'lat': lat,
                    'lon': lon,
                    'district': district,
                    'region': region,
                })
                self._next_db_id += 1

class AddressParser(osmium.SimpleHandler):
    def __init__(self, cities: List[Dict[str, Any]]):
        super().__init__()
        self.cities = cities
        self.streets: Dict[str, Dict[str, Any]] = {}
        self.houses: List[Dict[str, Any]] = []
        self._next_street_id = 1
        
    def _find_nearest_city(self, lat: float, lon: float) -> Optional[int]:
        min_dist = float('inf')
        nearest_id = None
        # In a highly optimized version, use an R-Tree or Geopandas for spatial join.
        # Linear scan is sufficient for smaller regions like Kyiv.
        for city in self.cities:
            # Simple squared Euclidean distance for local approximation
            dist = (city['lat'] - lat)**2 + (city['lon'] - lon)**2
            if dist < min_dist:
                min_dist = dist
                nearest_id = city['db_id']
        return nearest_id if min_dist < 0.2 else None  # approx ~20km tolerance

    def _process_street(self, osm_id, name, lat, lon):
        city_id = self._find_nearest_city(lat, lon)
        if city_id is None:
            return None
        
        # Deduplicate streets by name and city_id
        key = f"{city_id}_{name}"
        if key not in self.streets:
            self.streets[key] = {
                'db_id': self._next_street_id,
                'name': name,
                'city_id': city_id,
                'lat': lat,
                'lon': lon,
                'osm_id': osm_id
            }
            self._next_street_id += 1
        return self.streets[key]

    def node(self, n):
        self._extract_house(n.id, n.tags, n.location.lat, n.location.lon)

    def way(self, w):
        try:
            if len(w.nodes) == 0:
                return
            
            lat, lon = w.nodes[0].lat, w.nodes[0].lon
            
            if 'highway' in w.tags and 'name' in w.tags:
                self._process_street(w.id, w.tags['name'], lat, lon)
            
            self._extract_house(w.id, w.tags, lat, lon)
        except osmium.InvalidLocationError:
            pass
            
    def _extract_house(self, osm_id, tags, lat, lon):
        street_name = tags.get('addr:street')
        housenumber = tags.get('addr:housenumber')
        
        if street_name and housenumber:
            city_id = self._find_nearest_city(lat, lon)
            if city_id:
                self.houses.append({
                    'osm_id': osm_id,
                    'number': housenumber,
                    'street_name': street_name,
                    'city_id': city_id,
                    'lat': lat,
                    'lon': lon
                })
