import osmium
import logging
import math
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class CityParser(osmium.SimpleHandler):
    def __init__(self, region_name: Optional[str] = None):
        super().__init__()
        self.cities: List[Dict[str, Any]] = []
        self._next_db_id = 1
        self.region_name = region_name

    def node(self, n):
        if n.tags.get('place') in ('city', 'town', 'village', 'hamlet', 'suburb'):
            if 'name' in n.tags:
                district = n.tags.get('addr:district') or n.tags.get('is_in:district')
                region = n.tags.get('addr:province') or n.tags.get('is_in:state') or self.region_name
                self.cities.append({
                    'db_id': self._next_db_id,
                    'osm_id': n.id,
                    'name': n.tags['name'],
                    'lat': n.location.lat,
                    'lon': n.location.lon,
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
