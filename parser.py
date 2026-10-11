import logging
import json
import re
import difflib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import osmium
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

from transliterator import transliterate_uk, transliterate_house_number, transliterate_hromada

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
    def __init__(
        self,
        geojson_path: Optional[Path] = None,
        hromady_path: Optional[Path] = None
    ):
        self.enabled: bool = False
        self.hromada_tree: Optional[STRtree] = None
        self.hromada_geoms: List[Any] = []
        self.hromada_props: List[Dict[str, Any]] = []

        self.rayon_tree: Optional[STRtree] = None
        self.rayon_geoms: List[Any] = []
        self.rayon_names_uk: List[str] = []
        self.rayon_names_en: List[str] = []
        self.rayon_uk_to_en: Dict[str, str] = {}

        self.kyiv_geom: Optional[Any] = None

        # 1. Load Rayons (districts) if file exists
        target_rayony = geojson_path or Path("boundaries/rayony.geojson")
        if target_rayony and target_rayony.exists():
            try:
                with open(target_rayony, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                features = data.get('features', [])
                self.rayon_geoms = [shape(f['geometry']) for f in features]
                self.rayon_names_uk = [f['properties'].get('rayon', '') for f in features]
                self.rayon_names_en = [
                    f['properties'].get('rayon_en') or (
                        transliterate_uk(f['properties'].get('rayon', '').replace(' район', '').replace(' Район', '')) + ' Raion'
                        if f['properties'].get('rayon') else ''
                    )
                    for f in features
                ]
                for uk, en in zip(self.rayon_names_uk, self.rayon_names_en):
                    if uk and en:
                        self.rayon_uk_to_en[uk] = en
                if self.rayon_geoms:
                    self.rayon_tree = STRtree(self.rayon_geoms)
                    self.enabled = True
                    logger.info(f"Loaded {len(self.rayon_geoms)} district boundaries from {target_rayony}")
            except Exception as e:
                logger.warning(f"Could not load district boundaries from {target_rayony}: {e}")

        # 2. Load Hromadas (territorial communities, admin_level=7)
        target_hromady = hromady_path or Path("boundaries/hromady.geojson")
        if target_hromady and target_hromady.exists():
            try:
                with open(target_hromady, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                features = data.get('features', [])
                self.hromada_geoms = [shape(f['geometry']) for f in features]
                self.hromada_props = [f['properties'] for f in features]

                for geom, props in zip(self.hromada_geoms, self.hromada_props):
                    # Check for Kyiv city boundary
                    if props.get('region') == 'Київ' or props.get('hromada') == 'Київ':
                        self.kyiv_geom = geom

                if self.hromada_geoms:
                    self.hromada_tree = STRtree(self.hromada_geoms)
                    self.enabled = True
                    logger.info(f"Loaded {len(self.hromada_geoms)} hromada boundaries from {target_hromady}")
            except Exception as e:
                logger.warning(f"Could not load hromada boundaries from {target_hromady}: {e}")

    def find_boundaries(
        self,
        lat: float,
        lon: float
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """Finds both community (admin_level=7) and district (admin_level=6) for a location.
        Returns: (community_uk, community_en, district_uk, district_en)
        """
        community_uk: Optional[str] = None
        community_en: Optional[str] = None
        district_uk: Optional[str] = None
        district_en: Optional[str] = None

        pt = Point(lon, lat)

        # First check hromadas STRtree
        if self.hromada_tree is not None and self.hromada_geoms:
            idx = self.hromada_tree.query(pt, predicate='intersects')
            target_idx = idx[0] if len(idx) > 0 else None

            # Fallback to nearest within ~3km if on polygon boundary
            if target_idx is None:
                nearest_idx = self.hromada_tree.nearest(pt)
                if self.hromada_geoms[nearest_idx].distance(pt) < 0.03:
                    target_idx = nearest_idx

            if target_idx is not None:
                props = self.hromada_props[target_idx]
                h_name = props.get('hromada')
                r_name = props.get('rayon')
                region_name = props.get('region')

                if region_name == 'Київ':
                    community_uk = 'Київ'
                    community_en = 'Kyiv'
                    district_uk = None
                    district_en = None
                else:
                    if h_name:
                        community_uk = h_name
                        community_en = props.get('hromada_en') or transliterate_hromada(h_name)

                    if r_name:
                        district_uk = r_name
                        district_en = self.rayon_uk_to_en.get(r_name)
                        if not district_en:
                            clean_base = r_name.replace(' район', '').replace(' Район', '')
                            district_en = f"{transliterate_uk(clean_base)} Raion"

                return (community_uk, community_en, district_uk, district_en)

        # Fallback to rayony STRtree if hromadas didn't match
        if self.rayon_tree is not None and self.rayon_geoms:
            idx = self.rayon_tree.query(pt, predicate='intersects')
            target_idx = idx[0] if len(idx) > 0 else None
            if target_idx is None:
                nearest_idx = self.rayon_tree.nearest(pt)
                if self.rayon_geoms[nearest_idx].distance(pt) < 0.05:
                    target_idx = nearest_idx

            if target_idx is not None:
                district_uk = self.rayon_names_uk[target_idx]
                district_en = self.rayon_names_en[target_idx]

        return (community_uk, community_en, district_uk, district_en)

    def find_district(self, lat: float, lon: float) -> Tuple[Optional[str], Optional[str]]:
        """Backward-compatible method returning (district_uk, district_en)."""
        _, _, d_uk, d_en = self.find_boundaries(lat, lon)
        return (d_uk, d_en)

    def find_community(self, lat: float, lon: float) -> Tuple[Optional[str], Optional[str]]:
        """Returns (community_uk, community_en)."""
        c_uk, c_en, _, _ = self.find_boundaries(lat, lon)
        return (c_uk, c_en)

    def is_in_kyiv(self, lat: float, lon: float) -> bool:
        """Returns True if the point is strictly inside the Kyiv city municipality polygon."""
        if self.kyiv_geom is None:
            return False
        pt = Point(lon, lat)
        return bool(self.kyiv_geom.contains(pt))

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

                community_uk: Optional[str] = None
                community_en: Optional[str] = None
                district_uk: Optional[str] = None
                district_en: Optional[str] = None

                if self.district_matcher:
                    community_uk, community_en, district_uk, district_en = self.district_matcher.find_boundaries(lat, lon)

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
                    'place': place,
                    'community': community_uk,
                    'community_en': community_en,
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

    @classmethod
    def clean_old_names(
        cls,
        raw_name: str,
        raw_name_en: str,
        old_name: Optional[str] = None,
        old_name_uk: Optional[str] = None,
        old_name_en: Optional[str] = None
    ) -> Tuple[Optional[str], Optional[str]]:
        """Cleans and localizes historical/decommunized street names.
        
        Rules:
        1. Separates Ukrainian old_name and English old_name:en.
        2. Discards Latin strings for Ukrainian old_name if they are just transliterations
           of the current name (e.g. 'Kreschatic' for 'Хрещатик' -> None).
        3. Only preserves real historical names (e.g. 'Карла Маркса', 'Московська', 'Леніна').
        Returns: (clean_old_name_uk, clean_old_name_en)
        """
        def is_transliteration(cand: str, target_uk: str, target_en: str) -> bool:
            if not cand:
                return False
            c = re.sub(r'[^a-zA-Z]', '', cand).lower()
            t_en = re.sub(r'[^a-zA-Z]', '', target_en).lower()
            t_uk = re.sub(r'[^a-zA-Z]', '', transliterate_uk(target_uk)).lower()
            if not c:
                return False
            if c == t_en or c == t_uk:
                return True
            for t in (t_en, t_uk):
                if t and difflib.SequenceMatcher(None, c, t).ratio() >= 0.55:
                    return True
            return False

        cand_uk = old_name_uk or old_name
        cand_en = old_name_en

        res_uk: Optional[str] = None
        res_en: Optional[str] = None

        if cand_uk:
            # Check if contains Cyrillic letters
            if re.search(r'[а-яА-ЯіїєґІЇЄҐ]', cand_uk):
                clean_uk, _ = cls.normalize(cand_uk)
                if clean_uk and clean_uk.lower() != raw_name.lower():
                    res_uk = clean_uk
            else:
                # Value has only Latin letters! Might be a candidate for English old name
                if not cand_en:
                    cand_en = cand_uk

        if cand_en:
            clean_en = cls.normalize_en(cand_en)
            if clean_en and not is_transliteration(clean_en, raw_name, raw_name_en):
                res_en = clean_en

        # If a valid Ukrainian old name exists but no English one, generate it via transliteration
        if res_uk and not res_en:
            res_en = transliterate_uk(res_uk)

        return (res_uk, res_en)

class AddressParser(osmium.SimpleHandler):
    def __init__(
        self,
        cities: List[Dict[str, Any]],
        boundary_matcher: Optional[DistrictMatcher] = None
    ):
        super().__init__()
        self.cities: List[Dict[str, Any]] = cities
        self.boundary_matcher: Optional[DistrictMatcher] = boundary_matcher
        self.streets: Dict[str, Dict[str, Any]] = {}
        self.raw_to_street_key: Dict[str, str] = {}
        self.houses: List[Dict[str, Any]] = []
        self._next_street_id: int = 1

        # Precompute lookup maps
        self.kyiv_city_id: Optional[int] = None
        for c in self.cities:
            if c['name'] == 'Київ' and c.get('place') in ('city', 'town', None):
                self.kyiv_city_id = c['db_id']
                break

        self.name_to_cities: Dict[str, List[Dict[str, Any]]] = {}
        for c in self.cities:
            key_uk = c['name'].lower()
            self.name_to_cities.setdefault(key_uk, []).append(c)
            if c.get('name_en'):
                self.name_to_cities.setdefault(c['name_en'].lower(), []).append(c)

        # Distinguish actual settlements from internal city suburbs/microdistricts
        self.settlement_cities = [c for c in self.cities if c.get('place') != 'suburb']
        self.suburb_cities = [c for c in self.cities if c.get('place') == 'suburb']

    def _find_nearest_city(
        self,
        lat: float,
        lon: float,
        addr_city: Optional[str] = None
    ) -> Optional[int]:
        # 1. Match by addr_city if provided
        if addr_city:
            clean_city = re.sub(r'^(м\.|місто|смт|село|с\.)\s*', '', addr_city.strip(), flags=re.IGNORECASE).strip().lower()
            candidates = self.name_to_cities.get(clean_city, [])
            if candidates:
                best_cand = None
                best_d = float('inf')
                for c in candidates:
                    d = (c['lat'] - lat) ** 2 + (c['lon'] - lon) ** 2
                    if d < best_d:
                        best_d = d
                        best_cand = c
                if best_cand and best_d < 0.35:
                    return best_cand['db_id']

        # 2. Check if strictly inside Kyiv municipality polygon
        if self.kyiv_city_id is not None:
            if self.boundary_matcher and self.boundary_matcher.is_in_kyiv(lat, lon):
                return self.kyiv_city_id

        # 3. Search among actual settlements (cities, towns, villages)
        min_dist = float('inf')
        nearest_id: Optional[int] = None
        for city in self.settlement_cities:
            dist = (city['lat'] - lat) ** 2 + (city['lon'] - lon) ** 2
            if dist < min_dist:
                min_dist = dist
                nearest_id = city['db_id']

        if min_dist < 0.2:  # approx ~20km tolerance
            return nearest_id

        # 4. Fallback to suburbs only if no actual settlement was found
        sub_dist = float('inf')
        nearest_suburb_id: Optional[int] = None
        for city in self.suburb_cities:
            dist = (city['lat'] - lat) ** 2 + (city['lon'] - lon) ** 2
            if dist < sub_dist:
                sub_dist = dist
                nearest_suburb_id = city['db_id']

        if sub_dist < 0.2:
            return nearest_suburb_id

        return None

    def _process_street(
        self,
        osm_id: int,
        raw_name: str,
        raw_name_en: Optional[str],
        old_name: Optional[str],
        lat: float,
        lon: float,
        old_name_uk: Optional[str] = None,
        old_name_en: Optional[str] = None,
        addr_city: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        city_id = self._find_nearest_city(lat, lon, addr_city=addr_city)
        if city_id is None:
            return None

        clean_name, type_id = StreetNormalizer.normalize(raw_name)
        clean_name_en = StreetNormalizer.normalize_en(raw_name_en) if raw_name_en else ""
        if not clean_name_en:
            clean_name_en = transliterate_uk(clean_name)

        clean_old_name, clean_old_name_en = StreetNormalizer.clean_old_names(
            raw_name=clean_name,
            raw_name_en=clean_name_en,
            old_name=old_name,
            old_name_uk=old_name_uk,
            old_name_en=old_name_en
        )

        key = f"{city_id}_{clean_name}_{type_id}"
        raw_key = f"{city_id}_{raw_name}"

        if key not in self.streets:
            self.streets[key] = {
                'db_id': self._next_street_id,
                'name': clean_name,
                'name_en': clean_name_en,
                'old_name': clean_old_name,
                'old_name_en': clean_old_name_en,
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
            if not self.streets[key].get('old_name_en') and clean_old_name_en:
                self.streets[key]['old_name_en'] = clean_old_name_en

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
                old_name = w.tags.get('old_name')
                old_name_uk = w.tags.get('old_name:uk')
                old_name_en = w.tags.get('old_name:en')
                addr_city = w.tags.get('addr:city') or w.tags.get('is_in:city')
                self._process_street(
                    w.id, raw_name, raw_name_en, old_name, lat, lon,
                    old_name_uk=old_name_uk, old_name_en=old_name_en, addr_city=addr_city
                )

            self._extract_house(w.id, w.tags, lat, lon)
        except osmium.InvalidLocationError:
            pass

    def _extract_house(self, osm_id: int, tags: Any, lat: float, lon: float) -> None:
        street_name = tags.get('addr:street')
        housenumber = tags.get('addr:housenumber')
        addr_city = tags.get('addr:city') or tags.get('is_in:city')

        if street_name and housenumber:
            city_id = self._find_nearest_city(lat, lon, addr_city=addr_city)
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

