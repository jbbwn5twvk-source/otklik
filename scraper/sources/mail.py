"""Уведомления о сообщениях заказчиков (Авито, Kwork) из писем на почте.

Работает, только если в GitHub Secrets заданы MAIL_USER и MAIL_PASSWORD
(пароль для внешнего приложения, не обычный пароль). Подходят Mail.ru (и inbox/list/bk),
Яндекс и Gmail; старые имена GMAIL_USER / GMAIL_APP_PASSWORD тоже работают. Письма открываются только для чтения
и не помечаются прочитанными; читаются только письма от отправителей из MAIL_SENDERS.
"""
import email
import imaplib
import os
import re
from datetime import datetime, timedelta
from email.header import decode_header, make_header

from common import clean
from config import MAIL_SENDERS, MAIL_SUBJECT

_SUBJ = re.compile(MAIL_SUBJECT, re.I)
_LINK = re.compile(r"https://(?:www\.|m\.)?(?:avito\.ru|kwork\.ru)/[^\s\"'<>]+", re.I)


def _host(user):
    domain = user.split("@")[-1].lower()
    if domain in ("mail.ru", "inbox.ru", "list.ru", "bk.ru", "internet.ru", "my.com"):
        return "imap.mail.ru"
    if domain in ("yandex.ru", "ya.ru", "yandex.com"):
        return "imap.yandex.ru"
    return "imap.gmail.com"


def _h(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _body(msg):
    plain, html = "", ""
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        try:
            text = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if ctype == "text/plain" and not plain:
            plain = text
        elif ctype == "text/html" and not html:
            html = text
    return plain or html


def fetch(seen_ids):
    user = os.getenv("MAIL_USER") or os.getenv("GMAIL_USER")
    pwd = os.getenv("MAIL_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        return []
    since = (datetime.utcnow() - timedelta(days=2)).strftime("%d-%b-%Y")
    box = imaplib.IMAP4_SSL(_host(user))
    box.login(user, pwd)
    box.select("INBOX", readonly=True)
    out = []
    for domain, label in MAIL_SENDERS.items():
        _, data = box.search(None, f'(FROM "{domain}" SINCE {since})')
        for num in data[0].split()[-30:]:
            _, msg_data = box.fetch(num, "(BODY.PEEK[])")
            msg = email.message_from_bytes(msg_data[0][1])
            mid = msg.get("Message-ID") or f"{domain}-{num.decode()}"
            subj = _h(msg.get("Subject"))
            if mid in seen_ids or not _SUBJ.search(subj):
                continue
            body = _body(msg)
            links = [u for u in _LINK.findall(body) if "unsubscribe" not in u.lower()]
            out.append({"mid": mid, "label": label, "subject": subj,
                        "preview": clean(body, 300), "url": links[0] if links else ""})
    box.logout()
    return out
