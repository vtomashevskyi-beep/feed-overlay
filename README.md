# Feed Image Overlay

Сервіс, який бере товарний фід Merchant Center (XML/CSV/XLSX), качає фото товарів по image_link, накладає поверх них title, розміри і ціну (sale_price з перекресленою старою ціною), зберігає готові банери в хмару і віддає оновлений фід з новими посиланнями.

## Потік
1. Завантажуєш фід через інтерфейс (/) або POST /api/jobs
2. Парсяться атрибути: id, title, size, price, sale_price, image_link
3. (Опційно) Claude через Anthropic API чистить title під банер і дістає розміри з назви, якщо size пустий
4. Фото качаються паралельно, рендериться оверлей (Pillow), результат зберігається в сховище
5. Забираєш мапу id -> нове посилання і готовий фід: /api/jobs/{id}/feed.csv або feed.xml

## Запуск локально
```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
# відкрити http://localhost:8000
```

## Налаштування (env)
```bash
# сховище
STORAGE_BACKEND=local            # local | s3
PUBLIC_BASE_URL=http://localhost:8000   # для local

# для S3 / Cloudflare R2 / Backblaze B2
STORAGE_BACKEND=s3
S3_ENDPOINT_URL=https://<account>.r2.cloudflarestorage.com   # для AWS не вказувати
S3_BUCKET=feed-images
S3_PUBLIC_BASE=https://cdn.your-domain.com   # публічний домен бакета/CDN
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...

# Anthropic (тільки якщо вмикаєш чистку назв)
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-5

# тюнінг
DOWNLOAD_CONCURRENCY=8
HTTP_TIMEOUT=20
```

Найдешевший прод-варіант сховища - Cloudflare R2: нема плати за вихідний трафік, а Merchant Center буде тягнути ці зображення часто.

## Деплой на Railway
1. Запуш цей репозиторій на GitHub
2. Railway -> New Project -> Deploy from GitHub repo -> вибрати репо. Збірка піде по Dockerfile автоматично (railway.json вже все описує)
3. Settings -> Networking -> Generate Domain. Сервіс сам підхопить домен через RAILWAY_PUBLIC_DOMAIN і буде формувати правильні посилання на зображення
4. Якщо лишаєшся на local-сховищі - додай Volume (Settings -> Volumes) з mount path `/data`, інакше згенеровані банери зникнуть при кожному редеплої
5. Для проду краще одразу R2/S3: у Variables додати STORAGE_BACKEND=s3 і ключі з блоку вище, тоді volume не потрібен
6. Для чистки назв через Claude - додати ANTHROPIC_API_KEY у Variables

Перевірка: відкрити згенерований домен, закинути фід з лімітом 2-3 товари, глянути що нові посилання на зображення відкриваються ззовні.

## Docker
```bash
docker build -t feed-overlay .
docker run -p 8000:8000 --env-file .env feed-overlay
```

## API
- `POST /api/jobs` - multipart: feed (файл), brand, text_color, gradient, use_claude, limit
- `GET /api/jobs/{id}` - статус, прогрес, мапа id -> new_image_link
- `GET /api/jobs/{id}/feed.csv` / `feed.xml` - оновлений фід з підміненим image_link

## Кастомізація оверлею
`app/renderer.py` - все накладання в одному місці. Шрифти задаються через env (FONT_TITLE, FONT_PRICE, FONT_BRAND, FONT_SIZES) - підкинь фірмові ttf бренду і вони підхопляться. Позиції масштабуються від ширини зображення, тому фід з різними розмірами фото рендериться консистентно.

## Що доробити для проду
- джоби зараз в пам'яті процесу - для проду винести в Redis/Postgres + черга (наприклад, arq або Celery)
- авторизація на API
- ретраї на скачування зображень
- логотип бренду картинкою замість тексту (renderer легко розширюється через Image.paste)
