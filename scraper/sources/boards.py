"""Ещё две биржи без платной подписки для чтения: Weblancer и Фриланс.ру (только задания «Видно всем»).

Обе отдают обычный HTML, вход не нужен. Отклики: на Weblancer есть бесплатные заявки,
на Фриланс.ру берём только задания, на которые может откликнуться любой (не «Только для премиум»).
"""
import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from common import S, blocked, category, clean

MSK = timezone(timedelta(hours=3))

# Типичные «работы на дому» без реальной задачи: на биржах их много, нам они не нужны
SPAM = re.compile(r"без опыта|на дому|из дома|выкладк|размещ\w* объявлен|заполн\w* анкет|"
                  r"ежедневн\w* оплат|выкупить товар|напиш\w* отзыв|пора пробовать|твой шанс|"
                  r"оператор чата|модератор чат", re.I)


def _num(s):
    m = re.search(r"\d[\d\s]*", s or "")
    return int(re.sub(r"\s", "", m.group())) if m else None


def _item(id_, source, title, text, url, date, offers, price=0, salary=""):
    if blocked(title) or SPAM.search(title + " " + text):
        return None
    return {"id": id_, "source": source, "title": title, "text": clean(text),
            "price": price, "salary": salary, "url": url, "offers": offers,
            "cat": category(title, text) or "Другое", "date": date}


def weblancer():
    """Weblancer: первые 2 страницы ленты. На карточке только дата без времени,
    поэтому берём заказы за сегодня, а временем считаем момент, когда бот их увидел."""
    out = []
    today = datetime.now(MSK).strftime("%d.%m.%Y")
    for page in (1, 2):
        r = S.get("https://www.weblancer.net/freelance/", params={"page": page}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("h2 a[href^='/freelance/']"):
            m = re.search(r"-(\d+)/?$", a.get("href", ""))
            card = a.find_parent("div", class_=re.compile("space-y-3"))
            if not m or not card:
                continue
            spans = [s.get_text(" ", strip=True) for s in card.select("span")]
            day = next((s for s in spans if re.fullmatch(r"\d\d\.\d\d\.\d{4}", s)), "")
            if day != today:
                continue
            offers = next((_num(s) for s in spans if "заяв" in s), 0)
            p = card.find("p")
            price_el = card.select_one("span.text-green-600")
            it = _item(f"weblancer-{m.group(1)}", "Weblancer", a.get_text(" ", strip=True),
                       p.get_text(" ", strip=True) if p else "",
                       "https://www.weblancer.net" + a["href"],
                       datetime.now(timezone.utc).isoformat(), offers,
                       salary=price_el.get_text("", strip=True).replace("$", " $") if price_el else "")
            if it:
                out.append(it)
    return out


def freelance_ru():
    """Фриланс.ру: веб-разработка, дизайн, ИИ; только «Видно всем» (a=1)."""
    out = []
    r = S.get("https://freelance.ru/task",
              params=[("c[]", "4"), ("c[]", "40"), ("c[]", "724"), ("a", "1")], timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for card in soup.select("article.task-card"):
        a = card.select_one(".task-card__title-link")
        if not a or "task-badge--all" not in str(card.select_one(".task-card__badges") or ""):
            continue
        m = re.search(r"/task/view/(\d+)", a.get("href", ""))
        when = card.select_one(".task-card__foot-item[title]")
        try:
            date = datetime.strptime(when["title"], "%d.%m.%Y %H:%M").replace(
                tzinfo=MSK).astimezone(timezone.utc).isoformat()
        except Exception:
            continue
        com = card.select_one(".fa-comments")
        offers = _num(com.parent.get_text()) if com else None
        budget = card.select_one(".task-card__budget")
        btxt = budget.get_text(" ", strip=True) if budget else ""
        price = _num(btxt) if "₽" in btxt else 0
        desc = card.select_one(".task-card__desc")
        it = _item(f"freelanceru-{m.group(1)}" if m else a["href"], "Фриланс.ру",
                   a.get_text(" ", strip=True), desc.get_text(" ", strip=True) if desc else "",
                   "https://freelance.ru" + a["href"], date, offers, price=price or 0)
        if it:
            out.append(it)
    return out
