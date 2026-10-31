"""Открытые Telegram-каналы через веб-версию t.me/s/<канал>."""
import re

from bs4 import BeautifulSoup

from common import S, category, clean
from config import TG_CHANNELS, TG_REMOTE

_REMOTE = re.compile(TG_REMOTE, re.I)
_PRICE = re.compile(r"(\d[\d\s]{2,7})\s*(?:₽|руб|р\.|rub)", re.I)


def fetch():
    out, errors = [], []
    for ch in TG_CHANNELS:
        try:
            r = S.get(f"https://t.me/s/{ch}", timeout=30)
            r.raise_for_status()
        except Exception as e:  # один канал не должен ломать остальные
            errors.append(f"{ch}: {e}")
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for msg in soup.select(".tgme_widget_message"):
            post = msg.get("data-post")
            body_el = msg.select_one(".tgme_widget_message_text")
            if not post or not body_el:
                continue
            text = body_el.get_text("\n", strip=True)
            lines = [ln for ln in text.split("\n") if ln.strip()]
            title = lines[0][:150] if lines else ""
            head = " ".join(lines[:2])
            cat = category(title, title_only=True)
            if not cat or not _REMOTE.search(text[:400]):
                continue
            t = msg.select_one("time[datetime]")
            pm = _PRICE.search(text)
            out.append({
                "id": f"tg-{post}",
                "source": "Telegram",
                "channel": ch,
                "title": head[:150],
                "text": clean(text),
                "price": int(re.sub(r"\D", "", pm.group(1))) if pm else 0,
                "url": f"https://t.me/{post}",
                "cat": cat,
                "date": t["datetime"] if t else "",
            })
    if errors and not out:
        raise RuntimeError("; ".join(errors[:3]))
    return out
