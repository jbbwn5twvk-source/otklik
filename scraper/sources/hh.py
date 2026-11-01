"""hh.ru: HTML-поиск вакансий (удалёнка, частичная и проектная занятость)."""
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from common import S, category, clean
from config import HH_QUERIES


def fetch():
    out, seen = [], set()
    for q in HH_QUERIES:
        params = [("text", q), ("search_field", "name"), ("schedule", "remote"),
                  ("employment", "part"), ("employment", "project"),
                  ("order_by", "publication_time"), ("search_period", "1"),
                  ("items_on_page", "50")]
        r = S.get("https://hh.ru/search/vacancy", params=params, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select('[data-qa="serp-item__title"]'):
            href = a.get("href") or (a.find_parent("a") or {}).get("href", "")
            m = re.search(r"/vacancy/(\d+)", href or "")
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            title = a.get_text(" ", strip=True)
            card = a.find_parent(attrs={"data-qa": re.compile("vacancy-serp__vacancy")}) or a.parent
            salary = card.find(attrs={"data-qa": re.compile("compensation")}) if card else None
            company = card.find(attrs={"data-qa": re.compile("employer")}) if card else None
            out.append({
                "id": f"hh-{m.group(1)}",
                "source": "hh.ru",
                "title": title,
                "text": clean(company.get_text(" ", strip=True) if company else ""),
                "price": 0,
                "salary": salary.get_text(" ", strip=True) if salary else "",
                "url": f"https://hh.ru/vacancy/{m.group(1)}",
                "cat": category(title) or "Другое",
                # hh не показывает время публикации в поиске: берём момент, когда вакансия
                # впервые появилась в выдаче (поиск отсортирован по дате и ограничен сутками)
                "date": datetime.now(timezone.utc).isoformat(),
            })
    return out
