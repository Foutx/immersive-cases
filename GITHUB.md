# Загрузка в Foutx/immersive-cases

Текущая рабочая папка может быть распакованным архивом без `.git`.
Для существующего GitHub-проекта используйте клонирование: так сохраняется его история.
Не создавайте независимую историю поверх существующего репозитория и не используйте force push.

## Из подготовленного архива

Рядом с README локально подготовлен `immersive-cases-source.zip`: только исходники,
документация, примеры и зависимости. В нём нет `.env`, собранных кейсов, диагностик и окружений.
Архив не хранится в Git; при последующих изменениях его нужно собрать заново.

В PowerShell, находясь в папке, где лежит архив:

```powershell
git clone https://github.com/Foutx/immersive-cases.git .publish/github
Set-Location .publish/github
git switch -c update-immersive-pipeline
Expand-Archive -LiteralPath ../../immersive-cases-source.zip -DestinationPath . -Force
git status --short
git add .
git diff --cached --stat
git diff --cached
git commit -m "Update immersive pipeline, GigaChat integration and documentation"
git push -u origin update-immersive-pipeline
```

Выполняйте команды последовательно; если одна завершилась ошибкой, разберите её перед следующей.
Если папка `.publish/github` или ветка уже существует, используйте имеющееся клонирование
или выберите другое имя. Распаковка обновляет совпадающие файлы, но не удаляет остальные
файлы существующего проекта. Просмотрите diff, особенно если в репозитории есть свои изменения.

После push откройте [репозиторий](https://github.com/Foutx/immersive-cases),
нажмите **Compare & pull request**, проверьте изменения и объедините pull request.
Команда выше загружает отдельную ветку; основная ветка изменится только после объединения.

Если Git просит имя и email автора, задайте их внутри клонированного репозитория:

```powershell
git config user.name "Ваше имя"
git config user.email "Ваш email или GitHub noreply email"
```

При HTTPS-аутентификации используйте предложенный Git вход через браузер или токен GitHub.
Пароль от сайта не подставляйте в URL репозитория.

## Для уже клонированного проекта

Обновите исходники в своей рабочей ветке, затем проверьте `git status` и `git diff`.
Повторите тесты по README, создайте коммит и выполните `git push`.
Для переноса этой версии без архива копируйте только исходники и примеры,
исключая `.env`, `.venv`, `.test-deps`, `__pycache__`, `.pytest_cache`, `.publish`
и локальные результаты из `immersive_pipeline/data/`.

`.gitignore` не удаляет из истории уже закоммиченные секреты. Если ключ ранее попал
в GitHub, отзовите его у провайдера и создайте новый.

[Официальная инструкция GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
