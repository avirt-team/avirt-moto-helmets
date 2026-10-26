"""Перевод кадров в нужный размер и формат.

  export/**/*.png|jpg     -> PNG 1080 x 1440, sRGB, без прозрачности и метаданных, до 10 МБ;
                             файл кладётся в export/ready|draft/<Артикул>/ по своему имени
  Генерация/Кадры/*.*     -> JPG 1536 x 2752, качество 95 (Генерация фото.md)

Правила:
  * Пропорции не искажаются никогда (критерий 1.5). Если у файла те же пропорции,
    он масштабируется. Если пропорции другие, кадр НЕ трогается, в отчёте ошибка:
    такой кадр нужно переэкспортировать или перегенерировать, а не растягивать.
    Исключение: фото чуть не 9:16 (в пределах 3 %) обрезаются по центру.
  * Фото меньше нужного размера не увеличиваются: апскейл не добавляет деталей.
    Такие файлы пропускаются с пометкой. С --upscale они сохраняются как
    <имя>_upscaled.jpg и в проверке комплектности не засчитываются.
  * Прозрачность заливается цветом Фон/Кадр #E7E7E7.
  * Оригинал, который пришлось менять или переносить, уходит в «Входящие/_исходники/»
    (папка в .gitignore: тяжёлые исходники в репозиторий не попадают).
  * PNG тяжелее 10 МБ не записывается: площадки такое не принимают, кадр нужно упростить.

Запуск:  python scripts/convert.py [--dry-run] [--upscale]
"""
import argparse
import io
import shutil
import sys
from datetime import datetime

from PIL import Image, ImageCms, ImageOps

import common as c

IMAGE_EXT = {".png", ".jpg", ".jpeg"}
CROP_TOLERANCE = 0.03  # допустимое отличие пропорций для обрезки фото


def to_srgb(im):
    """Переводит из встроенного ICC-профиля в sRGB: цвета на площадке не «поплывут»."""
    profile = im.info.get("icc_profile")
    if not profile:
        return im
    try:
        src = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        return ImageCms.profileToProfile(im, src, ImageCms.createProfile("sRGB"), outputMode="RGB")
    except (ImageCms.PyCMSError, OSError):
        return im


def load_rgb(path):
    """Открывает файл с учётом EXIF-поворота; прозрачность заливает фоном кадра."""
    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, c.FRAME_BG)
        bg.paste(im, mask=im.split()[-1])
        return bg
    return to_srgb(im.convert("RGB") if im.mode != "RGB" else im)


def ratio(size):
    return size[0] / size[1]


def fit_exact(im, target, tolerance):
    """Масштабирует к target без искажений. Возвращает (картинка, пометка) или (None, ошибка)."""
    diff = abs(ratio(im.size) / ratio(target) - 1)
    if diff > tolerance:
        return None, (f"пропорции {im.size[0]}x{im.size[1]} не совпадают с "
                      f"{target[0]}x{target[1]} (отличие {diff:.1%}), кадр нужно переделать")
    note = ""
    if diff > 0.002:  # лёгкая подрезка до точной пропорции
        w, h = im.size
        new_w = min(w, round(h * ratio(target)))
        new_h = min(h, round(w / ratio(target)))
        left, top = (w - new_w) // 2, (h - new_h) // 2
        im = im.crop((left, top, left + new_w, top + new_h))
        note = f", обрезка по центру ({diff:.1%})"
    return im.resize(target, Image.LANCZOS), note


def convert_card(src, dry, report):
    info = c.parse_name(src)
    if not info or not info["article"]:
        report.append(("ОШИБКА", src, "имя не похоже на <Артикул>_<кадр>; запустите organize.py"))
        return
    im = load_rgb(src)
    out, note = fit_exact(im, c.CARD_SIZE, tolerance=0.0)
    if out is None:
        report.append(("ОШИБКА", src, note))
        return
    dst = c.card_path(info["article"], info["frame"], info["draft"])
    if src == dst and src.suffix == ".png" and im.size == c.CARD_SIZE and is_clean_png(src):
        report.append(("ОК", src, "уже 1080x1440 PNG sRGB, имя и папка верные"))
        return
    write(src, dst, out, "PNG", dry, report, f"{im.size[0]}x{im.size[1]} -> 1080x1440 PNG{note}",
          limit=c.MAX_UPLOAD_BYTES, optimize=True)


def is_clean_png(path):
    """PNG, RGB, без встроенного профиля и текстовых метаданных, до лимита площадки."""
    with Image.open(path) as im:
        return (im.format == "PNG" and im.mode == "RGB" and not im.info.get("icc_profile")
                and not any(k in im.info for k in ("exif", "XML:com.adobe.xmp", "Software", "Comment"))
                and path.stat().st_size <= c.MAX_UPLOAD_BYTES)


def convert_photo(src, dry, report, upscale):
    info = c.parse_name(src)
    if not info or info["article"]:
        report.append(("ОШИБКА", src, "ждём имя фото модели вида AVT-XX_<кадр> (без размера)"))
        return
    if info["frame"] not in c.PHOTO_FRAMES:
        report.append(("ОШИБКА", src, "кадр 3 не генерируется, фото модели бывают только 1, 2 и 4"))
        return
    im = load_rgb(src)
    small = im.size[0] < c.PHOTO_SIZE[0] or im.size[1] < c.PHOTO_SIZE[1]
    if small and not upscale:
        report.append(("ПРОПУСК", src, f"{im.size[0]}x{im.size[1]}: меньше 1536x2752, нужна "
                       "генерация в 2K+ (или --upscale для черновой растяжки)"))
        return
    out, note = fit_exact(im, c.PHOTO_SIZE, tolerance=CROP_TOLERANCE)
    if out is None:
        report.append(("ОШИБКА", src, note))
        return
    if im.size == c.PHOTO_SIZE and src == c.PHOTOS / c.photo_name(info["code"], info["frame"])             and src.suffix == ".jpg":
        report.append(("ОК", src, "уже 1536x2752 JPG, имя верное"))
        return
    if small:
        dst = c.PHOTOS / f"{info['code']}_{info['frame']}_upscaled.jpg"
        note += ", АПСКЕЙЛ без новых деталей"
    else:
        dst = c.PHOTOS / c.photo_name(info["code"], info["frame"])
    write(src, dst, out, "JPEG", dry, report,
          f"{im.size[0]}x{im.size[1]} -> 1536x2752 JPG q{c.PHOTO_QUALITY}{note}",
          quality=c.PHOTO_QUALITY, optimize=True, subsampling=0)


def archive(src):
    """Прячет оригинал в «Входящие/_исходники/» (в .gitignore), не затирая старые."""
    c.SOURCES.mkdir(parents=True, exist_ok=True)
    target = c.SOURCES / src.name
    if target.exists():
        target = c.SOURCES / f"{src.stem}_{datetime.now():%H%M%S}{src.suffix}"
    shutil.move(str(src), str(target))


def write(src, dst, image, fmt, dry, report, message, limit=None, **save_args):
    if dry:
        report.append(("БЫЛО БЫ", src, f"{message} -> {c.rel(dst)}"))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    image.save(tmp, fmt, **save_args)  # без icc/exif: метаданные не передаются
    if limit and tmp.stat().st_size > limit:
        mb = tmp.stat().st_size / 1024 / 1024
        tmp.unlink()
        report.append(("ОШИБКА", src, f"после конвертации {mb:.1f} МБ, предел площадки "
                       f"{limit // 1024 // 1024} МБ; упростите кадр, файл не записан"))
        return
    if src.resolve() != dst.resolve() and src.exists():
        archive(src)
    elif src.resolve() == dst.resolve():
        archive_copy = c.SOURCES / src.name
        c.SOURCES.mkdir(parents=True, exist_ok=True)
        if archive_copy.exists():
            archive_copy = c.SOURCES / f"{src.stem}_{datetime.now():%H%M%S}{src.suffix}"
        shutil.copyfile(src, archive_copy)
    tmp.replace(dst)
    report.append(("ГОТОВО", src, f"{message} -> {c.rel(dst)}"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    ap.add_argument("--upscale", action="store_true",
                    help="увеличивать маленькие фото (сохраняются как *_upscaled.jpg)")
    args = ap.parse_args(argv)

    report = []
    for folder, handler in ((c.CARDS, "card"), (c.PHOTOS, "photo")):
        if not folder.is_dir():
            continue
        found = folder.rglob("*") if handler == "card" else folder.iterdir()
        for src in sorted(p for p in found if p.is_file() and p.suffix.lower() in IMAGE_EXT):
            if src.stem.endswith("_upscaled"):
                continue
            try:
                if handler == "card":
                    convert_card(src, args.dry_run, report)
                else:
                    convert_photo(src, args.dry_run, report, args.upscale)
            except OSError as e:
                report.append(("ОШИБКА", src, f"не удалось открыть файл: {e}"))

    if not report:
        print("Нечего конвертировать: в export/ и Генерация/Кадры/ нет изображений.")
        return 0
    for status, src, message in report:
        print(f"  {status:8} {c.rel(src)}: {message}")
    bad = sum(1 for s, _, _ in report if s in ("ОШИБКА", "ПРОПУСК"))
    print(f"Готово: обработано {len(report) - bad}, требуют внимания {bad}.")
    return 1 if bad else 0


if __name__ == "__main__":
    c.setup_stdout()
    sys.exit(main())
