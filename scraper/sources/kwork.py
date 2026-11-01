"""Kwork: открытая биржа проектов (без входа)."""
from datetime import datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))

from common import S, category, clean
from config import KWORK_MAX_PRICE, KWORK_PAGES


def _price(v):
    try:
        return int(float(v or 0))
    except (TypeError, ValueError):
        return 0


def fetch():
    out = []
    for page in range(1, KWORK_PAGES + 1):
        r = S.post("https://kwork.ru/projects", data={"page": page, "c": "all"}, timeout=30,
                   headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json",
                            "Referer": "https://kwork.ru/projects"})
        r.raise_for_status()
        items = (((r.json().get("data") or {}).get("pagination") or {}).get("data")) or []
        if not items:
            break
        for it in items:
            title, body = it.get("name", ""), clean(it.get("description", ""))
            cat = category(title, body)
            price = _price(it.get("priceLimit"))
            if not cat or (KWORK_MAX_PRICE and price > KWORK_MAX_PRICE):
                continue
            created = it.get("date_create") or ""
            try:
                created = datetime.strptime(created, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=MSK).astimezone(timezone.utc).isoformat()  # Kwork отдаёт московское время
            except ValueError:
                created = datetime.now(timezone.utc).isoformat()
            out.append({
                "id": f"kwork-{it.get('id')}",
                "source": "Kwork",
                "title": title,
                "text": body,
                "price": price,
                "price_max": _price(it.get("possiblePriceLimit")),
                "offers": it.get("kwork_count"),
                "url": f"https://kwork.ru/projects/{it.get('id')}/view",
                "cat": cat,
                "date": created,
            })
    return out
