# 🇺🇦 Offline Geocoding DB Generator (Версія 2.0)

Високопродуктивний автономний генератор баз даних SQLite для **офлайн-геокодування України** у мобільних та десктопних додатках (React Native, Flutter, iOS/Swift, Android/Kotlin).

Перетворює сирі дані OpenStreetMap (OSM) на оптимізовані компактні бази даних SQLite з підтримкою **двомовності (UA/EN)**, **зворотного геокодування (GPS $\rightarrow$ адреса через R\*Tree)**, пошуку за **декомунізованими назвами (`old_name`)** та повнотекстового індексу **FTS5**.

---

## 🌟 Ключові можливості (v2.0)

- 🌐 **Повна двомовна локалізація (Українська + Англійська):**
  - Офіційна транслітерація за стандартом **Постанови Кабінету Міністрів України № 55 від 2010 р.** (з урахуванням позиційних правил `Ye`/`ie`, `Yi`/`i`, `Yu`/`iu`, `Ya`/`ia`, `zgh` та ігноруванням апострофа).
  - Назви міст, типів населених пунктів (`місто` $\rightarrow$ `city`, `село` $\rightarrow$ `village`, `селище` $\rightarrow$ `settlement`), районів, областей, вулиць та номерів будинків (`10-А` $\rightarrow$ `10-A`, `корп.` $\rightarrow$ `bldg.`).
  - Перекладені всі 136 нових районів України у `boundaries/rayony.geojson` та 25 регіонів у `regions.json`.
- 🏛️ **Підтримка старих назв (Декомунізація):**
  - Збереження та індексація `old_name` для вулиць. Користувач вводить стару назву (наприклад, *"Московська"*), а пошук знаходить сучасну адресу (*"Князів Острозьких"*).
- ⚡ **Миттєве зворотне геокодування (Reverse Geocoding через SQLite R\*Tree):**
  - Таблиця `houses_rtree` забезпечує просторовий пошук найближчого будинку за GPS-координатами `(lat, lon)` за $\le 1$ мілісекунду без навантаження на CPU.
- 📮 **Поштові індекси (`postcode`):**
  - Повні індекси для населених пунктів та адресних точок.
- 🗜️ **Стиснення та контроль цілісності у CI/CD:**
  - Автоматичне пакування у `.db.gz` (економія до 75% трафіку).
  - Генерація `output/manifest.json` з розмірами файлів та SHA-256 контрольними сумами для автоматичного оновлення у мобільних додатках.

---

## 🗄️ Схема бази даних SQLite (v2.0)

База даних оптимізована для мінімального розміру на диску та максимальної швидкості читання.

```sql
-- Довідник типів вулиць (вулиця, проспект, провулок тощо)
CREATE TABLE street_types (
    id INTEGER PRIMARY KEY,
    name_uk TEXT NOT NULL,
    short_uk TEXT NOT NULL,
    name_en TEXT NOT NULL,
    short_en TEXT NOT NULL
);

-- Населені пункти
CREATE TABLE cities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,           -- Назва українською (напр. "Київ")
    name_en TEXT,                 -- Назва англійською (напр. "Kyiv")
    city_type TEXT,               -- Тип (місто, село, селище)
    city_type_en TEXT,            -- Тип англійською (city, village, settlement)
    district TEXT,                -- Район (напр. "Бучанський район")
    district_en TEXT,             -- Район англійською (напр. "Buchanskyi Raion")
    region TEXT,                  -- Область (напр. "Київська область")
    region_en TEXT,               -- Область англійською (напр. "Kyiv Oblast")
    postcode TEXT,                -- Поштовий індекс
    lat REAL NOT NULL,            -- Широта
    lon REAL NOT NULL,            -- Довгота
    osm_id INTEGER
);

-- Вулиці
CREATE TABLE streets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    city_id INTEGER,              -- Зв'язок із таблицею cities(id)
    name TEXT NOT NULL,           -- Чиста назва (напр. "Князів Острозьких")
    name_en TEXT,                 -- Чиста назва англійською ("Kniaziv Ostrozkykh")
    old_name TEXT,                -- Колишня назва (напр. "Московська")
    type_id INTEGER DEFAULT 1,    -- Зв'язок із street_types(id)
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    osm_id INTEGER,
    FOREIGN KEY(city_id) REFERENCES cities(id),
    FOREIGN KEY(type_id) REFERENCES street_types(id)
);

-- Будинки (адресні точки)
CREATE TABLE houses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    street_id INTEGER,            -- Зв'язок із streets(id)
    number TEXT NOT NULL,         -- Номер українською (напр. "10-А корп. 1")
    number_en TEXT,               -- Номер англійською (напр. "10-A bldg. 1")
    postcode TEXT,                -- Поштовий індекс будинку
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    osm_id INTEGER,
    FOREIGN KEY(street_id) REFERENCES streets(id)
);

-- Просторово-координатний індекс для зворотного геокодування (GPS -> Будинок)
CREATE VIRTUAL TABLE houses_rtree USING rtree(
    id,          -- house_id (збігається з houses.id)
    min_lat, max_lat,
    min_lon, max_lon
);

-- Повнотекстовий пошук (FTS5) двома мовами та за старими назвами
CREATE VIRTUAL TABLE places_fts USING fts5(
    name,        -- Назва українською
    name_en,     -- Назва англійською
    old_name,    -- Колишня назва (для вулиць)
    type,        -- 'city' | 'street' | 'house'
    entity_id    -- ID відповідного запису в cities, streets або houses
);

-- B-Tree Індекси
CREATE INDEX idx_streets_city_id ON streets(city_id);
CREATE INDEX idx_streets_type_id ON streets(type_id);
CREATE INDEX idx_houses_street_id ON houses(street_id);
```

---

## 🛠️ Встановлення та локальний запуск

### 1. Системні вимоги
- **Python 3.10+**
- Утиліта **`osmium-tool`** для нарізання полігонів:
  - **macOS:** `brew install osmium-tool`
  - **Ubuntu / Debian:** `sudo apt-get update && sudo apt-get install -y osmium-tool jq gzip`

### 2. Клонування та налаштування оточення
```bash
git clone https://github.com/Pratnomenis/offline-geocoding-db.git
cd offline-geocoding-db

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Завантаження сирих даних OpenStreetMap
Скрипт автоматично завантажує актуальний дамп України (`ukraine-latest.osm.pbf`) з Geofabrik та кешує його:
```bash
python3 download.py
```

### 4. Генерація бази даних для обраного регіону
Список доступних ключів регіонів знаходиться у [`regions.json`](file:///Users/povar/Developer-2026/geo-db/regions.json) (наприклад, `kyiv`, `lviv`, `odesa`, `kharkiv` тощо).

```bash
# Генерація бази для Київської області
python3 pipeline.py --input data/ukraine-latest.osm.pbf --region kyiv
```
Результат буде збережено у файл `output/kyiv_region.db`.

### 5. Стиснення баз та генерація маніфесту
```bash
# Стиснення баз за допомогою gzip -9
gzip -9 output/*.db

# Створення output/manifest.json з контрольними сумами SHA-256
python3 generate_manifest.py --output-dir output
```

### 6. Запуск тестів
У проєкті є вбудований тестовий набір, що перевіряє транслітерацію, полігони районів, R\*Tree, FTS5 та маніфест:
```bash
python3 test_suite.py
```

---

## 📱 Інтеграція у клієнтські додатки

### Формат оновлень: `manifest.json`
Клієнтський додаток (мобільний або веб) перевіряє `manifest.json` перед завантаженням:

```json
{
  "updated_at": "2026-10-11T08:22:32.160124+00:00",
  "regions": [
    {
      "id": "kyiv",
      "name_uk": "Київська область",
      "name_en": "Kyiv Oblast",
      "filename": "kyiv_region.db.gz",
      "size_bytes": 14582910,
      "sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    }
  ]
}
```

Додаток завантажує `kyiv_region.db.gz`, звіряє SHA-256, розпаковує через стандартний zlib/gzip і підключає базу через SQLite драйвер (наприклад, `op-sqlite` / `react-native-quick-sqlite` у React Native або `sqflite` у Flutter).

---

## 💡 Приклади типових SQL-запитів

### 1. Зворотне геокодування (GPS $\rightarrow$ Найближча адреса за 1 мс)
Використовує просторовий R\*Tree пошук у вікні $\approx 100$ метрів навколо координат з точним сортуванням за відстанню:

```sql
SELECT 
    h.number,
    h.number_en,
    h.postcode,
    st.name_uk AS street_type,
    st.name_en AS street_type_en,
    s.name AS street_name,
    s.name_en AS street_name_en,
    c.name AS city_name,
    c.name_en AS city_name_en,
    c.district,
    c.district_en,
    c.region,
    c.region_en,
    ((h.lat - :user_lat) * (h.lat - :user_lat) + (h.lon - :user_lon) * (h.lon - :user_lon)) AS dist_sq
FROM houses_rtree r
JOIN houses h ON r.id = h.id
JOIN streets s ON h.street_id = s.id
JOIN street_types st ON s.type_id = st.id
JOIN cities c ON s.city_id = c.id
WHERE r.min_lat <= :user_lat + 0.001 AND r.max_lat >= :user_lat - 0.001
  AND r.min_lon <= :user_lon + 0.001 AND r.max_lon >= :user_lon - 0.001
ORDER BY dist_sq ASC
LIMIT 1;
```

---

### 2. Повнотекстовий пошук за адресою (Forward Geocoding)
Пошук однаково ефективно працює українською, англійською або за декомунізованою назвою:

```sql
-- Пошук за сучасною назвою українською
SELECT fts.type, s.name AS street, c.name AS city
FROM places_fts fts
JOIN streets s ON fts.entity_id = s.id AND fts.type = 'street'
JOIN cities c ON s.city_id = c.id
WHERE places_fts MATCH 'Острозьких*'
LIMIT 10;

-- Пошук за старою (радянською/декомунізованою) назвою: знайде Князів Острозьких
SELECT s.name AS current_name, s.old_name, c.name AS city
FROM places_fts fts
JOIN streets s ON fts.entity_id = s.id AND fts.type = 'street'
JOIN cities c ON s.city_id = c.id
WHERE places_fts MATCH 'Московська*'
LIMIT 10;

-- Пошук англійською мовою
SELECT s.name_en AS street_en, c.name_en AS city_en
FROM places_fts fts
JOIN streets s ON fts.entity_id = s.id AND fts.type = 'street'
JOIN cities c ON s.city_id = c.id
WHERE places_fts MATCH 'Ostrozkykh*'
LIMIT 10;
```

---

### 3. Автодоповнення при введенні номеру будинку
Якщо користувач обрав вулицю з `street_id = 42`:

```sql
SELECT h.id, h.number, h.number_en, h.lat, h.lon, h.postcode
FROM houses h
WHERE h.street_id = 42 AND h.number LIKE '10%'
ORDER BY h.number ASC
LIMIT 20;
```

---

### 4. Отримання повної інформації про місто
```sql
SELECT 
    name, name_en,
    city_type, city_type_en,
    district, district_en,
    region, region_en,
    lat, lon
FROM cities
WHERE name = 'Бориспіль';
```

---

## 🤖 Автоматизація в GitHub Actions

Щонеділі о **02:00 UTC** автоматичний воркфлоу [`.github/workflows/build-dbs.yml`](file:///Users/povar/Developer-2026/geo-db/.github/workflows/build-dbs.yml):
1. Завантажує свіжий дамп України з Geofabrik.
2. Проганяє пайплайн по черзі для всіх 25 регіонів із `regions.json`.
3. Стискає всі бази у `*.db.gz`.
4. Генерує `manifest.json`.
5. Створює/оновлює **GitHub Release `latest`**, прикріплюючи всі бази та маніфест.

---

## 📄 Ліцензія
Дані надаються на умовах ліцензії [Open Data Commons Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/) від OpenStreetMap Foundation.
Код пайплайну розповсюджується під ліцензією MIT.
