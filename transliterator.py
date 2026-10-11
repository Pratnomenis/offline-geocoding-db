import re
from typing import Optional

CYRILLIC_LETTERS = set('абвгґдеєжзиіїйклмнопрстуфхцчшщьюяАБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯ')
APOSTROPHES = set("'’ʻʼ`")

MAP_START = {
    'Є': 'Ye', 'є': 'ye',
    'Ї': 'Yi', 'ї': 'yi',
    'Й': 'Y',  'й': 'y',
    'Ю': 'Yu', 'ю': 'yu',
    'Я': 'Ya', 'я': 'ya',
}

MAP_INSIDE = {
    'Є': 'Ie', 'є': 'ie',
    'Ї': 'I',  'ї': 'i',
    'Й': 'I',  'й': 'i',
    'Ю': 'Iu', 'ю': 'iu',
    'Я': 'Ia', 'я': 'ia',
}

MAP_COMMON = {
    'А': 'A', 'а': 'a',
    'Б': 'B', 'б': 'b',
    'В': 'V', 'в': 'v',
    'Г': 'H', 'г': 'h',
    'Ґ': 'G', 'ґ': 'g',
    'Д': 'D', 'д': 'd',
    'Е': 'E', 'е': 'e',
    'Ж': 'Zh', 'ж': 'zh',
    'З': 'Z', 'з': 'z',
    'И': 'Y', 'и': 'y',
    'І': 'I', 'і': 'i',
    'К': 'K', 'к': 'k',
    'Л': 'L', 'л': 'l',
    'М': 'M', 'м': 'm',
    'Н': 'N', 'н': 'n',
    'О': 'O', 'о': 'o',
    'П': 'P', 'п': 'p',
    'Р': 'R', 'р': 'r',
    'С': 'S', 'с': 's',
    'Т': 'T', 'т': 't',
    'У': 'U', 'у': 'u',
    'Ф': 'F', 'ф': 'f',
    'Х': 'Kh', 'х': 'kh',
    'Ц': 'Ts', 'ц': 'ts',
    'Ч': 'Ch', 'ч': 'ch',
    'Ш': 'Sh', 'ш': 'sh',
    'Щ': 'Shch', 'щ': 'shch',
    'Ь': '', 'ь': '',
}

def transliterate_uk(text: Optional[str]) -> str:
    """Transliterates Ukrainian text to Latin according to KMU Resolution No. 55 (2010)."""
    if not text:
        return ""

    # Special handling for 'зг' -> 'zgh'
    # Use placeholder to avoid interfering with normal 'з' and 'г'
    working = text
    working = re.sub(r'ЗГ', 'ZGH', working)
    working = re.sub(r'Зг', 'Zgh', working)
    working = re.sub(r'зг', 'zgh', working)

    res = []
    for i, ch in enumerate(working):
        if ch in APOSTROPHES:
            continue
        if ch in MAP_START or ch in MAP_INSIDE:
            is_start = False
            if i == 0:
                is_start = True
            else:
                prev = working[i - 1]
                if prev in APOSTROPHES:
                    k = i - 1
                    while k >= 0 and working[k] in APOSTROPHES:
                        k -= 1
                    is_start = (k < 0 or working[k] not in CYRILLIC_LETTERS)
                elif prev not in CYRILLIC_LETTERS:
                    is_start = True

            mapping = MAP_START if is_start else MAP_INSIDE
            res.append(mapping[ch])
        elif ch in MAP_COMMON:
            res.append(MAP_COMMON[ch])
        else:
            res.append(ch)

    return "".join(res)

HOUSE_ABBREVIATIONS = [
    (re.compile(r'(?:\bкорпус\b|\bкорп\.?|\bк\.)', re.IGNORECASE), 'bldg. '),
    (re.compile(r'(?:\bбудинок\b|\bбуд\.?|\bб\.)', re.IGNORECASE), 'bldg. '),
    (re.compile(r'(?:\bлітера\b|\bліт\.?)', re.IGNORECASE), 'lit. '),
    (re.compile(r'(?:\bквартира\b|\bкв\.?)', re.IGNORECASE), 'apt. '),
    (re.compile(r'(?:\bприміщення\b|\bприм\.?)', re.IGNORECASE), 'prem. '),
    (re.compile(r'(?:\bгараж\b|\bгар\.?)', re.IGNORECASE), 'gar. '),
    (re.compile(r'\bбокс\b', re.IGNORECASE), 'box '),
    (re.compile(r'(?:\bсекція\b|\bсекц\.?)', re.IGNORECASE), 'sec. '),
]

def transliterate_house_number(raw_num: Optional[str]) -> str:
    """Translates and transliterates Ukrainian house numbers to English.
    Examples:
      '10-А' -> '10-A'
      '5 корп. 2' -> '5 bldg. 2'
      '12/1-Б' -> '12/1-B'
    """
    if not raw_num:
        return ""

    num_str = raw_num
    for pattern, replacement in HOUSE_ABBREVIATIONS:
        num_str = pattern.sub(replacement, num_str)

    # Clean multiple spaces
    num_str = re.sub(r'\s+', ' ', num_str).strip()

    # Transliterate any remaining Cyrillic letters
    return transliterate_uk(num_str)
