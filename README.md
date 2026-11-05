# immersive-cases

Поиск похожих культурных мероприятий по описанию идеи. В `cases.json` собраны 100 кейсов из архива «Культура.РФ». Поиск работает локально. Для пополнения базы сборщик обращается к сайту.

## Быстрый старт

Понадобится Python 3.10 или новее. Все команды выполняются из папки `immersive-cases`. Проект использует стандартную библиотеку Python.

```powershell
python cases_pipeline.py validate
python case_search.py "мастер-класс по керамике"
```

Для базы из репозитория проверка выводит `Проверено карточек: 100`. Поиск возвращает до пяти результатов с идентификатором, типом совпадения (`close` или `partial`) и пояснением. Например, по запросу выше находится мастер-класс «Роспись по керамике». Чтобы посмотреть запись, найдите карточку по идентификатору в `cases.json` и откройте её `source_url`.

## Сбор новых мероприятий

```powershell
python cases_pipeline.py --db collected.json collect --limit 100 --pages 30
python cases_pipeline.py --db collected.json validate --links
python case_search.py --db collected.json "спектакль в театре"
```

Первая команда создаёт или пополняет `collected.json`. Сборщик просматривает до 30 страниц архива и добавляет до 100 новых карточек, для которых нашёл сведения о видеозаписи. Для пробного запуска достаточно `--limit 3`. В собранной карточке `date` обозначает дату трансляции. Команда `validate --links` проверяет структуру базы и доступность ссылок.

## Импорт своих карточек

```powershell
python cases_pipeline.py --db collected.json import incoming.json
python cases_pipeline.py --db collected.json import incoming.csv
```

Вместо `incoming.json` или `incoming.csv` укажите свой файл. Для JSON нужен массив карточек, для CSV — заголовки с названиями полей. Обязательны `title`, `description` (2–4 предложения) и `source_url`. При отсутствии `id` программа создаст его по ссылке. При повторном импорте совпадающие карточки объединяются.

Если для оценки поиска выделена отдельная выборка, её можно исключить при импорте:

```powershell
python cases_pipeline.py --db collected.json --eval-file eval_100_cases.json import incoming.json
```

## Файлы проекта

| Файл | Назначение |
| --- | --- |
| `cases.json` | Готовая база из 100 мероприятий |
| `case_search.py` | Поиск по базе и функция `search_cases(query, cases, limit=5)` |
| `culture_archive.py` | Чтение архива «Культура.РФ» и извлечение сведений о мероприятиях |
| `cases_pipeline.py` | Команды сбора, импорта и проверки базы |
