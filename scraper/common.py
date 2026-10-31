import html
import re

import requests

from config import CATS, STOP

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "ru-RU,ru;q=0.9"})

_CATS = {k: re.compile(v, re.I) for k, v in CATS.items()}
_STOP = re.compile(STOP, re.I)


def category(title, body="", title_only=False):
    """Категория заказа или None, если не подходит."""
    if _STOP.search(title or ""):
        return None
    for name, rx in _CATS.items():
        if rx.search(title or ""):
            return name
    if title_only:
        return None
    for name, rx in _CATS.items():
        if rx.search(body or ""):
            return name
    return None


def clean(text, n=600):
    text = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:n] + ("…" if len(text) > n else "")
