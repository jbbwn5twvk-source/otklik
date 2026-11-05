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


def main():
    seen = set(load(STATE, {}).get("seen", []))
    seen |= set(load(SEEN_FILE, []))  # что прислал прошлый сторож
    end = time.time() + config.WATCH_MINUTES * 60
    errors = 0
    print(f"Сторож запущен, проверка каждые {config.WATCH_EVERY} с")
    while time.time() < end:
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
