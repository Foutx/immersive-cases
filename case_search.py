"""Поиск мероприятий по теме, площадке, формату и аудитории."""
import argparse
import json
import re
from pathlib import Path

# Общие основы для распространённых словоформ и синонимов.
ROOTS = """музе культурн центр экскурси фестивал семинар выставк лаборатори
инклюз доступн сред живопис цифров искусств мультимедиа архив локальн
истори устн нейро медиаци молодеж школьник подростк лекци кальян программ
библиотек керамик концерт театр поэзи""".split()
STOP = set("хочу хочуся сделать провести про для по в во на с со к о об и из мероприятие мероприятия мероприятии событие посвященное посвященный там хочу бы".split())

def terms(text):
    words = re.findall(r"[а-яa-z0-9]+", (text or "").lower().replace("ё", "е"))
    return {next((root for root in ROOTS if w.startswith(root)), w)
            for w in words if w not in STOP}

def search_cases(query, cases, limit=5):
    requested = terms(query)
    if not query.strip():
        raise ValueError("Опишите идею мероприятия")
    fields = ("venue_type", "format", "audience")
    # Аудитория может содержать тему («люди, интересующиеся искусством»).
    # Поэтому распознаём аудиторию по явным обозначениям групп.
    vocab = {key: set().union(*(terms(c.get(key)) for c in cases)) for key in fields}
    vocab["audience"] &= set("молодеж школьник подростк дети студентов взрослые".split())
    asked = {k: requested & v for k, v in vocab.items()}
    topic = requested - set().union(*asked.values())
    ranked = []
    seen = set()
    for c in cases:
        tag_text = " ".join(c.get("topics") or [])
        evidence = terms(" ".join((tag_text, c["title"], c["description"])))
        hits = topic & evidence
        matched = [k for k in fields if asked[k] and asked[k] <= terms(c.get(k))]
        if not (hits or matched):
            continue
        complete = hits == topic and all(not asked[k] or k in matched for k in fields)
        labels = {"venue_type": "Площадка", "format": "Формат", "audience": "Аудитория"}
        reasons = [labels[k] + " — " + c[k] for k in matched]
        if hits:
            excerpt = next((t for t in c.get("topics") or [] if terms(t) & hits), None)
            if not excerpt:
                excerpt = c["title"] if hits & terms(c["title"]) else c["description"]
            reasons.insert(0, "Тематическое совпадение: " + excerpt)
        elif topic:
            reasons.append("Совпадение по теме не найдено")
        result = dict(id=c["id"], match_type="close" if complete else "partial",
                      explanation=". ".join(reasons))
        ranked.append((-len(hits), -len(matched), c["id"], result))
    output = []
    for _, _, cid, item in sorted(ranked, key=lambda row: row[:3]):
        if cid not in seen:
            seen.add(cid)
            output.append(item)
    return output[:max(0, min(limit, 5))]

if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("--db", default=Path(__file__).with_name("cases.json"))
    cli.add_argument("query")
    args = cli.parse_args()
    try:
        cards = json.loads(Path(args.db).read_text(encoding="utf-8"))
        print(json.dumps(search_cases(args.query, cards), ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        cli.exit(1, str(exc) + "\n")
