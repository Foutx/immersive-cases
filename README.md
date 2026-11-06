# Immersive Cases

**Сборщик референсов для иммерсивных выставок, инсталляций и мультимедийных событий.**

Программа обходит сайты студий и премий, извлекает карточки через LLM, ищет видео,
оценивает кандидатов и формирует JSON-базу. По готовой базе можно искать примеры для своей идеи.
Основной настроенный провайдер — **GigaChat-2-Max**; также поддерживаются Ollama и OpenAI-совместимый API.

> **Статус:** разработка. Извлечение через GigaChat проверено на реальных страницах teamLab.
> Все четыре этапа покрыты офлайн-тестами, но полный сбор проверенного топ-100 ещё не подтверждён.
> Готовая база из 100 кейсов в репозиторий не входит. Карточки LLM требуют проверки фактов.

## Как это устроено

```text
Сайты студий и премий → карточки кандидатов → поиск видео → оценка → cases.json
                              GigaChat           API        правила
```

| Этап | Что делает | Результат в immersive_pipeline/data/ |
| --- | --- | --- |
| `stage1` | Читает страницы, извлекает сведения, объединяет похожие карточки | `raw_candidates.json` |
| `stage2` | Ищет видео по студии, визуальным признакам, месту и обзорам | `enriched_cases.json` |
| `stage3` | Отбирает кейсы с видео и считает баллы | `scored_cases.json`, `top_cases.json` |
| `stage4` | Проверяет формат и экспортирует базу | `final_cases.json`, `cases.schema.json` |

Ориентиры по умолчанию: пул 250–300 кандидатов, итог 100 кейсов, годы 2018–2026.
Количество не гарантируется: оно зависит от источников, полноты фактов и доступных видео.

## Быстрый старт · Windows / PowerShell

Нужен Python 3.10+ и Git. Команды выполняются **из корня репозитория**.

```powershell
git clone https://github.com/Foutx/immersive-cases.git
cd immersive-cases
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r immersive_pipeline/requirements.txt
Copy-Item immersive_pipeline/.env.example immersive_pipeline/.env
notepad immersive_pipeline/.env
```

Копируйте пример только при первой настройке: существующий `.env` содержит ваши ключи.
В файле укажите:

```dotenv
LLM_PROVIDER=gigachat
GIGACHAT_AUTH_KEY=ваш_ключ_авторизации
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_MODEL=GigaChat-2-Max
GIGACHAT_BASE_URL=https://api.giga.chat/v1
GIGACHAT_STRUCTURED=0
```

Нужен **Authorization Key из кабинета GigaChat API**, без префикса `Basic`.
Scope должен соответствовать аккаунту; для организации используйте выданный ей scope.
Клиент получает и обновляет временный токен автоматически. Доступность модели и расход
квоты зависят от аккаунта. [Авторизация GigaChat](https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api).

Пробный запуск на трёх ссылках:

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage1 --llm gigachat --seed teamLab --limit 3
powershell -ExecutionPolicy Bypass -File .\run.ps1 status
```

`run.ps1` использует `.venv` в корне. Для текущей локальной установки предусмотрен
резервный Python из pgAdmin и зависимости `.test-deps`; на другом компьютере создайте `.venv`.
Прямой эквивалент запуска:

```powershell
.\.venv\Scripts\python.exe immersive_pipeline/main.py stage1 --llm gigachat --seed teamLab --limit 3
```

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r immersive_pipeline/requirements.txt
cp immersive_pipeline/.env.example immersive_pipeline/.env
# Заполните .env перед запуском.
python immersive_pipeline/main.py stage1 --llm gigachat --seed teamLab --limit 3
```

## Сбор базы по шагам

Для существующей настройки Windows:

```powershell
# Обход teamLab — по умолчанию до 40 ссылок из каталога выставок
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage1 --seed teamLab

# Все включённые источники из seeds.json
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage1

# Пробный поиск видео: сначала проверьте качество на 10 кейсах
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage2 --limit 10

# Поиск видео для оставшихся кандидатов
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage2

# Оценка и отбор
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage3

# Экспорт полного набора в cases.json в корне
powershell -ExecutionPolicy Bypass -File .\run.ps1 stage4 --strict --publish cases.json
```

Для этапа 2 задайте `YOUTUBE_API_KEY` и/или `VIMEO_TOKEN` в `.env`.
Без этих ключей остаётся DuckDuckGo: его HTML-поиск может блокироваться или менять разметку.
Автоматически подтверждаются видео YouTube/Vimeo через oEmbed и текстовые признаки релевантности.
Это не просмотр ролика человеком и не гарантия соответствия проекту.

`stage4 --publish` требует ровно `FINAL_COUNT` записей (по умолчанию 100).
Для просмотра неполного результата используйте `stage4` без `--strict` и `--publish`:
он создаст `data/final_cases.json` с предупреждением о недоборе.

`all` запускает четыре этапа подряд. Для первого использования рекомендуются отдельные этапы,
чтобы проверить карточки до расходования поисковых квот.

## Повторный запуск и сообщения

- `Ctrl+C` останавливает работу. Уже сохранённые карточки остаются на диске.
- `stage1` пропускает успешно обработанные страницы; похожие кейсы объединяются.
- `--limit 3` на этапе 1 ограничивает первые три подходящие ссылки **каждого источника**,
  а не число новых кейсов. Уже обработанные ссылки тоже входят в этот лимит.
- `--limit 10` на этапе 2 ограничивает число обрабатываемых кандидатов.
- `stage2 --force` повторяет поиск видео для всех выбранных кандидатов.
- После изменения карточки в исходном пуле повторите этап 2 с `--force`, затем этапы 3–4.

| Сообщение | Значение и действие |
| --- | --- |
| `[ADDED]` | Карточка принята по схеме и сохранена; факты ещё нужно проверить |
| `N кандидатов (цель 250–300)` | Недобор пула, не ошибка подключения |
| `Crawl4AI не установлен` | Работает обычный загрузчик; это допустимо |
| `Не хватает данных` | В ответе отсутствуют обязательные факты; страница остаётся для повтора |
| `HTTP 0` | Ошибка соединения или TLS; это не ответ API о неправильном ключе |
| `HTTP 401 / 403` | Проверьте доступ аккаунта, ключ, scope и разрешение на модель |
| `HTTP 429` | Ограничение частоты запросов или квоты |
| `GigaChat не вернул карточку` | Сбор остановлен после попытки исправить ответ; смотрите диагностику |

Диагностика находится в `immersive_pipeline/data/.state/`:
`gigachat_last_response.json` — проблемный ответ модели;
`last_invalid_candidate.json` — последняя невалидная карточка и причина.
Ключи и заголовки авторизации туда не записываются.

## Что проверять перед использованием кейсов

Проверка схемы подтверждает структуру данных, а не истинность описания.
Сверьте название, год открытия, место, бренд и технологии с первоисточником.
Модель может перепутать выставку с отдельным произведением или взять год из навигации сайта.
Для teamLab используется каталог выставок `/e/`; бренд по умолчанию задан явно.
Для других студий автор производства автоматически не становится заказчиком.

Сайты и шаблоны ссылок из `seeds.json` требуют проверки по одному источнику.
Сборщик обходит ссылки каталога, но не реализует универсальную пагинацию всех сайтов.
HTML без браузера может не содержать данные, которые сайт подгружает JavaScript.

При необходимости браузерного загрузчика:

```powershell
.\.venv\Scripts\python.exe -m pip install -r immersive_pipeline/requirements-browser.txt
.\.venv\Scripts\crawl4ai-setup.exe
```

В `.env` можно выбрать `USE_CRAWL4AI=yes` или `no`. Для дополнительного доверенного CA
задайте `SSL_CERT_FILE` с путём к PEM-файлу; проверка TLS остаётся включённой.

## Поиск по готовой базе

```powershell
.\.venv\Scripts\python.exe case_search.py --db cases.json "интерактивная выставка"
```

Поиск локальный, по словам и признакам карточки, без LLM. Возвращает до пяти совпадений.
Поддерживается формат иммерсивных кейсов и прежние карточки с полем `description`.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q immersive_pipeline/tests
```

Тесты не используют реальные ключи, сеть или платные запросы. Они проверяют четыре этапа,
обновление токена, обработку ошибок, повторный запуск и защиту неполного экспорта.
Успешные тесты не заменяют пробный сбор с реальным API.

## Структура проекта

```text
README.md                         быстрый старт и работа с программой
GITHUB.md                         загрузка изменений в GitHub
run.ps1                           запуск из PowerShell
case_search.py                    локальный поиск по базе
requirements-dev.txt              зависимости для тестирования
immersive_pipeline/
  main.py                         команды stage1–stage4, all, status
  config.py                       пути, пороги, квоты и настройки
  seeds.json                      источники и шаблоны ссылок
  .env.example                    пример настроек без ключей
  stages/                         реализация этапов и LLM-клиенты
  tests/                          офлайн-тесты
  data/                           локальные результаты и примеры импорта
```

[Настройки и формат данных](immersive_pipeline/README.md) · [Как загрузить в GitHub](GITHUB.md)

Ключи, диагностические файлы, окружения и собранные базы исключены через `.gitignore`.
Примеры импорта и пустой список существующих кейсов входят в исходники.
