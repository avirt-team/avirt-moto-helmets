"""Проверка комплектности: для каждого артикула из Данные.csv собраны все кадры.

Выгрузка (export/):
  * на артикул 4 файла в export/ready/<Артикул>/<Артикул>_<1-4>.png; для кадра с `?????`
    в данных вместо него export/draft/<Артикул>/<Артикул>_<N>_draft.png;
  * каждый PNG ровно 1080 x 1440, RGB, без прозрачности, не тяжелее 10 МБ;
  * имена и папки только латиница, цифры, `_` и `-` (без пробелов и русских букв);
  * лишних файлов нет: всё, что не <Артикул>_<N>[_draft].png на своём месте, — замечание.
Фото (Генерация/Кадры/): на модель кадры 1, 2 и 4 в JPG 1536 x 2752.
Фото товара (Фото/): <Артикул>.jpg для каждого артикула.

Код возврата 0 — всё собрано, 1 — есть недостающее или негодное.

Запуск:  python scripts/check.py [--articles AVT-CR-L AVT-FF-M ...] [--no-photos]
"""
import argparse
import sys

from PIL import Image

import common as c


def image_info(path):
    with Image.open(path) as im:
        return im.size, im.mode, im.format


def check_card(article, row, frame, problems):
    """Возвращает короткий статус кадра для таблицы."""
    draft_needed = c.frame_needs_draft(row, frame)
    want = c.card_path(article, frame, draft=draft_needed)
    other = c.card_path(article, frame, draft=not draft_needed)

    if not want.exists():
        if other.exists():
            why = ("в данных `?????`: кадр должен лежать в export/draft/ с _draft" if draft_needed
                   else "в данных нет `?????`: кадр должен лежать в export/ready/ без _draft")
            problems.append(f"{article} кадр {frame}: найден {c.rel(other)}, но {why}")
            return "имя"
        problems.append(f"{article} кадр {frame}: нет файла {c.rel(want)}")
        return "нет"
    if other.exists():
        problems.append(f"{article} кадр {frame}: лежат оба файла, {c.rel(want)} и {c.rel(other)}")
        return "дубль"
    try:
        size, mode, fmt = image_info(want)
    except OSError as e:
        problems.append(f"{want.name}: файл не открывается ({e})")
        return "битый"
    errors = []
    if size != c.CARD_SIZE:
        errors.append(f"размер {size[0]}x{size[1]}, нужен 1080x1440")
    if fmt != "PNG" or mode != "RGB":
        errors.append(f"формат {fmt}/{mode}, нужен PNG/RGB без прозрачности")
    weight = want.stat().st_size
    if weight > c.MAX_UPLOAD_BYTES:
        errors.append(f"вес {weight / 1024 / 1024:.1f} МБ, предел площадки {c.MAX_UPLOAD_BYTES // 1024 // 1024} МБ")
    for e in errors:
        problems.append(f"{want.name}: {e}")
    if errors:
        return "формат"
    return "черновик" if draft_needed else "ok"


def check_stray(all_articles, problems):
    """Всё лишнее в export/: чужие имена, русские буквы, пробелы, файлы не на своём месте."""
    if not c.CARDS.is_dir():
        return
    expected_dirs = {c.READY.name, c.DRAFT.name}
    for path in sorted(c.CARDS.rglob("*")):
        parts = path.relative_to(c.CARDS).parts
        if path.name == ".gitkeep":
            continue
        bad_name = [p for p in parts if not c.SAFE_NAME_RE.match(p)]
        if bad_name:
            problems.append(f"{c.rel(path)}: в имени недопустимые символы ({', '.join(bad_name)}); "
                            "нужны латиница, цифры, _ и -, без пробелов и русских букв")
            continue
        if path.is_dir():
            if len(parts) == 1 and path.name not in expected_dirs:
                problems.append(f"{c.rel(path)}: лишняя папка, в export/ только ready/ и draft/")
            elif len(parts) == 2 and path.name not in all_articles:
                problems.append(f"{c.rel(path)}: нет такого артикула в Данные.csv")
            continue
        info = c.parse_name(path)
        ok = (len(parts) == 3 and parts[0] in expected_dirs and info and info["article"] == parts[1]
              and path.name == c.card_name(info["article"], info["frame"], info["draft"])
              and info["draft"] == (parts[0] == c.DRAFT.name))
        if not ok:
            problems.append(f"{c.rel(path)}: файл не на своём месте или с чужим именем; "
                            "ждём export/ready|draft/<Артикул>/<Артикул>_<N>[_draft].png "
                            "(запустите scripts/run.py organize/convert)")


def check_photo(code, frame, problems):
    path = c.PHOTOS / c.photo_name(code, frame)
    if not path.exists():
        problems.append(f"{code} фото кадра {frame}: нет файла {c.rel(path)}")
        return "нет"
    try:
        size, _, fmt = image_info(path)
    except OSError as e:
        problems.append(f"{path.name}: файл не открывается ({e})")
        return "битый"
    if size != c.PHOTO_SIZE or fmt != "JPEG":
        problems.append(f"{path.name}: {fmt} {size[0]}x{size[1]}, нужен JPEG 1536x2752")
        return "формат"
    return "ok"


def table(headers, rows):
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = lambda r: "  ".join(str(x).ljust(w) for x, w in zip(r, widths)).rstrip()
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for r in rows:
        print(line(r))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--articles", nargs="+", metavar="АРТИКУЛ",
                    help="проверить только эти артикулы (по умолчанию все из Данные.csv)")
    ap.add_argument("--no-photos", action="store_true", help="не проверять фото и Фото/")
    args = ap.parse_args(argv)

    rows = c.read_articles()
    if args.articles:
        wanted = {a.upper() for a in args.articles}
        unknown = wanted - {r["Артикул"] for r in rows}
        if unknown:
            print(f"Нет в Данные.csv: {', '.join(sorted(unknown))}")
            return 2
        rows = [r for r in rows if r["Артикул"] in wanted]

    problems = []
    print("Карточки (export/):")
    cards = []
    for row in rows:
        art = row["Артикул"]
        cards.append([art] + [check_card(art, row, f, problems) for f in c.CARD_FRAMES])
    table(["Артикул"] + [f"кадр {f}" for f in c.CARD_FRAMES], cards)

    check_stray({r["Артикул"] for r in c.read_articles()}, problems)

    if not args.no_photos:
        print("\nФото моделей (Генерация/Кадры/):")
        codes = sorted({r["Артикул"].rsplit("-", 1)[0] for r in rows})
        photos = [[code] + [check_photo(code, f, problems) for f in c.PHOTO_FRAMES] for code in codes]
        table(["Модель"] + [f"кадр {f}" for f in c.PHOTO_FRAMES], photos)

        print("\nФото товара (Фото/):")
        for row in rows:
            p = c.PRODUCT_PHOTOS / f"{row['Артикул']}.jpg"
            if not p.exists():
                problems.append(f"{row['Артикул']}: нет фото товара {c.rel(p)}")
        missing = [p for p in problems if "нет фото товара" in p]
        print("все на месте" if not missing else f"не хватает: {len(missing)}")

    ok = sum(1 for r in cards for s in r[1:] if s in ("ok", "черновик"))
    drafts = sum(1 for r in cards for s in r[1:] if s == "черновик")
    print(f"\nКарточки: {ok} из {len(cards) * len(c.CARD_FRAMES)} кадров в порядке"
          f" (из них черновиков для заказчика: {drafts}).")
    if problems:
        print(f"\nЗамечаний: {len(problems)}")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Всё собрано.")
    return 0


if __name__ == "__main__":
    c.setup_stdout()
    sys.exit(main())
