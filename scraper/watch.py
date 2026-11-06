"""Сторож: каждые WATCH_EVERY секунд проверяет первую страницу Kwork и сразу присылает
в бот новые приоритетные заказы (презентации, дизайн, контент/SMM,
боты для Telegram и ВК, парсеры). Боты для Max не присылаются.

Работает внутри одного запуска GitHub Actions до WATCH_MINUTES минут, потом его сменяет
следующий запуск. Остальные заказы по-прежнему приходят из main.py по расписанию.

Запуск: python scraper/watch.py
"""
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config  # noqa: E402
from common import blocked  # noqa: E402
from main import STATE, age_hours, is_hot, load, order_msg, skip_reason, tg  # noqa: E402
from sources import kwork  # noqa: E402

SEEN_FILE = Path(__file__).parent / ".watch_seen.json"


def check(seen):
    now = datetime.now(timezone.utc)
    sent = 0
    for o in kwork.fetch(pages=1):
        if o["id"] in seen:
            continue
        seen.add(o["id"])
        if not is_hot(o) or blocked(o["title"]) or skip_reason(o, now):
            continue
        a = age_hours(o, now)
        if a is not None and a * 60 > config.WATCH_FRESH_MIN:
            continue  # старше нескольких минут — его уже прислал обычный запуск
        tg(order_msg(o).replace("🔥 <b>ПРИОРИТЕТ</b>", "⚡ <b>СРОЧНО</b> · 🔥 <b>ПРИОРИТЕТ</b>", 1))
        sent += 1
    return sent


CODE_PATHS = ("scraper/", ".github/workflows/watch.yml", "requirements.txt")


def code_changed():
    """True, если после запуска этого сторожа в main залили новый код бота.
    Тогда сторож запускает свою свежую копию и выходит, чтобы правки начали работать сразу."""
    import os
    import requests
    repo, sha, tok = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_SHA"), os.getenv("GITHUB_TOKEN")
    if not (repo and sha and tok):
        return False
    h = {"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"https://api.github.com/repos/{repo}/compare/{sha}...main", headers=h, timeout=30)
    if not r.ok:
        return False
    files = [f["filename"] for f in r.json().get("files", [])]
    if not any(f.startswith(CODE_PATHS) and not f.endswith(".watch_seen.json") for f in files):
        return False
    d = requests.post(f"https://api.github.com/repos/{repo}/actions/workflows/watch.yml/dispatches",
                      headers=h, json={"ref": "main"}, timeout=30)
    print("Код обновился, перезапускаю сторожа:", d.status_code)
    return d.status_code == 204


def main():
    seen = set(load(STATE, {}).get("seen", []))
    seen |= set(load(SEEN_FILE, []))  # что прислал прошлый сторож
    end = time.time() + config.WATCH_MINUTES * 60
    errors = 0
    next_code_check = time.time() + 600
    print(f"Сторож запущен, проверка каждые {config.WATCH_EVERY} с")
    while time.time() < end:
        if time.time() >= next_code_check:
            next_code_check = time.time() + 600
            try:
                if code_changed():
                    break
            except Exception:
                traceback.print_exc()
        try:
            n = check(seen)
            if n:
                print(datetime.now().strftime("%H:%M:%S"), "отправлено:", n)
            errors = 0
        except Exception:
            errors += 1
            traceback.print_exc()
            if errors == 10:  # ~15 минут подряд не читается — сообщаем один раз
                tg("⚠️ Сторож не может прочитать Kwork уже несколько минут. "
                   "Срочные заказы придут с обычным обновлением. Перешлите это Claude.")
        SEEN_FILE.write_text(json.dumps(sorted(seen)[-3000:]))
        time.sleep(config.WATCH_EVERY)
    # Сохраняем, что уже видели, чтобы следующий сторож не прислал повторно
    SEEN_FILE.write_text(json.dumps(sorted(seen)[-3000:]))


if __name__ == "__main__":
    main()
