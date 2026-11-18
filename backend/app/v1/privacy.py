"""Public pilot documents, shared by the browser, the PDF and the consent gate."""
from os import environ

from .site_config import site_preferences

POLICY = "pilot-4"

CONFIG = {
    "operator": "CAMPUSFLOW_PRIVACY_OPERATOR",
    "responsible": "CAMPUSFLOW_PRIVACY_RESPONSIBLE",
    "contact": "CAMPUSFLOW_PRIVACY_CONTACT",
    "effective_date": "CAMPUSFLOW_PRIVACY_EFFECTIVE_DATE",
}


def policy_version(db=None) -> str:
    version = site_preferences(db)["version"] or POLICY
    if len(version) > 80:
        raise ValueError("CAMPUSFLOW_PRIVACY_VERSION must contain at most 80 characters")
    return version


def documents(db=None) -> dict:
    settings = site_preferences(db)
    operator = {key:settings.get(key) for key in CONFIG}
    booking_days = settings.get("booking_days") or 365
    audit_days = settings.get("audit_days") or 365
    session_days = settings.get("session_days") or 1
    retention = (
        f"Брони и удержания хранятся до {booking_days} дн. с окончания интервала, журнал действий — "
        f"до {audit_days} дн., истёкшие сеансы — до {session_days} дн. после истечения, с учётом периодичности очистки. "
        "Учётные данные и история согласий хранятся до удаления данных аккаунта. "
        "Сроки хранения резервных копий устанавливает оператор до запуска."
    )
    rights = ("За сведениями об обработке, уточнением или удалением данных обратитесь к оператору. "
              "Контакт публикуют в шапке этого документа.")
    withdrawal = ("Откройте «Личный кабинет» → «Данные и конфиденциальность» → «Отозвать согласие». "
                  "Доступ к сервису закроется, все сеансы завершатся. Для рассмотрения вопроса "
                  "о дальнейшем хранении или удалении данных обратитесь к оператору.")
    transfer = "CampusFlow обрабатывает данные на сервере университета. Трансграничная передача для этой конфигурации не предусмотрена."
    policy = [
        ("Цели обработки", "Вход в CampusFlow, предоставление расписания, подбор аудиторий, управление бронированием и безопасность аккаунта."),
        ("Правовые основания", "Эта редакция описывает пилот с отдельным согласием пользователя. Применимые основания для университетского запуска определяет оператор."),
        ("Категории данных", "Логин, роль, история согласий, брони и действия с ними, технические сведения о сеансах. Имена преподавателей из выделенного поля импорта заменяются псевдонимами."),
        ("Сроки хранения", retention),
        ("Права пользователя", rights),
        ("Отзыв согласия", withdrawal),
        ("Трансграничная передача", transfer),
        ("Меры защиты", "Доступ ограничен ролью. Пароли хранятся в виде хешей, события доступа журналируются, университетское подключение использует HTTPS."),
    ]
    consent = [
        ("Для чего даю согласие", "Я даю согласие оператору на обработку данных для входа, просмотра расписания и работы с бронированием в CampusFlow."),
        ("Основание и способ подтверждения", "Я выражаю согласие отдельной отметкой и кнопкой подтверждения после проверки логина и пароля. Сервис фиксирует редакцию и время."),
        ("Какие данные обрабатываются", "Логин, роль, сведения о моих бронях и действиях с ними, история согласий и технические сведения о сеансах."),
        ("Сроки хранения", retention),
        ("Мои права", rights),
        ("Как отозвать согласие", withdrawal),
        ("Трансграничная передача", transfer),
        ("Меры защиты", policy[-1][1]),
    ]
    cookies = [
        ("Сеанс", "Технический cookie cf_refresh сохраняет сеанс входа. Ожидание подтверждения документов длится до 15 минут. Обычный сеанс сохраняется до 7 дней и обновляется при продлении."),
        ("Настройки браузера", "Тема, избранная группа и отметка о прочтении этого уведомления хранятся в локальном хранилище браузера."),
        ("Управление", "При выходе cookie сеанса удаляется. Настройки можно очистить в браузере. Аналитические и рекламные cookie CampusFlow не использует."),
    ]
    return {
        "version": policy_version(db), "status": "draft", "demo": environ.get("CAMPUSFLOW_DEMO") == "1",
        "operator": operator, "missing": [key for key, value in operator.items() if not value],
        "retention": retention,
        "documents": {
            key: {"title": title, "sections": [{"title": name, "text": text} for name, text in sections]}
            for key, title, sections in [
                ("privacy", "Политика обработки персональных данных", policy),
                ("consent", "Согласие на обработку персональных данных", consent),
                ("cookies", "Технические cookie", cookies),
            ]
        },
    }
