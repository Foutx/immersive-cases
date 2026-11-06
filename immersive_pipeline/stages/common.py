"""Общие утилиты: цветной лог, атомарная запись JSON, нормализация текста, HTTP."""
from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import ssl
import sys
import tempfile
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

import config

# --- Лог ----------------------------------------------------------------------
try:
    import colorama

    colorama.just_fix_windows_console()
except (ImportError, AttributeError):
    pass

_COLORS = {
    "ADDED": "\033[92m", "ENRICHED": "\033[96m", "SELECTED": "\033[92m",
    "SKIP - DUPLICATE": "\033[93m", "SKIP": "\033[93m", "NO VIDEO": "\033[93m",
    "VALIDATION ERROR": "\033[91m", "ERROR": "\033[91m", "GATE": "\033[95m",
    "WARN": "\033[33m", "INFO": "\033[94m", "DONE": "\033[1;92m",
}
_RESET = "\033[0m"
_USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def log(status: str, message: str) -> None:
    color = next((c for key, c in _COLORS.items() if status.startswith(key)), "")
    tag = f"[{status}]"
    if _USE_COLOR and color:
        tag = f"{color}{tag}{_RESET}"
    print(f"{tag} {message}", flush=True)


# --- JSON-состояния ---------------------------------------------------------------
def load_json(path: Path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8-sig") as stream:
        return json.load(stream)


def save_json(path: Path, data) -> None:
    """Атомарная запись: сначала во временный файл, затем os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, ensure_ascii=False, indent=2, default=str)
            out.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


# --- Текст --------------------------------------------------------------------
STOPWORDS = set("""a an the of and or in on at to for by with from by is are be it its this that
immersive experience exhibition show video official new и в во на с со к о об из для по от до
the выставка шоу проект project""".split())


def norm_text(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def tokens(value, *, drop_stop=True) -> set[str]:
    words = norm_text(value).split()
    return {w for w in words if len(w) > 1 and not (drop_stop and w in STOPWORDS)}


def similarity(a, b) -> float:
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return 0.0
    matcher = SequenceMatcher(None, a, b)
    if matcher.real_quick_ratio() < 0.5:
        return 0.0
    return matcher.ratio()


def coverage(needle, haystack_tokens: set[str]) -> float:
    """Доля значимых слов `needle`, встречающихся в тексте (с учётом префиксов)."""
    wanted = tokens(needle)
    if not wanted:
        return 0.0
    hit = 0
    for word in wanted:
        if word in haystack_tokens or (len(word) >= 5 and any(
                t.startswith(word[:5]) for t in haystack_tokens)):
            hit += 1
    return hit / len(wanted)


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


# --- HTTP (stdlib + asyncio.to_thread, чтобы не тянуть лишних зависимостей) -----------
class _HostThrottle:
    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, host: str):
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            delay = config.PER_HOST_DELAY - (time.monotonic() - self._last.get(host, 0))
            if delay > 0:
                await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


_throttle = _HostThrottle()


def _blocking_request(method, url, params, headers, json_body, timeout):
    full = url + (("&" if "?" in url else "?") + urlencode(params) if params else "")
    data = (json_body if isinstance(json_body, bytes) else json.dumps(json_body).encode()) if json_body is not None else None
    merged = {"User-Agent": config.USER_AGENT, "Accept-Encoding": "gzip",
              "Accept-Language": "en,ru;q=0.8"}
    if data is not None:
        merged["Content-Type"] = "application/json"
    merged.update(headers or {})
    request = Request(full, data=data, headers=merged, method=method)
    try:
        context = ssl.create_default_context(cafile=os.getenv("SSL_CERT_FILE") or None)
        with urlopen(request, timeout=timeout, context=context) as response:
            body = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            charset = response.headers.get_content_charset() or "utf-8"
            return response.status, body.decode(charset, "replace")
    except HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")
    except (URLError, OSError, ValueError) as exc:
        return 0, str(exc)


async def http_request(method: str, url: str, *, params=None, headers=None, json_body=None,
                       timeout=None, retries=2) -> tuple[int, str]:
    """Возвращает (status, text). status == 0 — сетевая ошибка."""
    timeout = timeout or config.HTTP_TIMEOUT
    for attempt in range(retries + 1):
        await _throttle.wait(host_of(url))
        status, text = await asyncio.to_thread(
            _blocking_request, method, url, params, headers, json_body, timeout)
        if status not in (0, 429) and status < 500:
            return status, text
        if attempt < retries:
            await asyncio.sleep(2 ** attempt * 2)
    return status, text


async def get_json(url, **kwargs):
    status, text = await http_request("GET", url, **kwargs)
    if status != 200:
        return status, None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, None
