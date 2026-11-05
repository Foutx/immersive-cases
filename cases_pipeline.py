"""Сбор, импорт, проверка и объединение базы кейсов. Python 3.10+."""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from urllib.request import Request, urlopen

from culture_archive import listings, recording

LISTS = ("topics", "photo_urls", "video_urls", "review_urls")
OPTIONAL = ("venue_type", "format", "audience", "date", "city", "outcome", "outcome_source_url")
LINKS = ("photo_urls", "video_urls", "review_urls")


def read(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if path.suffix.lower() == ".csv":
            sample = stream.read(4096)
            stream.seek(0)
            return list(csv.DictReader(stream, dialect=csv.Sniffer().sniff(sample, delimiters=",;\t")))
        rows = json.load(stream)
    if not isinstance(rows, list):
        raise ValueError(f"{path}: ожидался массив карточек")
    return rows


def items(value):
    if isinstance(value, str):
        value = json.loads(value) if value.lstrip().startswith("[") else value.split(";")
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ValueError("Ожидался список строк")
    return list(dict.fromkeys(v.strip() for v in value if v.strip()))


def normalize(row):
    if not isinstance(row, dict):
        raise ValueError("Карточка должна быть объектом")
    card = {}
    for field in ("id", "title", "description", "source_url", *OPTIONAL):
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field}: ожидалась строка")
        card[field] = (value or "").strip() or None
    for field in LISTS:
        card[field] = items(row.get(field))
    if not all(card[k] for k in ("title", "description", "source_url")):
        raise ValueError("Обязательны title, description и source_url")
    prose = re.sub(r"\([^()]*\)", "", card["description"])
    prose = re.sub(r"\b(?:[А-ЯЁA-Z]|им|г|ул|т)\.\s*", " ", prose)
    if not 2 <= len(re.split(r'(?<=[.!?])\s+(?=[А-ЯЁA-Z«0-9])', prose.strip())) <= 4:
        raise ValueError(f"{card['title']}: описание должно содержать 2–4 предложения")
    if not card["id"]:
        card["id"] = "case_" + hashlib.sha256(card["source_url"].encode()).hexdigest()[:16]
    for url in [card["source_url"], card["outcome_source_url"], *(u for k in LINKS for u in card[k])]:
        if url and (urlsplit(url).scheme not in ("http", "https") or not urlsplit(url).hostname):
            raise ValueError(f"Некорректная ссылка: {url}")
    if card["date"]:
        date.fromisoformat(card["date"])
    return card


def keys(c):
    result = {("id", c["id"]), ("url", c["source_url"].rstrip("/"))}
    # У разных показов одного спектакля может совпадать название.
    if c["date"]:
        result.add(("event", " ".join(c["title"].casefold().split()), c["date"], (c["city"] or "").casefold()))
    return result


class Collection:
    def __init__(self, excluded):
        self.cards = []
        self.index = {}
        self.excluded = excluded

    def add(self, card):
        identity = keys(card)
        if identity & self.excluded:
            return False
        matches = {self.index[k] for k in identity if k in self.index}
        if len(matches) > 1:
            raise ValueError(f"Противоречивые идентификаторы: {card['id']}")
        if matches:
            pos = matches.pop()
            current = self.cards[pos]
            for field in LISTS:
                current[field] = list(dict.fromkeys(current[field] + card[field]))
            for field in OPTIONAL:
                current[field] = current[field] or card[field]
            identity |= keys(current)
        else:
            pos = len(self.cards)
            self.cards.append(card)
        self.index.update(dict.fromkeys(identity, pos))
        return self.cards[pos] is card


def write(path, cards):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, encoding="utf-8", delete=False) as out:
        temp = Path(out.name)
    try:
        temp.write_text(json.dumps(cards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def writer(path):
    lock = path.with_suffix(path.suffix + ".lock")
    try:
        handle = lock.open("x")
    except FileExistsError:
        raise ValueError(f"База занята. После аварийного завершения проверьте файл {lock}.") from None
    try:
        yield
    finally:
        handle.close()
        lock.unlink()


def run(args):
    db = args.db.resolve()
    excluded = set()
    if args.eval_file:
        if args.eval_file.resolve() == db:
            raise ValueError("Контрольная выборка должна храниться отдельно")
        for row in read(args.eval_file):
            excluded.update(keys(normalize(row)))
    collection = Collection(excluded)
    if args.action == "validate":
        rows = read(db)
        urls = set()
        for row in rows:
            if not row.get("id") or not collection.add(normalize(row)):
                raise ValueError("Отсутствует id, есть дубль или пересечение с контрольной выборкой")
            if args.links:
                c = collection.cards[-1]
                urls.update(u for u in (c["source_url"], c["outcome_source_url"],
                            *(u for key in LINKS for u in c[key])) if u)
        for url in sorted(urls):
            try:
                with urlopen(Request(url, headers={"User-Agent": "CultureCaseCollector/1.0"}), timeout=20) as response:
                    response.read(1)
            except OSError as exc:
                raise ValueError(f"{url}: {exc}") from exc
        print(f"Проверено карточек: {len(rows)}")
        return
    db.parent.mkdir(parents=True, exist_ok=True)
    with writer(db):
        for row in read(db) if db.exists() else []:
            collection.add(normalize(row))
        before = len(collection.cards)
        if args.action == "import":
            for row in read(args.file):
                collection.add(normalize(row))
        else:
            for row in listings(args.pages):
                card = recording(row)
                if card:
                    collection.add(normalize(card))
                if len(collection.cards) - before >= args.limit:
                    break
        write(db, collection.cards)
    print(f"Добавлено: {len(collection.cards) - before}. Всего: {len(collection.cards)}. {db}")


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("ожидалось положительное число")
    return value


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--db", type=Path, default=Path(__file__).with_name("cases.json"))
    cli.add_argument("--eval-file", type=Path, help="Отдельная контрольная выборка JSON/CSV")
    commands = cli.add_subparsers(dest="action", required=True)
    collect = commands.add_parser("collect", help="Найти архивные записи и дополнить базу")
    collect.add_argument("--limit", type=positive, default=100, help="Максимум новых карточек")
    collect.add_argument("--pages", type=positive, default=30, help="Максимум страниц каталога")
    commands.add_parser("import", help="Импортировать JSON/CSV").add_argument("file", type=Path)
    validate = commands.add_parser("validate", help="Проверить поля и уникальность карточек")
    validate.add_argument("--links", action="store_true", help="Также проверить доступность всех ссылок")
    try:
        run(cli.parse_args())
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        sys.exit(f"Ошибка: {exc}")
