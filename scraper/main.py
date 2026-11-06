"""Собирает заказы, обновляет docs/data/orders.json и шлёт новые в Telegram.

Запуск: python scraper/main.py
Переменные окружения (по желанию): TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, GMAIL_USER, GMAIL_APP_PASSWORD
"""
import html
import json
import re
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import (BOTS, BOTS_NO, DRAFTS_ENABLED, HOT, LEADS, HOT_CATS, KEEP_DAYS, MAIL_ENABLED, MAX_AGE_HOURS,  # noqa: E402
                    MAX_OFFERS, TG_NOTIFY_MAX, TIME, WATCH_ENABLED)
from common import blocked  # noqa: E402
from drafts import draft  # noqa: E402
from sources import boards, hh, kwork, mail, telegram  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
ORDERS = DATA / "orders.json"
STATE = DATA / "state.json"
MSK = timezone(timedelta(hours=3))
TOKEN, CHAT = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
SOURCES = {"Kwork": kwork.fetch, "hh.ru": hh.fetch, "Telegram": telegram.fetch,
           "Weblancer": boards.weblancer, "Фриланс.ру": boards.freelance_ru}
E = html.escape
_HOT = re.compile(HOT, re.I)
_BOTS = re.compile(BOTS, re.I)
_BOTS_NO = re.compile(BOTS_NO, re.I)
_LEADS = re.compile(LEADS, re.I)


def is_lead(o):
    """Прямая заявка: «нужен сайт», «ищу, кто сделает бота»."""
    return bool(_LEADS.search(o.get("title", "") + " " + o.get("text", "")[:300]))


def is_bot(o):
    return bool(_BOTS.search(o.get("title", "")))


def is_max_bot(o):
    """Бот для мессенджера Max — не берём (Max может быть упомянут только в описании)."""
    return is_bot(o) and bool(_BOTS_NO.search(o.get("title", "") + " " + o.get("text", "")))


def is_hot(o):
    if is_max_bot(o):
        return False
    return (o.get("cat") in HOT_CATS or bool(_HOT.search(o.get("title", "")))
            or is_bot(o) or is_lead(o))


def age_hours(o, now):
    try:
        d = datetime.fromisoformat(o.get("date", "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return (now - d).total_seconds() / 3600


def skip_reason(o, now):
    """Почему заказ не надо присылать в бот (None — присылать)."""
    if is_max_bot(o):
        return "бот для Max"
    a = age_hours(o, now)
    if a is None or a > MAX_AGE_HOURS:
        return "старый"
    if o.get("offers") is not None and o["offers"] > MAX_OFFERS:
        return "много откликов"
    return None


def watcher_running():
    """Работает ли сейчас сторож (watch.yml) — спрашиваем у GitHub."""
    repo = os.getenv("GITHUB_REPOSITORY")
    if not (WATCH_ENABLED and repo):
        return False
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/actions/workflows/watch.yml/runs",
                         params={"status": "in_progress", "per_page": 1}, timeout=20,
                         headers={"Authorization": f"Bearer {os.getenv('GITHUB_TOKEN', '')}"})
        return r.ok and r.json().get("total_count", 0) > 0
    except Exception:
        return False


WATCHING = None


def watched(o):
    """Приоритетные заказы Kwork мгновенно присылает сторож (watch.py) — здесь их не дублируем.
    Если сторож не запущен, присылаем их как обычно."""
    global WATCHING
    if not (o.get("source") == "Kwork" and is_hot(o)):
        return False
    if WATCHING is None:
        WATCHING = watcher_running()
        print("Сторож работает:", WATCHING)
    return WATCHING


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
    head = "🔥 <b>ПРИОРИТЕТ</b> · " if is_hot(o) else "🆕 "
    if is_lead(o) and is_hot(o):
        head += "🎯 <b>ЗАЯВКА</b> · "
    lines = [f"{head}<b>{E(o['title'])}</b>",
             f"{E(src)} · {E(o['cat'])} · {E(money(o))}"]
    if o.get("offers") is not None:
        lines.append(f"Откликов: {o['offers']}")
    if o.get("text"):
        lines.append(E(o["text"][:500]))
    lines += [f"⏱ {estimate(o['cat'])}", f"🔗 {E(o['url'])}"]
    d = draft(o, lead=is_lead(o) and o.get("source") == "Telegram") if DRAFTS_ENABLED and is_hot(o) else ""
    if d:
        lines += ["✍️ Черновик (нажмите, чтобы скопировать):", f"<pre>{E(d)}</pre>",
                  "<i>Сложный заказ? Перешлите его Claude.</i>"]
    else:
        lines.append("<i>Перешлите это сообщение Claude — напишем отклик.</i>")
    return "\n".join(lines)


def mail_msg(m):
    lines = [f"{m['label']}: <b>{E(m['subject'])}</b>"]
    if m.get("preview"):
        lines.append(E(m["preview"]))
    if m.get("url"):
        lines.append(f"🔗 {E(m['url'])}")
    return "\n".join(lines)


def weekly(state, orders, now):
    """Воскресенье после 19:00 по Москве: сводка за 7 дней, один раз в неделю."""
    msk = now.astimezone(MSK)
    week = msk.strftime("%G-%V")
    if msk.weekday() != 6 or msk.hour < 19 or state.get("weekly") == week:
        return
    since = (now - timedelta(days=7)).isoformat()
    last = [o for o in orders if o.get("found", "") >= since]
    by, hot = {}, {}
    for o in last:
        by[o["source"]] = by.get(o["source"], 0) + 1
        if is_hot(o):
            hot[o["source"]] = hot.get(o["source"], 0) + 1
    rows = "\n".join(f"• {E(k)}: {v} (приоритетных {hot.get(k, 0)})"
                      for k, v in sorted(by.items(), key=lambda x: -x[1]))
    tg(f"📊 <b>Неделя в ленте</b>. Заказов: {len(last)}, из них приоритетных: {sum(hot.values())}.\n{rows}\n"
       "<i>Источник, где неделями нет приоритетных, можно убрать. Перешлите Claude, если что-то поменять.</i>")
    state["weekly"] = week


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
            if name == "Telegram" and telegram.last_errors:
                status[name] += f", не прочитано каналов: {len(telegram.last_errors)}"
                print("Telegram:", telegram.last_errors)
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
    fresh = [o for o in fresh if not blocked(o.get("title", ""), o.get("text", ""))]
    new = [o for o in fresh if o["id"] not in seen]
    # Новый источник: в первый раз всё, что уже лежит на бирже, только запоминаем, а не шлём пачкой
    known = set(state.get("sources", []))
    if state.get("started"):
        first = {o["source"] for o in fresh} - known - {"Kwork", "hh.ru", "Telegram", "Почта"}
        new = [o for o in new if o["source"] not in first]
        if first:
            print("Новые источники, запоминаю без отправки:", first)
    state["sources"] = sorted(known | {o["source"] for o in fresh})
    for o in fresh:
        old[o["id"]] = {**old.get(o["id"], {}), **o, "found": old.get(o["id"], {}).get("found", now.isoformat())}

    cutoff = (now - timedelta(days=KEEP_DAYS)).isoformat()
    orders = sorted((o for o in old.values() if o.get("found", "") >= cutoff
                     and not blocked(o.get("title", ""), o.get("text", ""))),
                    key=lambda o: o.get("found", ""), reverse=True)

    if not state.get("started"):
        tg(f"✅ Лента подключена. Сейчас в ленте {len(orders)} заказов. "
           "Дальше буду присылать только новые.")
        state["started"] = True
    else:
        send, skipped = [], {}
        for o in new:
            why = "у сторожа" if watched(o) else skip_reason(o, now)
            if why:
                skipped[why] = skipped.get(why, 0) + 1
            else:
                send.append(o)
        print("Не отправлено в бот:", skipped)
        # Приоритетные первыми и без лимита, остальные — свежие сверху, в пределах лимита.
        # Раньше лимит съедали hh и Kwork, и до Telegram очередь не доходила.
        hot = [o for o in send if is_hot(o)]
        rest = sorted((o for o in send if not is_hot(o)), key=lambda o: o.get("date", ""), reverse=True)
        for o in hot + rest[:TG_NOTIFY_MAX]:
            tg(order_msg(o))
        if len(rest) > TG_NOTIFY_MAX:
            tg(f"…и ещё {len(rest) - TG_NOTIFY_MAX} новых заказов в ленте.")

    # Сообщения от заказчиков (Авито, Kwork) из почты
    mails_seen = set(state.get("mails", []))
    try:
        for m in (mail.fetch(mails_seen) if MAIL_ENABLED else []):
            tg(mail_msg(m))
            mails_seen.add(m["mid"])
        status["Почта"] = ("на паузе" if not MAIL_ENABLED else
                           "ok" if (os.getenv("MAIL_USER") or os.getenv("GMAIL_USER")) else "не подключена")
        if state["errors"].pop("Почта", None):
            tg("✅ Почта снова читается.")
    except Exception as e:
        traceback.print_exc()
        status["Почта"] = f"ошибка: {e}"[:200]
        if "Почта" not in state["errors"]:
            tg(f"⚠️ Не получилось прочитать почту: {E(str(e)[:200])}\n"
               "Проверьте MAIL_USER и MAIL_PASSWORD (пароль для внешнего приложения) в секретах.")
        state["errors"]["Почта"] = str(e)[:200]

    weekly(state, orders, now)
    state["seen"] = list(seen | {o["id"] for o in fresh})[-5000:]
    state["mails"] = list(mails_seen)[-1000:]
    ORDERS.write_text(json.dumps({
        "updated": now.astimezone(MSK).strftime("%d.%m.%Y %H:%M"),
        "status": status, "orders": orders}, ensure_ascii=False, indent=1), "utf-8")
    STATE.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
    print("Готово:", status, "новых:", len(new))


if __name__ == "__main__":
    main()
