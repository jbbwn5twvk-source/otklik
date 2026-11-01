"""Открытые Telegram-каналы через веб-версию t.me/s/<канал>."""
import re

from bs4 import BeautifulSoup

from common import S, category, clean
from config import TG_CHANNELS, TG_HEAD_LINES, TG_REMOTE

_REMOTE = re.compile(TG_REMOTE, re.I)
_PRICE = re.compile(r"(\d[\d\s]{2,7})\s*(?:₽|руб|р\.|rub)", re.I)
_JUNK = re.compile(r"^[\W\d_#@]*$")  # строки из одних эмодзи, хэштегов и знаков

# Сколько каналов не прочиталось в последнем запуске (main.py показывает в статусе)
last_errors = []


def _lines(text):
    out = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if ln and not _JUNK.match(ln):
            out.append(ln)
    return out


def fetch():
    out = []
    last_errors.clear()
    for ch in TG_CHANNELS:
        try:
            r = S.get(f"https://t.me/s/{ch}", timeout=30)
            r.raise_for_status()
        except Exception as e:  # один канал не должен ломать остальные
            last_errors.append(f"{ch}: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        msgs = soup.select(".tgme_widget_message")
        if not msgs:
            last_errors.append(f"{ch}: пустая страница")
            continue
        for msg in msgs:
            post = msg.get("data-post")
            body_el = msg.select_one(".tgme_widget_message_text")
            if not post or not body_el:
                continue
            text = body_el.get_text("\n", strip=True)
            lines = _lines(text)
            if not lines:
                continue
            head = " ".join(lines[:TG_HEAD_LINES])
            # Раньше категорию искали только в первой строке, а она часто «#вакансия» или эмодзи —
            # поэтому почти все посты отсеивались. Теперь смотрим первые строки.
            cat = category(head[:400], title_only=True)
            if not cat or not _REMOTE.search(text[:1500]):
                continue
            t = msg.select_one("time[datetime]")
            pm = _PRICE.search(text)
            out.append({
                "id": f"tg-{post}",
                "source": "Telegram",
                "channel": ch,
                "title": " ".join(lines[:2])[:150],
                "text": clean(text),
                "price": int(re.sub(r"\D", "", pm.group(1))) if pm else 0,
                "url": f"https://t.me/{post}",
                "cat": cat,
                "date": t["datetime"] if t else "",
            })
    if last_errors and not out:
        raise RuntimeError("; ".join(last_errors[:3]))
    return out
