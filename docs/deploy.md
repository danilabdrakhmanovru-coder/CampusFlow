# Развёртывание CampusFlow

Основной запуск описан в корневом README. Сервисы базы данных и API доступны
только в сети Compose. Локальный веб-порт принимает запросы от прокси университета.
Для SSE оставьте буферизацию отключённой на обоих прокси.

Пример для университетского nginx. Замените домен и пути к сертификатам.
Включайте HSTS после проверки HTTPS на выбранном домене.

```nginx
server {
    listen 443 ssl;
    server_name campusflow.university.example;
    ssl_certificate /etc/nginx/tls/campusflow/fullchain.pem;
    ssl_certificate_key /etc/nginx/tls/campusflow/privkey.pem;
    add_header Strict-Transport-Security "max-age=31536000" always;
    access_log off;
    client_max_body_size 22m;

    location / {
        proxy_pass http://127.0.0.1:8767;
        proxy_set_header Host $http_host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
        proxy_read_timeout 180s;
    }
}
```

По умолчанию ограничитель входа видит IP непосредственного клиента контейнера
nginx. За университетским прокси это может быть общий адрес шлюза. До пилота
настройте в своей сети доверенную передачу IP клиента и отдельное ограничение на
пограничном прокси. CampusFlow хранит HMAC-ключи счётчиков входа, без открытых
логинов и IP в этих счётчиках. Журналы ошибок и PostgreSQL должны оставаться
доступны только операторам. Не включайте журналирование тела запросов и заголовков
авторизации.

Используйте `docker compose ps` для проверки состояния PostgreSQL, API и веба.
Воркер проверяет неявки и очередь сторожа примерно раз в минуту. Уведомления
отображаются в разделе бронирования. Автоматическая внеплановая проверка после
отмены работает при следующем проходе воркера.

Проверяемый дамп на сервере Linux: sh scripts/backup.sh /protected/campusflow.dump.
