# Pomodoro Desktop

Desktop-приложение на `PySide6` с единым Pomodoro-таймером.

## Требования
- Python 3.11+
- Windows/macOS/Linux

## Установка
```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

## Запуск
```bash
python main.py
```

## Текущее состояние
- Pomodoro работает как раньше (главное окно + плавающее окно).
- Раздел `Планирование` сейчас в упрощенном режиме:
  - автоматически показывает текущий день по системной дате,
  - автоматически определяет текущую неделю,
  - есть навигация `неделя назад / текущая неделя / неделя вперед`.

## Данные
- Данные пользователя хранятся отдельно от exe:
  - `%APPDATA%\\FlowGrid\\settings.json`
  - `%APPDATA%\\FlowGrid\\planner_state.json`
- При первом запуске выполняется безопасная best-effort миграция legacy-файлов
  (`settings.json`, `planner_state.json`) из старого каталога запуска в `%APPDATA%\\FlowGrid`.
- Запись JSON выполняется атомарно (tmp-файл в той же папке + `os.replace`), чтобы не повредить
  конфиг при аварийном завершении приложения.

## Обновления (v1 UX)
- Проверка обновлений выполняется автоматически при запуске (тихо, без навязчивых popup).
- В настройках доступны режимы:
  - полностью отключить систему обновлений,
  - оставить только уведомления (без автоустановки),
  - включить автоустановку после тихой автопроверки.
- Ручная проверка остается доступной:
  - `Настройки -> Обновления -> Проверить обновления`
  - страница `Обновления -> Проверить сейчас`
- Если найдена новая версия, появляется нижний footer-баннер:
  - текст с номером версии,
  - кнопка `Обновить` (переход на страницу `Обновления`),
  - кнопка `Скрыть`.
- Если пользователь скрыл баннер для версии `X.Y.Z`, он не показывается снова для этой же версии
  (пока не появится более новая версия или не будет выполнена значимая ручная проверка).
- На странице `Обновления` отображаются:
  - текущая версия,
  - последняя найденная версия,
  - `minimum_supported_version`,
  - дата публикации,
  - release notes (кратко + разворачиваемый подробный список),
  - последняя ошибка проверки,
  - время последней попытки и последнего успешного check.
- Поддерживаемые URL манифеста:
  - `https://...`
  - `http://...`
  - `file:///...` (локальный файл для тестов)
- По умолчанию используется манифест из репозитория:
  - `https://raw.githubusercontent.com/OleksandrLozenko/Smart_task_scheduler/main/update_manifest.json`

### Cooldown авто-проверки
- Используется интервал автопроверки (по умолчанию `12 часов`).
- Хранятся два таймстампа:
  - `last_update_check_attempt_at`
  - `last_update_check_success_at`
- Cooldown считается по `last_update_check_attempt_at`:
  это предотвращает частые повторные запросы даже при временных сетевых ошибках.

## Обновления (v2, установка)
- Если в манифесте есть валидные `download_url` и `sha256`, после проверки доступна кнопка
  `Скачать и установить`.
- Приложение:
  1. скачивает пакет (`zip`) в `%LOCALAPPDATA%\\FlowGrid\\updates\\downloads`,
  2. проверяет sha256,
  3. запускает отдельный updater,
  4. закрывается.
- Updater:
  1. ждет завершения основного процесса (с таймаутом),
  2. безопасно распаковывает zip (защита от path traversal),
  3. делает backup текущей версии вне папки приложения,
  4. выполняет swap,
  5. запускает обновленную версию.

Важно:
- V1 установки поддерживает только per-user install (без UAC / Program Files сценариев).
- Данные пользователя в `%APPDATA%\\FlowGrid` не трогаются.

## Локальная проверка update-flow (check + install)
### Вариант A: `file://`
1. Подготовьте пакет `update.zip` (onedir сборка приложения):
   - в корне zip должны быть файлы будущей папки установки, например:
     - `FlowGrid.exe`
     - `FlowGridUpdater.exe`
     - `_internal/...`
2. Посчитайте sha256 zip.
3. Создайте `update_manifest.json` (пример ниже) и укажите:
   - `download_url`: `file:///C:/path/to/update.zip`
4. В приложении укажите URL манифеста:
   - `file:///C:/path/to/update_manifest.json`
5. Нажмите `Проверить обновления`, затем `Скачать и установить`.

### Вариант B: локальный HTTP server
1. Положите в отдельную папку:
   - `update_manifest.json`
   - `update.zip`
2. В этой папке запустите:
   - `python -m http.server 8765`
3. В настройках укажите URL:
   - `http://127.0.0.1:8765/update_manifest.json`
4. В `update_manifest.json` укажите:
   - `download_url`: `http://127.0.0.1:8765/update.zip`

## Формат `update_manifest.json`
```json
{
  "latest_version": "0.7.0",
  "minimum_supported_version": "0.5.0",
  "release_notes": "Исправления стабильности и улучшение UI.",
  "download_url": "file:///C:/updates/update.zip",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "published_at": "2026-03-10T12:00:00Z"
}
```

## Репозиторий как источник обновлений
- Файл `update_manifest.json` лежит в корне репозитория и публикуется через `raw.githubusercontent`.
- Для нового релиза:
  1. Обновите `APP_VERSION` в [app_version.py](C:\Users\Someone\Downloads\FG\app\core\app_version.py).
  2. Обновите поля в [update_manifest.json](C:\Users\Someone\Downloads\FG\update_manifest.json) (`latest_version`, `release_notes`, `download_url`, `sha256`, `published_at`).
  3. Закоммитьте и запушьте изменения.
  4. После этого клиенты при проверке увидят новую версию из репозитория.

### Подготовка будущих обновлений (рекомендуемый поток)
Чтобы не править манифест вручную, используйте скрипт:

```bash
python tools/prepare_update_release.py --version 0.6.1 --release-notes-file RELEASE_NOTES.md
```

Что делает скрипт:
- собирает `zip` из `dist/FlowGrid`,
- считает `sha256`,
- обновляет `update_manifest.json` полями:
  - `latest_version`,
  - `minimum_supported_version`,
  - `release_notes`,
  - `download_url`,
  - `sha256`,
  - `published_at`.

По умолчанию `download_url` формируется под GitHub Releases:

`https://github.com/OleksandrLozenko/Smart_task_scheduler/releases/download/v{version}/FlowGrid_portable_{version}.zip`

После запуска скрипта:
1. Загрузите созданный zip в GitHub Release с тегом `vX.Y.Z`.
2. Закоммитьте `update_manifest.json` (и при необходимости изменения версии).
3. Запушьте в `main`.

Если в манифесте версия выше текущей, но `download_url/sha256` пустые или неверные,
кнопка установки покажет причину и не запустит поврежденный update flow.

### Проверка манифеста перед публикацией
Перед push релиза проверьте манифест и пакет:

```bash
python tools/validate_release_manifest.py --manifest update_manifest.json
```

Скрипт проверяет:
- валидность `update_manifest.json`,
- semver у `latest_version`,
- совпадение имени asset с версией (`FlowGrid_portable_X.Y.Z.zip`),
- доступность `download_url` (ловит `HTTP 404`),
- совпадение `sha256` скачанного пакета и `manifest.sha256`.

### Пример `update_manifest.json` (already up to date)
```json
{
  "latest_version": "0.6.0",
  "minimum_supported_version": "0.5.0",
  "release_notes": "Текущая версия актуальна.",
  "download_url": "file:///C:/updates/update.zip",
  "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "published_at": "2026-03-10T12:00:00Z"
}
```

### Пример битого манифеста
```json
{
  "latest_version": "0.7",
  "minimum_supported_version": "oops"
```

## Тесты
```bash
python -m unittest discover -s tests -v
```

Покрытие включает:
- `parse_semver` / `compare_semver`,
- парсинг манифеста и ошибки формата,
- `file://` сценарии,
- `update available` vs `up-to-date`,
- integration-like проверки UI (footer + страница `Обновления` + активация кнопки `Установить`).

## Сборка updater
- Отдельный updater собирается отдельным spec-файлом:
  - `pyinstaller FlowGridUpdater.spec`
- Для onedir релиза `FlowGridUpdater.exe` должен лежать рядом с `FlowGrid.exe`.

## Windows: снижение ложных срабатываний антивируса
- Для релизной сборки в проекте отключен `UPX` во всех `.spec`:
  - `FlowGrid.spec`
  - `FlowGridUpdater.spec`
  - `FlowGrid-OneFile.spec`
- Рекомендуемый формат дистрибуции: `onedir` (`dist/FlowGrid`) + zip-архив
  `FlowGrid_portable_X.Y.Z.zip` (а не только one-file exe).
- One-file сборка чаще дает ложные срабатывания у SmartScreen/Defender из-за
  самораспаковки во временный каталог.
- Для минимального количества предупреждений на Windows 10/11 используйте
  цифровую подпись (Code Signing) для:
  - `FlowGrid.exe`
  - `FlowGridUpdater.exe`
  - установщика (если используете installer).
- Без цифровой подписи предупреждение "Неизвестный издатель" может появляться,
  это штатное поведение SmartScreen.

## Архитектура
- `app/core` - логика таймера и настройки.
- `app/ui` - окна интерфейса, стили, компонент заголовка недели.
- `app/utils` - утилиты.
