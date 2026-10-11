import logging
import json
import re
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import osmium
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

from transliterator import transliterate_uk, transliterate_house_number

logger = logging.getLogger(__name__)

CITY_TYPE_MAP: Dict[str, Tuple[str, str]] = {
    'city': ('місто', 'city'),
    'town': ('місто', 'city'),
    'village': ('село', 'village'),
    'hamlet': ('селище', 'settlement'),
    'isolated_dwelling': ('селище', 'settlement'),
    'suburb': ('передмістя', 'suburb'),
}

class DistrictMatcher:
    def __init__(self, geojson_path: Path):
        self.enabled: bool = False
        self.geoms: List[Any] = []
        self.names_uk: List[str] = []
        self.names_en: List[str] = []
        self.tree: Optional[STRtree] = None

        if geojson_path.exists():
            try:
                with open(geojson_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                features = data.get('features', [])
                self.geoms = [shape(f['geometry']) for f in features]
                self.names_uk = [f['properties'].get('rayon', '') for f in features]
                self.names_en = [
                    f['properties'].get('rayon_en') or (
                        transliterate_uk(f['properties'].get('rayon', '').replace(' район', '').replace(' Район', '')) + ' Raion'
                        if f['properties'].get('rayon') else ''
                    )
                    for f in features
                ]
                if self.geoms:
                    self.tree = STRtree(self.geoms)
                    self.enabled = True
                    logger.info(f"Loaded {len(self.geoms)} district boundaries from {geojson_path}")
            except Exception as e:
                logger.warning(f"Could not load district boundaries from {geojson_path}: {e}")
        else:
            logger.warning(f"District boundaries file not found at {geojson_path}")

    def find_district(self, lat: float, lon: float) -> Tuple[Optional[str], Optional[str]]:
        if not self.enabled or self.tree is None:
            return (None, None)

        pt = Point(lon, lat)
        idx = self.tree.query(pt, predicate='intersects')
        if len(idx) > 0:
            i = idx[0]
            return (self.names_uk[i], self.names_en[i])

        # Check nearest within ~5km threshold if on boundary
        nearest_idx = self.tree.nearest(pt)
        if self.geoms[nearest_idx].distance(pt) < 0.05:
            return (self.names_uk[nearest_idx], self.names_en[nearest_idx])

        return (None, None)

class CityParser(osmium.SimpleHandler):
    def __init__(
        self,
        region_name_uk: Optional[str] = None,
        region_name_en: Optional[str] = None,
        district_matcher: Optional[DistrictMatcher] = None
    ):
        super().__init__()
        self.cities: List[Dict[str, Any]] = []
        self._next_db_id: int = 1
        self.region_name_uk: Optional[str] = region_name_uk
        self.region_name_en: Optional[str] = region_name_en
        self.district_matcher: Optional[DistrictMatcher] = district_matcher

    def node(self, n: Any) -> None:
        place = n.tags.get('place')
        if place in ('city', 'town', 'village', 'hamlet', 'isolated_dwelling', 'suburb'):
            if 'name' in n.tags:
                lat = n.location.lat
                lon = n.location.lon

                name_uk = n.tags['name']
                name_en = n.tags.get('name:en') or transliterate_uk(name_uk)

                city_type_uk, city_type_en = CITY_TYPE_MAP.get(place, ('місто', 'city'))

                district_uk: Optional[str] = None
                district_en: Optional[str] = None
                if self.district_matcher:
                    district_uk, district_en = self.district_matcher.find_district(lat, lon)

                if not district_uk:
                    district_uk = n.tags.get('addr:district') or n.tags.get('is_in:district')
                    if district_uk:
                        clean_base = district_uk.replace(' район', '').replace(' Район', '')
                        district_en = f"{transliterate_uk(clean_base)} Raion"

                region_uk = self.region_name_uk or n.tags.get('addr:province') or n.tags.get('is_in:state')
                region_en = self.region_name_en or (transliterate_uk(region_uk) if region_uk else None)

                postcode = n.tags.get('addr:postcode') or n.tags.get('postal_code')

                self.cities.append({
                    'db_id': self._next_db_id,
                    'osm_id': n.id,
                    'name': name_uk,
                    'name_en': name_en,
                    'city_type': city_type_uk,
                    'city_type_en': city_type_en,
                    'district': district_uk,
                    'district_en': district_en,
                    'region': region_uk,
                    'region_en': region_en,
                    'postcode': postcode,
                    'lat': lat,
                    'lon': lon,
                })
                self._next_db_id += 1

class StreetNormalizer:
    # Mapping of regex patterns to (type_id, type_name_uk)
    PATTERNS = [
        (re.compile(r'\b(вулиця|вул\.?)\b', re.IGNORECASE), 1),
        (re.compile(r'\b(проспект|просп\.?)\b', re.IGNORECASE), 2),
        (re.compile(r'\b(провулок|пров\.?)\b', re.IGNORECASE), 3),
        (re.compile(r'\b(бульвар|бул\.?)\b', re.IGNORECASE), 4),
        (re.compile(r'\b(площа|пл\.?)\b', re.IGNORECASE), 5),
        (re.compile(r'\b(набережна|наб\.?)\b', re.IGNORECASE), 6),
        (re.compile(r'\b(шосе)\b', re.IGNORECASE), 7),
        (re.compile(r'\b(узвіз)\b', re.IGNORECASE), 8),
        (re.compile(r'\b(проїзд|пр-д\.?)\b', re.IGNORECASE), 9),
        (re.compile(r'\b(тупик|туп\.?)\b', re.IGNORECASE), 10),
        (re.compile(r'\b(алея)\b', re.IGNORECASE), 11),
        (re.compile(r'\b(лінія)\b', re.IGNORECASE), 12),
        (re.compile(r'\b(дорога|дор\.?)\b', re.IGNORECASE), 13),
        (re.compile(r'\b(тракт)\b', re.IGNORECASE), 14),
        (re.compile(r'\b(квартал|кв-л\.?)\b', re.IGNORECASE), 15),
        (re.compile(r'\b(масив)\b', re.IGNORECASE), 16),
    ]

    ENGLISH_TYPE_PATTERNS = [
        re.compile(r'\b(street|st\.?)\b', re.IGNORECASE),
        re.compile(r'\b(avenue|ave\.?)\b', re.IGNORECASE),
        re.compile(r'\b(lane|ln\.?)\b', re.IGNORECASE),
        re.compile(r'\b(boulevard|blvd\.?)\b', re.IGNORECASE),
        re.compile(r'\b(square|sq\.?)\b', re.IGNORECASE),
        re.compile(r'\b(embankment|emb\.?)\b', re.IGNORECASE),
        re.compile(r'\b(highway|hwy\.?)\b', re.IGNORECASE),
        re.compile(r'\b(descent|desc\.?)\b', re.IGNORECASE),
        re.compile(r'\b(drive|dr\.?)\b', re.IGNORECASE),
        re.compile(r'\b(cul-de-sac|cds\.?)\b', re.IGNORECASE),
        re.compile(r'\b(alley|aly\.?)\b', re.IGNORECASE),
        re.compile(r'\b(line)\b', re.IGNORECASE),
        re.compile(r'\b(road|rd\.?)\b', re.IGNORECASE),
        re.compile(r'\b(tract|tr\.?)\b', re.IGNORECASE),
        re.compile(r'\b(quarter|qtr\.?)\b', re.IGNORECASE),
        re.compile(r'\b(microraion|mrn\.?)\b', re.IGNORECASE),
    ]

    @classmethod
    def normalize(cls, raw_name: Optional[str]) -> Tuple[str, int]:
        """Separates the street type from the Ukrainian street name.
        Returns: (clean_name, type_id)
        """
        if not raw_name:
            return ("", 1)

        detected_type_id = 1
        clean_name = raw_name

        for pattern, type_id in cls.PATTERNS:
            match = pattern.search(clean_name)
            if match:
                detected_type_id = type_id
                clean_name = pattern.sub('', clean_name)
                break

        clean_name = re.sub(r'["\'«»]', '', clean_name)
        clean_name = re.sub(r'\s+', ' ', clean_name).strip(' ,.-')

        if not clean_name:
            clean_name = raw_name

        return (clean_name, detected_type_id)

    @classmethod
    def normalize_en(cls, raw_en: Optional[str]) -> str:
        """Removes English street type words to get a clean English street name."""
        if not raw_en:
            return ""

        clean_en = raw_en
        for pat in cls.ENGLISH_TYPE_PATTERNS:
            clean_en = pat.sub('', clean_en)

        clean_en = re.sub(r'["\'«»]', '', clean_en)
        clean_en = re.sub(r'\s+', ' ', clean_en).strip(' ,.-')

        return clean_en if clean_en else raw_en.strip()

class AddressParser(osmium.SimpleHandler):
    def __init__(self, cities: List[Dict[str, Any]]):
        super().__init__()
        self.cities: List[Dict[str, Any]] = cities
        self.streets: Dict[str, Dict[str, Any]] = {}
        self.raw_to_street_key: Dict[str, str] = {}
        self.houses: List[Dict[str, Any]] = []
        self._next_street_id: int = 1

    def _find_nearest_city(self, lat: float, lon: float) -> Optional[int]:
        min_dist = float('inf')
        nearest_id: Optional[int] = None
        for city in self.cities:
            dist = (city['lat'] - lat) ** 2 + (city['lon'] - lon) ** 2
            if dist < min_dist:
                min_dist = dist
                nearest_id = city['db_id']
        return nearest_id if min_dist < 0.2 else None  # approx ~20km tolerance

    def _process_street(
        self,
        osm_id: int,
        raw_name: str,
        raw_name_en: Optional[str],
        old_name: Optional[str],
        lat: float,
        lon: float
    ) -> Optional[Dict[str, Any]]:
        city_id = self._find_nearest_city(lat, lon)
        if city_id is None:
            return None

        clean_name, type_id = StreetNormalizer.normalize(raw_name)
        clean_name_en = StreetNormalizer.normalize_en(raw_name_en) if raw_name_en else ""
        if not clean_name_en:
            clean_name_en = transliterate_uk(clean_name)

        clean_old_name: Optional[str] = None
        if old_name:
            clean_old_name, _ = StreetNormalizer.normalize(old_name)

        key = f"{city_id}_{clean_name}_{type_id}"
        raw_key = f"{city_id}_{raw_name}"

        if key not in self.streets:
            self.streets[key] = {
                'db_id': self._next_street_id,
                'name': clean_name,
                'name_en': clean_name_en,
                'old_name': clean_old_name,
                'type_id': type_id,
                'city_id': city_id,
                'lat': lat,
                'lon': lon,
                'osm_id': osm_id
            }
            self._next_street_id += 1
        else:
            if not self.streets[key].get('name_en') and clean_name_en:
                self.streets[key]['name_en'] = clean_name_en
            if not self.streets[key].get('old_name') and clean_old_name:
                self.streets[key]['old_name'] = clean_old_name

        self.raw_to_street_key[raw_key] = key
        self.raw_to_street_key[f"{city_id}_{clean_name}"] = key
        return self.streets[key]

    def node(self, n: Any) -> None:
        self._extract_house(n.id, n.tags, n.location.lat, n.location.lon)

    def way(self, w: Any) -> None:
        try:
            if len(w.nodes) == 0:
                return

            lat, lon = w.nodes[0].lat, w.nodes[0].lon

            if 'highway' in w.tags and 'name' in w.tags:
                raw_name = w.tags['name']
                raw_name_en = w.tags.get('name:en')
                old_name = w.tags.get('old_name') or w.tags.get('old_name:uk')
                self._process_street(w.id, raw_name, raw_name_en, old_name, lat, lon)

            self._extract_house(w.id, w.tags, lat, lon)
        except osmium.InvalidLocationError:
            pass

    def _extract_house(self, osm_id: int, tags: Any, lat: float, lon: float) -> None:
        street_name = tags.get('addr:street')
        housenumber = tags.get('addr:housenumber')

        if street_name and housenumber:
            city_id = self._find_nearest_city(lat, lon)
            if city_id:
                postcode = tags.get('addr:postcode') or tags.get('postal_code')
                number_en = transliterate_house_number(housenumber)
                self.houses.append({
                    'osm_id': osm_id,
                    'number': housenumber,
                    'number_en': number_en,
                    'postcode': postcode,
                    'raw_street_name': street_name,
                    'city_id': city_id,
                    'lat': lat,
                    'lon': lon
                })
