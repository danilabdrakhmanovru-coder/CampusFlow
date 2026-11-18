# CampusFlow API

Сервер — приложение `backend/app/v1/main.py`. Общие функции хеширования
находятся в `backend/app/security.py`. Alembic применяет миграции при старте
контейнера API после готовности PostgreSQL.

## Запуск

Из корня CampusFlow запустите локальный демостенд:

```sh
docker compose -f compose.demo.yaml up --build
```

Интерфейс и API доступны на http://127.0.0.1:8767/. Для университетского
развёртывания используйте `compose.yaml` по [корневой инструкции](../README.md).
OpenAPI доступна в контейнере по `/openapi.json`.

## Эндпоинты

К путям в таблице добавляется префикс `/api/v1`. Защищённые маршруты
принимают `Authorization: Bearer <access_token>`.

| Метод и путь | Назначение |
| --- | --- |
| GET /privacy/policy | Текущая редакция, реквизиты, политика, согласие и технические cookie |
| GET /privacy/documents/{kind}.pdf | PDF для `privacy`, `consent` и `cookies` |
| POST /auth/login | `login` и `password`. Ответ `authenticated` с токеном или `consent_required` с версией |
| POST /auth/consent | `version`, `policy_accepted=true`, `consent_accepted=true` и cookie сеанса. Выдаёт рабочий токен |
| GET /auth/consents · POST /auth/consent/withdraw | История своего аккаунта и отзыв согласия с завершением всех сеансов |
| POST /auth/refresh, /auth/logout · GET /auth/me | Обновить, завершить сессию или получить профиль |
| GET /rooms · GET /rooms/{id}/occupancy | Каталог и занятость на интервале `start`–`end` |
| GET /schedule/entities · GET /schedule | Справочники и расписание по `scope=group\|teacher\|mine\|room\|building`, `entity_id`, `from` и `to` |
| GET /slots/recommendations | До трёх вариантов. `day`, `kind`, `count`, необязательные `group` и `equipment` |
| POST /booking-holds · DELETE /booking-holds/{id} | Удержать интервал на пять минут или освободить его |
| POST /bookings · GET /bookings/mine · POST /bookings/{id}/cancel | Подтвердить удержание, посмотреть свои брони или отменить бронь |
| GET /analytics/windows, /analytics/occupancy, /analytics/forecasts | Окна, загрузка и прогноз. Для прогноза передаётся также дата `target` |
| GET /admin/bookings · POST /admin/rooms · PUT /admin/rooms/{id} | Общий список броней и управление аудиториями |
| GET, POST /admin/users · PATCH /admin/users/{id} | Список, создание и управление пользователями |
| PUT, DELETE /admin/users/{id}/teacher-link · DELETE /admin/users/{id}/data | Привязка преподавателя по корпусу и номеру, удаление данных аккаунта |
| GET, POST /admin/imports · GET /admin/imports/{id} | Загрузка, история и предпросмотр |
| POST /admin/imports/{id}/publish, /admin/imports/{id}/rollback | Публикация и откат версии |
| POST /admin/optimization-runs | Предложение переносов с метриками до и после |

Создание удержания и подтверждение брони требуют отдельных заголовков
`Idempotency-Key`. Для удержания передайте `room_id`, `start` и `end`
с часовым смещением. Для подтверждения передайте `hold_id` и `title`.
Удержания, брони и опубликованные занятия занимают общий календарь PostgreSQL.

## Форматы импорта

`POST /admin/imports` принимает multipart-форму с `file`, `scope` (`iimrt`,
`6` или `7`), `date_from`, `date_to`, необязательным `mapping_json`
и флагом `complete` для полного расписания корпуса. Даты периода включительны.

- CSV и первый лист XLSX поддерживают поля `start`, `end`, `building`, `room`,
  `subject`, `groups`, `teachers`. Время без смещения считается местным.
  Несколько значений внутри ячейки разделяются точкой с запятой.
- Для сопоставления передайте JSON вида `{"start":"Начало","subject":"Дисциплина"}`.
  Если нужные колонки не найдены, ответ вернёт заголовки.
- ICS поддерживает `DTSTART`, `DTEND`, `SUMMARY`, `LOCATION` в формате
  «Корпус 6 - 101», альтернативные `X-BUILDING` и `X-ROOM`, а также
  `X-GROUPS` и `X-TEACHERS`. Повторения и исключения раскрываются в рамках периода.
- JSON выгрузки ИИМРТ принимается в области `iimrt`.

После предпросмотра публикация заменяет действующую версию области. Откат возвращает
предыдущую версию. Обе операции проверяют занятость. Полная выгрузка требует
зарегистрированных в каталоге аудиторий. Только опубликованная полная выгрузка
корпуса подтверждает покрытие календаря для всего запрошенного интервала.

## Оптимизатор и тесты

Тесты находятся в [backend/tests](tests). Интеграционная проверка записывает
синтетические данные в выделенную PostgreSQL после применения миграций.

## API Пульса кампуса

| Метод и путь | Назначение |
| --- | --- |
| GET /free-now · GET /rooms/{id}/timeline · GET /events | Свободные сейчас, слои занятости и SSE об изменениях |
| POST /booking-holds/{id}/renew | Одно продление удержания с отдельным Idempotency-Key |
| GET /tickets/{id} · POST /tickets/{id}/check-in | QR-токен и отметка явки |
| GET, POST /watches · DELETE /watches/{id} | Сторож слота. Для создания нужен Idempotency-Key |
| GET /notifications · GET /me/windows | Уведомления владельца и окна для своего расписания или группы |
| GET, POST /admin/imports/{id}/conflicts | Список пересечений и решение с причиной и Idempotency-Key |
| POST /admin/optimization-runs · GET /admin/proposals · POST /admin/proposals/{id}/apply | Подбор на период до семи дней, очередь и частичное применение |
| GET, PUT /admin/group-sizes · PUT /admin/walking-times | Численность групп и измеренные переходы |
| POST /auth/password · GET /admin/audit | Смена своего пароля и журнал действий |

Удержания отклоняются с кодом no_coverage при отсутствии полного импорта.
Уже начавшийся слот доступен при остатке от 15 минут. Повтор ключа истёкшего
удержания даёт hold_expired. /bookings/mine скрывает отменённые, для истории
передайте include_cancelled=true. Рекомендации принимают duration с шагом 15 минут.
Для оптимизации необязательный end_day задаёт конец периода. Тип берётся
из исходной аудитории, число участников — из каталога групп. Оба параметра
можно переопределить. Прогноз спроса работает на истории броней и сравнивается
со средним в обучающем периоде. Модель синтетических неявок в API и UI не используется.

Дополнительные маршруты версии 3 включают `/me`, `/me/preferences`, `/me/sessions`,
`/me/export`, `/me/deletion-request`, `/me/teacher-link-request`, `/schedule/export/pdf`, `/schedule/export/docx`,
`/rooms/free`, `/analytics/groups/windows`, `/analytics/groups/{group}/windows`,
`/analytics/groups/{group}/suggestions`, `/suggestions/{id}/decision`,
`/analytics/model`, `/admin/overview` и `/admin/settings`. Методы, параметры и роли
описаны в OpenAPI на локальной копии API.
