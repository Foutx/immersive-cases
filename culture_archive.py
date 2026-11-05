"""Загрузка подтверждённых записей из публичного архива Культура.РФ."""
import gzip
import json
import re
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = "https://www.culture.ru"


def download(url):
    for attempt in range(3):
        try:
            req = Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "CultureCaseCollector/1.0"})
            with urlopen(req, timeout=20) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return response.geturl(), body.decode("utf-8")
        except (OSError, URLError) as exc:
            if attempt == 2 or isinstance(exc, HTTPError) and exc.code < 500 and exc.code != 429:
                raise
            time.sleep(2 ** attempt)


class Scripts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.key = None
        self.data = {}

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attrs = dict(attrs)
            self.key = attrs.get("id") or attrs.get("type")

    def handle_endtag(self, tag):
        if tag == "script":
            self.key = None

    def handle_data(self, data):
        if self.key in ("__NEXT_DATA__", "application/ld+json"):
            self.data[self.key] = json.loads(data)


def page(url):
    final, html = download(url)
    scripts = Scripts()
    scripts.feed(html)
    return final, scripts.data


def listings(max_pages):
    seen = set()
    for number in range(1, max_pages + 1):
        _, scripts = page(f"{BASE}/live/archive?page={number}")
        props = scripts["__NEXT_DATA__"]["props"]["pageProps"]
        rows = props["broadcasts"]
        fresh = [r for r in rows if r["_id"] not in seen]
        if not fresh:
            break
        for row in fresh:
            seen.add(row["_id"])
            date = row.get("fromDate")
            if date and datetime.fromisoformat(date.replace("Z", "+00:00")) < datetime.now(timezone.utc):
                yield row


def recording(row):
    url = f"{BASE}/live/broadcast/{row['_id']}/{row['name']}"
    final, scripts = page(url)
    objects = scripts.get("application/ld+json", [])
    if isinstance(objects, dict):
        objects = [objects]
    video = next((o for o in objects if o.get("@type") == "VideoObject" and
                  not re.search("трейлер|тизер|анонс|trailer|teaser", o.get("name", ""), re.I) and
                  (o.get("embedUrl") or o.get("contentUrl"))), None)
    if not video:
        return None
    props = scripts["__NEXT_DATA__"]["props"]["pageProps"]
    movie = props.get("movie") or props.get("broadcast") or {}
    title = (movie.get("title") or row["title"]).strip()
    source = final
    match = re.search(r"/live/movies/(\d+)", source)
    identifier = "culture_" + match[1] if match else f"broadcast_{row['_id']}"
    institution = (row.get("institute") or {}).get("title") or ""
    venue = next((label for stem, label in [
        ("музе", "Музей"), ("библиотек", "Библиотека"), ("театр", "Театр"),
        ("филармони", "Филармония"), ("культур", "Культурный центр")
    ] if stem in institution.lower()), None)
    formats = {"lecture": "Лекция", "concert": "Концерт", "performance": "Спектакль",
               "excursion": "Экскурсия", "masterclass": "Мастер-класс"}
    event_format = formats.get(row.get("type")) or formats.get(row.get("broadcastType"))
    raw = unescape(re.sub("<[^>]+>", " ", video.get("description", "")))
    summary = re.sub(r"^\d{1,2}\+\s*", "", " ".join(raw.split()))
    # Сохраняем позиции символов, чтобы не оборвать предложение на инициалах.
    masked = re.sub(r"\b(?:[А-ЯЁA-Z]|им|г|ул|т)\.", lambda m: m[0][:-1] + "·", summary)
    sentence = re.match(r".{18,420}?[.!?](?=\s|$)", masked)
    lead = summary[:sentence.end()] if sentence else f"В архиве представлена запись мероприятия «{title.rstrip('.!?')}»."
    second = f"Трансляцию представила площадка «{institution}»." if institution else "Запись опубликована в архиве культурных трансляций."
    tags = [tag["title"] for tag in (movie.get("tags") or [])
            if isinstance(tag, dict) and isinstance(tag.get("title"), str)]
    return dict(id=identifier, title=title, description=f"{lead} {second}", topics=tags,
                venue_type=venue, format=event_format, audience=None, date=row["fromDate"][:10],
                city=None, source_url=source, photo_urls=[], video_urls=[source], review_urls=[],
                outcome=None, outcome_source_url=None)
