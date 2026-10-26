"""Общие константы и функции скриптов проекта (см. scripts/README.md)."""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INBOX = ROOT / "Входящие"            # сюда кладут свежие файлы как есть
SOURCES = INBOX / "_исходники"       # сюда уходят оригиналы после конвертации
CARDS = ROOT / "export"              # выгрузка: ready/<Артикул>/ и draft/<Артикул>/ (ASCII-имена)
READY = CARDS / "ready"              # можно загружать на площадку
DRAFT = CARDS / "draft"              # есть `?????`, согласуется с заказчиком, не публикуется
PHOTOS = ROOT / "Генерация" / "Кадры"  # сгенерированные фото <Модель>_<N>.jpg
PRODUCT_PHOTOS = ROOT / "Фото"       # фото товара <Артикул>.jpg
DATA = ROOT / "Данные.csv"

CARD_SIZE = (1080, 1440)             # Критерии кадра.md, 1.1
PHOTO_SIZE = (1536, 2752)            # Генерация фото.md, «Формат выдачи»
PHOTO_QUALITY = 95                   # требование: JPG, качество >= 90
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # Wildberries и Ozon: файл до 10 МБ (JPG/PNG/WEBP, 3:4, рекомендовано 900x1200)
SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[a-z0-9]+)?$")  # латиница, цифры, _ и -; без пробелов
FRAME_BG = (231, 231, 231)           # Фон/Кадр #E7E7E7, подложка вместо прозрачности

CARD_FRAMES = (1, 2, 3, 4)           # у карточки всегда четыре кадра
PHOTO_FRAMES = (1, 2, 4)             # кадр 3 — одно фото на все артикулы

# Какие поля данных попадают на какой кадр (README.md, таблица свойств).
# Нужно, чтобы понять, должен ли кадр быть черновиком (_draft), если в поле `?????`.
FRAME_FIELDS = {
    1: ("Модель", "Линейка", "Размер", "Главная выгода"),
    2: ("Материал скорлупы", "Замок ремня", "Подкладка", "Вес, г", "Вентиляция"),
    3: ("Обхват головы, см",),
    4: ("Визор", "Подпись визора", "Сертификат", "Гарантия", "Страна производства"),
}
NO_DATA = "?????"

# Артикул AVT-CR-L и код модели AVT-CR в имени файла; регистр и разделители терпим.
NAME_RE = re.compile(
    r"(?P<code>AVT-[A-Z]{2})(?:-(?P<size>XL|M|L))?"
    r"[\s_\-]*(?P<frame>[1-4])(?![0-9])"
    r"(?P<rest>.*)$",
    re.IGNORECASE,
)


def setup_stdout():
    """Кириллица в консоли Windows."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def parse_name(path):
    """Разбирает имя файла. Возвращает dict или None, если имя не опознано.

    code — код модели (AVT-CR), size — M/L/XL или None, frame — 1..4,
    draft — есть ли в имени `draft`, article — AVT-CR-L или None.
    """
    m = NAME_RE.search(Path(path).stem)
    if not m:
        return None
    code = m.group("code").upper()
    size = m.group("size").upper() if m.group("size") else None
    return {
        "code": code,
        "size": size,
        "article": f"{code}-{size}" if size else None,
        "frame": int(m.group("frame")),
        "draft": "draft" in m.group("rest").lower(),
    }


def read_articles():
    """Строки Данные.csv как список dict (UTF-8 с BOM, разделитель `;`)."""
    with DATA.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def frame_needs_draft(row, frame):
    """True, если на этом кадре артикула стоит `?????` (кадр — черновик)."""
    return any(row.get(field, "").strip() == NO_DATA for field in FRAME_FIELDS[frame])


def card_name(article, frame, draft=False):
    return f"{article}_{frame}{'_draft' if draft else ''}.png"


def card_path(article, frame, draft=False):
    """Где лежит карточка: export/ready|draft/<Артикул>/<Артикул>_<N>[_draft].png"""
    return (DRAFT if draft else READY) / article / card_name(article, frame, draft)


def photo_name(code, frame):
    return f"{code}_{frame}.jpg"


def rel(path):
    """Путь для вывода — относительно корня проекта."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)
