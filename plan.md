# План розвитку: Offline Geocoding DB Generator (Версія 2.0)

> **Інструкція для AI Агента на початку нової сесії:**
> Прочитай цей документ від початку до кінця і послідовно реалізуй усі описані нижче покращення в кодовій базі `offline-geocoding-db`. Усі зміни мають бути суворо типізовані (Type hints), протестовані на сумісність та готові до роботи в GitHub Actions.

---

## 🎯 Мета
Перетворити генератор баз даних для офлайн-геокодування України на повноцінне рішення промислового рівня (production-ready). Бази даних повинні підтримувати **двомовність (UA / EN)**, **зворотне геокодування (GPS -> адреса)**, **пошук декомунізованих вулиць**, а також постачатися у стисненому вигляді разом із маніфестом оновлень для мобільних додатків.

---

## 📋 Завдання для реалізації

### 1. Повна двомовна локалізація (Українська + Англійська)
- **Схема SQLite:**
  - `cities`: додати `name_en TEXT`, `district_en TEXT`, `region_en TEXT`, `city_type TEXT`, `city_type_en TEXT` (місто/село/селище -> city/village/settlement).
  - `streets`: додати `name_en TEXT` (чиста англійська назва без типу вулиці).
  - `houses`: додати `number_en TEXT` (транслітерація літер: `10-А` -> `10-A`, `корп.` -> `bldg.`).
  - `places_fts`: оновити віртуальну таблицю, додавши колонку `name_en`, щоб повнотекстовий пошук працював обома мовами.
- **Парсинг та транслітерація:**
  - Брати теги `name:en` з OSM, якщо вони є.
  - Якщо тегу немає — автоматично транслітерувати за офіційним стандартом КМУ №55 (2010 рік).
  - Додати англійські назви для всіх 136 районів у `boundaries/rayony.geojson` або відповідний мапінг.
  - У `regions.json` додати `"name_en"` для всіх 25 регіонів (наприклад, `"Kyiv Oblast"`).

### 2. Підтримка старих назв вулиць (`old_name` / Декомунізація)
- **Схема SQLite:**
  - `streets`: додати колонку `old_name TEXT` (колишня назва вулиці).
  - `places_fts`: індексувати `old_name`, щоб при запиті старої назви (наприклад, *"Московська"*) користувач знаходив нову адресу (*"Князів Острозьких"*).
- **Парсинг:**
  - Зчитувати теги `old_name`, `old_name:uk` з ліній вулиць в OSM.

### 3. Зворотне геокодування (Reverse Geocoding через SQLite R*Tree)
- **Схема SQLite:**
  - Створити віртуальну таблицю `houses_rtree` на базі модуля SQLite `rtree`:
    ```sql
    CREATE VIRTUAL TABLE houses_rtree USING rtree(
        id,          -- house_id
        min_lat, max_lat,
        min_lon, max_lon
    );
    ```
- **Логіка:**
  - При вставці будинків заповнювати `houses_rtree`.
  - Це дозволить мобільному додатку за 1 мс знаходити найближчий будинок за координатами GPS `(lat, lon)` через запити просторового пошуку.

### 4. Поштовий індекс (`postcode`)
- Додати поле `postcode TEXT` у таблиці `cities` та `houses`.
- Зчитувати тег `addr:postcode` з OSM.

### 5. Стиснення артефактів (`.db.gz`) та `manifest.json` у CI/CD
- **Стиснення:**
  - У GitHub Actions (`.github/workflows/build-dbs.yml`) додати крок архівації згенерованих баз через `gzip -9` (наприклад, `kyiv_region.db.gz`), що зменшить розмір файлів на 60–75%.
- **Маніфест оновлень (`manifest.json`):**
  - Додати генерацію файлу `output/manifest.json`, що містить:
    - Дату збірки (`updated_at`).
    - Список усіх регіонів із назвами файлів, розміром у байтах та SHA-256 хешами для перевірки цілісності та автоматичного оновлення у клієнтських додатках.
  - Прикріплювати `manifest.json` та всі `*.db.gz` до GitHub Release.

---

## 🛠 Очікувана підсумкова схема бази даних (v2.0)

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

-- R-Tree для зворотного пошуку (GPS -> Будинок)
CREATE VIRTUAL TABLE houses_rtree USING rtree(
    id,
    min_lat, max_lat,
    min_lon, max_lon
);

-- Повнотекстовий пошук (FTS5) з підтримкою двох мов та старих назв
CREATE VIRTUAL TABLE places_fts USING fts5(
    name,
    name_en,
    old_name,
    type,        -- 'city', 'street', 'house'
    entity_id
);

-- Індекси
CREATE INDEX idx_streets_city_id ON streets(city_id);
CREATE INDEX idx_streets_type_id ON streets(type_id);
CREATE INDEX idx_houses_street_id ON houses(street_id);
```

---

## 🚀 Інструкція запуску після виконання
1. Перевірити компіляцію: `python -m py_compile *.py`
2. Зробити коміт і відправити зміни:
   ```bash
   git add .
   git commit -m "Implement v2.0: EN localization, reverse geocoding, old_name and compression"
   git push
   ```
