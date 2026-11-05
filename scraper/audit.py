"""Аудит сайтов: кому из найденных компаний нужен новый сайт и что именно у них плохо.

Список берётся из переменной SITES (запуск из GitHub Actions) или из файла scraper/sites.txt.
Одна компания на строку, можно через «;»:
    Салон «Лаванда» | lavanda-salon.ru
    Кофейня у дома | нет            ← сайта нет совсем
    https://example.ru

Сайты только читаются, как в обычном браузере, ничего не отправляется.
Результат: сообщения в Telegram-бот (сначала те, кому сайт нужнее всего) и файл audit_report.html.

Запуск: python scraper/audit.py
"""
import html
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import S  # noqa: E402

E = html.escape
YEAR = datetime.now().year
NO_SITE = {"", "нет", "-", "—", "no", "none", "нет сайта"}

BUILDERS = {
    "Tilda": r"tilda\.ws|tildacdn|data-tilda",
    "Wix": r"wix\.com|wixstatic|_wixCssImports",
    "WordPress": r"wp-content|wp-includes",
    "1С-Битрикс": r"/bitrix/|bx-core",
    "uKit": r"ukit\.com|ukit-",
    "Nethouse": r"nethouse",
    "Craftum": r"craftum",
    "Taplink": r"taplink",
}
BOOKING = r"yclients|dikidi|онлайн.?запис|записаться|запись онлайн|забронир|оставить заявку|заказать звонок|<form"
PRICES = r"прайс|цены|стоимость|₽|руб\.?\b|от \d+ ?р"


def parse(raw):
    """Строки «Название | сайт» → список (название, сайт)."""
    out = []
    for line in re.split(r"[\n;]+", raw or ""):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "|" in line:
            name, site = [x.strip() for x in line.split("|", 1)]
        elif re.search(r"\.[a-zа-я]{2,}(/|$)", line, re.I):
            name, site = "", line
        else:
            name, site = line, ""
        out.append((name, site))
    return out


def check(name, site):
    r = {"name": name, "site": site, "problems": [], "good": [], "score": 0}

    def bad(points, text):
        r["score"] += points
        r["problems"].append(text)

    if site.lower() in NO_SITE:
        bad(10, "сайта нет совсем, клиенты видят только карточку на картах")
        return r
    url = site if re.match(r"https?://", site, re.I) else "http://" + site
    if re.search(r"taplink|vk\.com|t\.me|instagram", url, re.I):
        bad(6, "вместо сайта ссылка на соцсеть или таплинк")
    try:
        t0 = time.time()
        resp = S.get(url, timeout=25, allow_redirects=True)
        sec = time.time() - t0
    except Exception as e:
        bad(9, f"сайт не открывается ({type(e).__name__})")
        return r
    if resp.status_code >= 400:
        bad(9, f"сайт отвечает ошибкой {resp.status_code}")
        return r
    page = resp.text or ""
    low = page.lower()
    r["final"] = resp.url

    if not resp.url.lower().startswith("https://"):
        bad(3, "нет защищённого соединения (https), браузер пишет «Не защищено»")
    if 'name="viewport"' not in low and "name='viewport'" not in low:
        bad(4, "не адаптирован под телефон, на мобильном всё мелкое")
    else:
        r["good"].append("есть мобильная версия")
    if sec > 4:
        bad(2, f"долго грузится ({sec:.0f} с)")
    if len(page) > 3_000_000:
        bad(1, "очень тяжёлая страница")

    years = [int(y) for y in re.findall(r"(?:©|&copy;|copyright)[^<]{0,30}?(20\d\d)", page, re.I)]
    if years and max(years) <= YEAR - 3:
        bad(3, f"в подвале стоит {max(years)} год, сайт давно не обновляли")

    title = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    if not title or len(title.group(1).strip()) < 5:
        bad(1, "у страницы нет нормального заголовка, хуже ищется в Яндексе")
    if 'name="description"' not in low and "name='description'" not in low:
        bad(1, "нет описания для поисковиков")

    if not re.search(BOOKING, low):
        bad(3, "нельзя записаться или оставить заявку с сайта, только звонить")
    else:
        r["good"].append("есть заявка или запись")
    if not re.search(PRICES, low):
        bad(2, "на сайте не видно цен")
    if not re.search(r'href="(tel:|https?://(wa\.me|api\.whatsapp|t\.me|vk\.com))', low):
        bad(2, "нет кнопок «позвонить» или «написать в мессенджер»")
    if len(re.sub(r"<[^>]+>", " ", low).split()) < 80:
        bad(2, "на сайте почти нет текста")

    for b, rx in BUILDERS.items():
        if re.search(rx, page, re.I):
            r["builder"] = b
            break
    return r


def verdict(score):
    if score >= 9:
        return "🔴 Нужен сайт"
    if score >= 5:
        return "🟠 Сайт слабый"
    if score >= 2:
        return "🟡 Есть что улучшить"
    return "🟢 Сайт нормальный"


# Как проблема звучит для владельца бизнеса (без техники)
PLAIN = [
    (r"не открывается|ошибкой", "сайт сейчас не открывается, и клиент уходит к соседям"),
    (r"соцсеть|таплинк", "вместо сайта стоит ссылка на соцсеть, а там неудобно смотреть услуги и цены"),
    (r"https", "браузер помечает сайт как «Не защищено», это отпугивает"),
    (r"телефон", "на телефоне сайт выглядит мелко, а с телефона заходит большинство"),
    (r"подвале", "по сайту видно, что его давно не обновляли"),
    (r"записаться|заявку", "с сайта нельзя записаться или оставить заявку"),
    (r"цен", "на сайте не видно цен"),
    (r"мессенджер", "нет кнопки, чтобы сразу написать или позвонить"),
    (r"долго", "сайт долго грузится"),
]


def plain(problems):
    out = []
    for p in problems:
        for rx, text in PLAIN:
            if re.search(rx, p) and text not in out:
                out.append(text)
                break
    return out[:3]


def note(r):
    """Черновик первого сообщения компании. Перед отправкой его стоит прочитать и поправить."""
    hello = f"{r['name']}, добрый день!" if r["name"] else "Добрый день!"
    if r["problems"] and r["problems"][0].startswith("сайта нет"):
        return (f"{hello} Нашла вас на картах и увидела, что сайта у вас пока нет. "
                "Могу собрать простой сайт на одну страницу: услуги, цены, фото и кнопка записи. "
                "Если интересно, пришлю пример, как это может выглядеть у вас.")
    probs = plain(r["problems"])
    if not probs:
        return ""
    lst = "; ".join(probs)
    return (f"{hello} Зашла на ваш сайт и заметила, из-за чего могут теряться клиенты: {lst}. "
            "Могу сделать новую версию страницы. Пришлю набросок, если интересно.")


def msg(r):
    head = f"{verdict(r['score'])} · <b>{E(r['name'] or r['site'])}</b>"
    lines = [head]
    if r["site"] and r["site"].lower() not in NO_SITE:
        lines.append(f"🔗 {E(r.get('final') or r['site'])}" + (f" · {r['builder']}" if r.get("builder") else ""))
    if r["problems"]:
        lines.append("Что плохо:\n" + "\n".join(f"• {E(p)}" for p in r["problems"]))
    if r["good"]:
        lines.append("Хорошо: " + E(", ".join(r["good"])))
    if r["score"] >= 5:
        lines.append(f"✉️ Черновик:\n<i>{E(note(r))}</i>")
    return "\n".join(lines)


def report(results, path):
    rows = "".join(
        f"<tr><td>{E(verdict(r['score']))}</td><td>{E(r['name'])}</td>"
        f"<td>{E(r.get('final') or r['site'] or 'нет')}</td><td>{r['score']}</td>"
        f"<td>{'<br>'.join(E(p) for p in r['problems']) or '—'}</td>"
        f"<td>{E(note(r)) if r['score'] >= 5 else ''}</td></tr>"
        for r in results)
    path.write_text(
        "<!doctype html><meta charset='utf-8'><title>Аудит сайтов</title>"
        "<style>body{font:14px system-ui;margin:20px}table{border-collapse:collapse}"
        "td,th{border:1px solid #ccc;padding:6px;vertical-align:top}</style>"
        f"<h1>Аудит сайтов · {datetime.now():%d.%m.%Y}</h1><table>"
        "<tr><th>Итог</th><th>Компания</th><th>Сайт</th><th>Баллы</th><th>Проблемы</th>"
        f"<th>Черновик сообщения</th></tr>{rows}</table>", "utf-8")


def main():
    raw = os.getenv("SITES") or ""
    f = Path(__file__).parent / "sites.txt"
    if not raw.strip() and f.exists():
        raw = f.read_text("utf-8")
    items = parse(raw)
    if not items:
        print("Список пуст: передайте SITES или заполните scraper/sites.txt")
        return
    results = sorted((check(n, s) for n, s in items), key=lambda r: -r["score"])
    from main import tg  # отправка в бот (без токена просто печатает)
    need = sum(r["score"] >= 5 for r in results)
    tg(f"🔍 <b>Аудит сайтов</b>: проверено {len(results)}, нужен новый или сайт слабый у {need}.")
    for r in results:
        tg(msg(r))
        time.sleep(0.5)
    report(results, Path("audit_report.html"))
    print("Готово:", len(results))


if __name__ == "__main__":
    main()
