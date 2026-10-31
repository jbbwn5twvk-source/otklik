"""Собирает заказы, обновляет docs/data/orders.json и шлёт новые в Telegram.

Запуск: python scraper/main.py
Переменные окружения (по желанию): TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GMAIL_USER, GMAIL_APP_PASSWORD
"""
import html
import json
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import KEEP_DAYS, TG_NOTIFY_MAX, TIME  # noqa: E402
from sources import hh, kwork, mail, telegram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
ORDERS = DATA / "orders.json"
STATE = DATA / "state.json"
MSK = timezone(timedelta(hours=3))
TOKEN, CHAT = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
SOURCES = {"Kwork": kwork.fetch, "hh.ru": hh.fetch, "Telegram": telegram.fetch}
E = html.escape


def load(p, default):
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return default


def tg(text):
    if not TOKEN or not CHAT:
        print("[bot]", text.replace("\n", " | ")[:300])
        return
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", timeout=30, json={
        "chat_id": CHAT, "text": text[:4000], "parse_mode": "HTML",
        "disable_web_page_preview": True})
    if not r.ok:
        print("Telegram error:", r.status_code, r.text[:300])


def estimate(cat):
    c, me = TIME.get(cat, (20, 60))
    return f"≈ {c + me} мин вместе: Claude ~{c} мин, вы ~{me} мин"


def money(o):
    if o.get("salary"):
        return o["salary"]
    if o.get("price"):
        s = f"{o['price']:,}".replace(",", " ") + " ₽"
        if o.get("price_max") and o["price_max"] > o["price"]:
            s += f" (допустимо до {o['price_max']:,} ₽)".replace(",", " ")
        return s
    return "цена не указана"


def order_msg(o):
    src = o["source"] + (f" · @{o['channel']}" if o.get("channel") else "")
    lines = [f"🆕 <b>{E(o['title'])}</b>",
             f"{E(src)} · {E(o['cat'])} · {E(money(o))}"]
    if o.get("offers") is not None:
        lines.append(f"Откликов: {o['offers']}")
    if o.get("text"):
        lines.append(E(o["text"][:500]))
    lines += [f"⏱ {estimate(o['cat'])}", f"🔗 {E(o['url'])}",
              "<i>Перешлите это сообщение Claude — напишем отклик.</i>"]
    return "\n".join(lines)


def mail_msg(m):
    lines = [f"{m['label']}: <b>{E(m['subject'])}</b>"]
    if m.get("preview"):
        lines.append(E(m["preview"]))
    if m.get("url"):
        lines.append(f"🔗 {E(m['url'])}")
    return "\n".join(lines)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    state = load(STATE, {"seen": [], "mails": [], "errors": {}, "started": False})
    old = {o["id"]: o for o in load(ORDERS, {"orders": []}).get("orders", [])}
    seen = set(state.get("seen", []))
    now = datetime.now(timezone.utc)
    fresh, status = [], {}

    for name, fn in SOURCES.items():
        try:
            got = fn()
            status[name] = f"ok ({len(got)})"
            fresh += got
            if state["errors"].pop(name, None):
                tg(f"✅ {name} снова работает.")
        except Exception as e:
            traceback.print_exc()
            status[name] = f"ошибка: {e}"[:200]
            if name not in state["errors"]:  # сообщаем об ошибке один раз, а не каждые 30 минут
                tg(f"⚠️ {name} сейчас не читается: {E(str(e)[:200])}\nПерешлите это Claude — поправим.")
            state["errors"][name] = str(e)[:200]

    fresh = list({o["id"]: o for o in fresh}.values())  # один пост может прийти дважды
    new = [o for o in fresh if o["id"] not in seen]
    for o in fresh:
        old[o["id"]] = {**old.get(o["id"], {}), **o, "found": old.get(o["id"], {}).get("found", now.isoformat())}

    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    orders = sorted((o for o in old.values() if o.get("found", "") >= cutoff),
                    key=lambda o: o.get("found", ""), reverse=True)

    if not state.get("started"):
        tg(f"✅ Лента подключена. Сейчас в ленте {len(orders)} заказов. "
           "Дальше буду присылать только новые.")
        state["started"] = True
    else:
        for o in new[:TG_NOTIFY_MAX]:
            tg(order_msg(o))
        if len(new) > TG_NOTIFY_MAX:
            tg(f"…и ещё {len(new) - TG_NOTIFY_MAX} новых заказов в ленте.")

    # Сообщения от заказчиков (Авито, Kwork) из почты
    mails_seen = set(state.get("mails", []))
    try:
        for m in mail.fetch(mails_seen):
            tg(mail_msg(m))
            mails_seen.add(m["mid"])
        status["Почта"] = "ok" if (os.getenv("MAIL_USER") or os.getenv("GMAIL_USER")) else "не подключена"
        if state["errors"].pop("Почта", None):
            tg("✅ Почта снова читается.")
    except Exception as e:
        traceback.print_exc()
        status["Почта"] = f"ошибка: {e}"[:200]
        if "Почта" not in state["errors"]:
            tg(f"⚠️ Не получилось прочитать почту: {E(str(e)[:200])}\n"
               "Проверьте MAIL_USER и MAIL_PASSWORD (пароль для внешнего приложения) в секретах.")
        state["errors"]["Почта"] = str(e)[:200]

    state["seen"] = list(seen | {o["id"] for o in fresh})[-5000:]
    state["mails"] = list(mails_seen)[-1000:]
    ORDERS.write_text(json.dumps({
        "updated": now.astimezone(MSK).strftime("%d.%m.%Y %H:%M"),
        "status": status, "orders": orders}, ensure_ascii=False, indent=1), "utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
    print("Готово:", status, "новых:", len(new))


if __name__ == "__main__":
    main()
