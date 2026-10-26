"""Единая точка входа: python scripts/run.py <команда> [аргументы команды]

  organize   разложить файлы из «Входящие/» по папкам и переименовать
  convert    привести кадры к нужному размеру и формату
  check      проверить комплектность кадров по всем артикулам
  all        organize -> convert -> check подряд; код возврата — от check

Примеры:
  python scripts/run.py all
  python scripts/run.py organize --dry-run
  python scripts/run.py check --articles AVT-CR-L
"""
import sys

import check
import common as c
import convert
import organize

COMMANDS = {"organize": organize.main, "convert": convert.main, "check": check.main}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "all":
        # Замечания organize/convert (пропуск файла) не мешают проверке: check их увидит сам.
        for name in ("organize", "convert", "check"):
            print(f"\n=== {name} ===")
            code = COMMANDS[name](rest if name == "check" else [])
        return code
    if cmd not in COMMANDS:
        print(f"Неизвестная команда «{cmd}». Доступны: {', '.join(COMMANDS)}, all")
        return 2
    return COMMANDS[cmd](rest)


if __name__ == "__main__":
    c.setup_stdout()
    sys.exit(main(sys.argv[1:]))
