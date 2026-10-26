"""Журнал и предохранитель петли генерации (сама петля описана в .claude/skills/generation-loop).

Петля: сгенерировали -> проверили -> не пошло -> поправили запрос по замечанию -> повторили.
Скрипт не генерирует и не проверяет, он держит правила, которые нельзя оставлять на честное слово:

  * не больше 3 кругов на один кадр;
  * запрос второго и дальнейших кругов обязан отличаться от предыдущего и сопровождаться
    пояснением, что поменяли и в ответ на какое замечание (те же слова = отказ);
  * каждый круг пишется в журнал: что просили, что вернулось, почему не подошло;
  * после третьего неудачного круга (или замечания, которое запросом не лечится)
    печатается остановка с диагнозом: проблема в задании или данных, а не в генерации.

Команды (код возврата: 0 годен, 10 повторить, 20 остановка, 2 ошибка использования):

  start  --model AVT-CR --frame 1            -> печатает номер прогона
  round  RUN --prompt-file p.txt --file кандидат.jpg --verdict ok|fail
         [--generation-id ID] [--page-url URL] [--tokens N] [--size 1536x2752]
         [--defect "категория|пункт|что не так|как править запрос"] ...
         [--change "что поменяли в запросе и по какому замечанию"]
  status RUN
  report                                     -> пересобрать «Генерация/Журнал генераций.md»

Категории замечаний: тип-шлема, цвет, надписи, обрезка, положение, фон, форма, руки,
окружение, размер, баланс, прочее. Пункт — номер из таблицы проверок в «Генерация фото.md».
"""
import argparse
import difflib
import json
import shutil
import sys
from datetime import datetime

import common as c

MAX_ROUNDS = 3
RUNS = c.ROOT / "Генерация" / "Журнал"
JOURNAL_MD = c.ROOT / "Генерация" / "Журнал генераций.md"

CATEGORIES = ("тип-шлема", "цвет", "надписи", "обрезка", "положение", "фон", "форма",
              "руки", "окружение", "размер", "баланс", "прочее")
# Замечания, которые не лечатся правкой формулировки: повторять запрос бессмысленно.
NOT_PROMPTABLE = {"размер": "выбрана модель/размер генерации, не дающие 1536x2752 (нужен 2K+)",
                  "баланс": "не хватает токенов на генерацию"}
# Если замечание повторяется из круга в круг, виноват не запрос, а вот что.
ROOT_CAUSE = {
    "тип-шлема": "фото товара (Фото/<Артикул>.jpg) или строка {HELMET} в таблице моделей "
                 "(Генерация фото.md): они не однозначно задают тип шлема",
    "цвет": "фото товара или описание цвета в строке {HELMET}: цвет скорлупы задан неоднозначно",
    "форма": "фото товара как опорное изображение: форма шлема на нём читается неоднозначно "
             "(ракурс, тень, обрезка)",
    "надписи": "опорные изображения: надписи или логотипы есть на фото товара или в эталоне, "
               "и модель их переносит",
    "обрезка": "эталон кадра или зона видимости в Figma: шлем в заданном масштабе не помещается",
    "положение": "эталон сцены или допуски положения в «Генерация фото.md»: модель не удерживает "
                 "положение шлема по эталону, задание слишком жёсткое для этой модели",
    "фон": "эталон сцены или допуск по цвету фона (±12): для этой модели он нереалистичен",
    "окружение": "эталон сцены: сиденье/тень/руки не переносятся этой моделью по описанию",
    "руки": "кадр 4: модель не удерживает руки по эталону; нужен другой генератор или другой эталон",
    "прочее": "формулировка замечаний контролёра: не сведено к проверяемому пункту",
}


# ---------- хранение ----------

def run_path(run_id):
    return RUNS / f"{run_id}.json"


def load(run_id):
    p = run_path(run_id)
    if not p.exists():
        sys.exit(f"Прогон «{run_id}» не найден в {c.rel(RUNS)}")
    return json.loads(p.read_text(encoding="utf-8"))


def save(run):
    RUNS.mkdir(parents=True, exist_ok=True)
    run_path(run["id"]).write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    write_journal()


# ---------- журнал ----------

def write_journal():
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RUNS.glob("*.json"))]
    out = ["# Журнал генераций", "",
           "Собирается скриптом `scripts/loop.py`, вручную не правится. Один прогон = один кадр; "
           "в круге: что просили, что вернулось, почему не подошло. Предел — "
           f"{MAX_ROUNDS} круга.", ""]
    if not runs:
        out.append("Пока нет ни одного прогона.")
    for run in reversed(runs):
        out += [f"## {run['model']}, кадр {run['frame']} — {run['status_text']}",
                f"Прогон `{run['id']}`, начат {run['started']}.", ""]
        for r in run["rounds"]:
            out += [f"### Круг {r['n']} из {run['max_rounds']}: "
                    f"{'годен' if r['verdict'] == 'ok' else 'брак'}", "",
                    "**Что просили**",
                    f"- запрос: «{r['prompt'].strip()}»"]
            if r.get("change"):
                out.append(f"- что поменяли относительно круга {r['n'] - 1}: {r['change']}")
            out += ["", "**Что вернулось**",
                    f"- файл: `{r['file']}`" + (f", {r['size']}" if r.get("size") else ""),
                    f"- генерация: {r.get('generation_id') or '—'}"
                    + (f", [страница]({r['page_url']})" if r.get("page_url") else "")
                    + (f", списано токенов: {r['tokens']}" if r.get("tokens") is not None else "")]
            out.append("")
            if r["verdict"] == "ok":
                out += ["**Итог:** все проверки пройдены.", ""]
            else:
                out.append("**Почему не подошло**")
                for d in r["defects"]:
                    pt = f" (пункт {d['point']})" if d["point"] else ""
                    fix = f" Как править запрос: {d['fix']}" if d["fix"] else ""
                    out.append(f"- [{d['category']}]{pt} {d['what']}.{fix}")
                out.append("")
        if run.get("stop_message"):
            out += ["> " + line if line else ">" for line in run["stop_message"].splitlines()] + [""]
    JOURNAL_MD.write_text("\n".join(out) + "\n", encoding="utf-8")


# ---------- правила ----------

def parse_defect(text):
    parts = [p.strip() for p in text.split("|")]
    while len(parts) < 4:
        parts.append("")
    category, point, what, fix = parts[:4]
    if category not in CATEGORIES:
        sys.exit(f"Категория «{category}» не из списка: {', '.join(CATEGORIES)}")
    if point and not point.isdigit():
        sys.exit(f"Пункт должен быть числом, получено «{point}»")
    if not what:
        sys.exit("У замечания должно быть описание: что именно не так")
    return {"category": category, "point": int(point) if point else None, "what": what, "fix": fix}


def similarity(a, b):
    return difflib.SequenceMatcher(None, " ".join(a.split()), " ".join(b.split())).ratio()


def diagnose(run):
    """Текст остановки: почему петля не сошлась и где искать причину."""
    rounds = run["rounds"]
    lines = []
    blockers = {d["category"] for r in rounds[-1:] for d in r["defects"]} & set(NOT_PROMPTABLE)
    if blockers:
        lines.append(f"ОСТАНОВКА на круге {len(rounds)}: замечание не лечится правкой запроса.")
        for b in sorted(blockers):
            lines.append(f"- {b}: {NOT_PROMPTABLE[b]}.")
        lines.append("Проблема не в формулировке запроса и не в генерации: это условия запуска. "
                     "Снимите ограничение и запускайте заново.")
        return "\n".join(lines)

    lines.append(f"ОСТАНОВКА: {len(rounds)} круга(ов) подряд без годного кадра.")
    counts = {}
    for r in rounds:
        for cat in {d["category"] for d in r["defects"]}:
            counts[cat] = counts.get(cat, 0) + 1
    repeated = {cat: n for cat, n in counts.items() if n >= 2}
    if repeated:
        lines.append("Одно и то же замечание вернулось несколько раз, хотя запрос правили:")
        for cat, n in sorted(repeated.items(), key=lambda x: -x[1]):
            lines.append(f"- [{cat}] в {n} из {len(rounds)} кругов. Вероятная причина: {ROOT_CAUSE[cat]}.")
        lines.append("Вывод: проблема не в генерации, а в задании или данных. Менять формулировки "
                     "дальше бесполезно: проверьте перечисленное выше и запустите петлю заново.")
    else:
        lines.append("Замечания каждый круг новые: исправив одно, модель ломает другое.")
        lines.append("Вывод: проблема не в формулировке, а в самом задании: слишком много жёстких "
                     "условий для выбранной модели (либо модель нестабильна). Упростите задание "
                     "(эталон, допуски) или смените модель генерации.")
    return "\n".join(lines)


# ---------- команды ----------

def cmd_start(a):
    code = a.model.upper()
    if a.frame not in c.PHOTO_FRAMES:
        sys.exit("Генерируются кадры 1, 2 и 4. Кадр 3 — одно фото на все артикулы.")
    if not any(r["Артикул"].startswith(code + "-") for r in c.read_articles()):
        sys.exit(f"Модель {code} не найдена в Данные.csv")
    run_id = f"{code}_{a.frame}_{datetime.now():%Y%m%d-%H%M%S}"
    save({"id": run_id, "model": code, "frame": a.frame, "max_rounds": MAX_ROUNDS,
          "started": f"{datetime.now():%Y-%m-%d %H:%M}", "status": "идёт",
          "status_text": "идёт", "rounds": []})
    print(run_id)
    return 0


def cmd_round(a):
    run = load(a.run)
    if run["status"] != "идёт":
        print(f"Прогон уже завершён ({run['status_text']}). Новый круг не принимается; "
              "для повтора запустите новый прогон (start).")
        return 2
    n = len(run["rounds"]) + 1
    if n > run["max_rounds"]:
        print(f"Предел {run['max_rounds']} круга достигнут. Новый круг не принимается.")
        return 2

    prompt = open(a.prompt_file, encoding="utf-8").read()
    if not prompt.strip():
        print("Запрос пустой.")
        return 2
    defects = [parse_defect(d) for d in (a.defect or [])]
    if a.verdict == "fail" and not defects:
        print("Брак без замечаний не принимается: укажите, что именно не так (--defect).")
        return 2
    if a.verdict == "ok" and defects:
        print("Годный кадр не может нести замечаний.")
        return 2

    if n > 1:
        prev = run["rounds"][-1]
        sim = similarity(prompt, prev["prompt"])
        if sim >= 0.98:
            print(f"ОТКАЗ: запрос круга {n} совпадает с запросом круга {n - 1} "
                  f"(сходство {sim:.0%}). Повтор идёт с правкой по замечанию, а не теми же словами.")
            return 2
        if not a.change:
            print("ОТКАЗ: для повторного круга нужно --change: что поменяли в запросе "
                  "и в ответ на какое замечание.")
            return 2

    run["rounds"].append({
        "n": n, "prompt": prompt, "change": a.change, "file": c.rel(a.file),
        "size": a.size, "generation_id": a.generation_id, "page_url": a.page_url,
        "tokens": a.tokens, "verdict": a.verdict, "defects": defects,
        "time": f"{datetime.now():%H:%M:%S}"})

    if a.verdict == "ok":
        dst = c.PHOTOS / c.photo_name(run["model"], run["frame"])
        c.PHOTOS.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(a.file, dst)
        run["status"], run["status_text"] = "готово", f"годен с круга {n}"
        save(run)
        print(f"РЕШЕНИЕ: ГОДЕН (круг {n}). Кадр сохранён: {c.rel(dst)}")
        return 0

    stop_early = any(d["category"] in NOT_PROMPTABLE for d in defects)
    if n >= run["max_rounds"] or stop_early:
        msg = diagnose(run)
        run["status"] = "остановлен"
        run["status_text"] = f"остановлен на круге {n}: не сошлось"
        run["stop_message"] = msg
        save(run)
        print(f"РЕШЕНИЕ: СТОП\n{msg}")
        return 20

    save(run)
    print(f"РЕШЕНИЕ: ПОВТОРИТЬ (круг {n + 1} из {run['max_rounds']}). Замечания для правки запроса:")
    for d in defects:
        pt = f", пункт {d['point']}" if d["point"] else ""
        print(f"- [{d['category']}{pt}] {d['what']}" + (f" -> {d['fix']}" if d["fix"] else ""))
    print("Запрос следующего круга должен отличаться и отвечать на эти замечания.")
    return 10


def cmd_status(a):
    run = load(a.run)
    print(f"{run['id']}: {run['status_text']}, кругов {len(run['rounds'])} из {run['max_rounds']}")
    if run.get("stop_message"):
        print(run["stop_message"])
    return 0


def cmd_report(a):
    write_journal()
    print(f"Журнал пересобран: {c.rel(JOURNAL_MD)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("--model", required=True)
    s.add_argument("--frame", type=int, required=True)
    s.set_defaults(fn=cmd_start)
    r = sub.add_parser("round")
    r.add_argument("run")
    r.add_argument("--prompt-file", required=True)
    r.add_argument("--file", required=True, help="кандидат-кадр этого круга")
    r.add_argument("--verdict", choices=("ok", "fail"), required=True)
    r.add_argument("--defect", action="append", help="категория|пункт|что не так|как править запрос")
    r.add_argument("--change")
    r.add_argument("--generation-id")
    r.add_argument("--page-url")
    r.add_argument("--tokens", type=int)
    r.add_argument("--size")
    r.set_defaults(fn=cmd_round)
    t = sub.add_parser("status")
    t.add_argument("run")
    t.set_defaults(fn=cmd_status)
    sub.add_parser("report").set_defaults(fn=cmd_report)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    c.setup_stdout()
    sys.exit(main())
