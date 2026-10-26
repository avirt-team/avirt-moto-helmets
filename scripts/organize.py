"""Переименование и раскладка готовых файлов из «Входящие/» по папкам.

  <Артикул>_<N>.png|jpg          (AVT-CR-L_1.png)  ->  export/ready/<Артикул>/<Артикул>_<N>.<расш.>
  <Артикул>_<N>_draft.png|jpg                      ->  export/draft/<Артикул>/<Артикул>_<N>_draft.<расш.>
  <Модель>_<N>[...].png|jpg      (AVT-CR_1_x.jpg)  ->  Генерация/Кадры/<Модель>_<N>.<расш.>

Опознаётся по имени: код модели AVT-XX, необязательный размер M/L/XL, номер кадра 1-4.
Файл с размером — карточка, без размера — фото модели. Всё, что не опознано или уже
лежит на месте, остаётся во «Входящих» с пометкой в отчёте. Существующие файлы не
перезаписываются без --force.

Запуск:  python scripts/organize.py [--dry-run] [--force]
"""
import argparse
import shutil
import sys

import common as c

IMAGE_EXT = {".png", ".jpg", ".jpeg"}


def plan_target(path, info):
    """Возвращает (папка, новое имя) или (None, причина)."""
    ext = path.suffix.lower().replace(".jpeg", ".jpg")
    if info["article"]:  # карточка: имя только из артикула и кадра, латиница без пробелов
        suffix = "_draft" if info["draft"] else ""
        folder = (c.DRAFT if info["draft"] else c.READY) / info["article"]
        return folder, f"{info['article']}_{info['frame']}{suffix}{ext}"
    if info["frame"] not in c.PHOTO_FRAMES:
        return None, f"кадр {info['frame']} у фото модели не генерируется (нужны 1, 2, 4)"
    return c.PHOTOS, f"{info['code']}_{info['frame']}{ext}"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="только показать, что будет сделано")
    ap.add_argument("--force", action="store_true", help="перезаписывать существующие файлы")
    args = ap.parse_args(argv)

    c.INBOX.mkdir(exist_ok=True)
    files = sorted(p for p in c.INBOX.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXT)
    if not files:
        print(f"Во «{c.rel(c.INBOX)}» нет изображений. Положите туда файлы и запустите снова.")
        return 0

    moved = skipped = 0
    for src in files:
        info = c.parse_name(src)
        if info is None:
            print(f"  ПРОПУСК  {src.name}: имя не опознано (ждём AVT-XX[-размер]_<кадр>)")
            skipped += 1
            continue
        folder, new_name = plan_target(src, info)
        if folder is None:
            print(f"  ПРОПУСК  {src.name}: {new_name}")
            skipped += 1
            continue
        dst = folder / new_name
        if dst.exists() and not args.force:
            print(f"  ПРОПУСК  {src.name}: {c.rel(dst)} уже есть (используйте --force)")
            skipped += 1
            continue
        print(f"  {'БЫЛО БЫ ' if args.dry_run else ''}ПЕРЕНОС {src.name} -> {c.rel(dst)}")
        if not args.dry_run:
            folder.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        moved += 1

    print(f"Готово: перенесено {moved}, пропущено {skipped}.")
    return 1 if skipped else 0


if __name__ == "__main__":
    c.setup_stdout()
    sys.exit(main())
