# Ridni Kvitu

Telegram shop and Web App for a small flower brand. The project combines a Telegram bot, FastAPI backend, mobile-first storefront, order processing, Monobank payments, and Nova Poshta delivery support.

## Features

- Telegram Web App storefront
- Product catalog with cart and checkout
- Customer order history
- Monobank invoice creation and payment status checks
- Monobank webhook for successful payments
- Admin Web App panel for orders and products
- Admin notifications inside Telegram
- Nova Poshta city, warehouse, TTN, and tracking support
- SQLite persistence for products, orders, contacts, and admin message links
- FastAPI static frontend and JSON API in one deployable service

## Tech Stack

- Python 3.11+
- FastAPI
- aiogram 3
- SQLite
- aiohttp
- Monobank merchant API
- Nova Poshta API
- python-dotenv
- Uvicorn

## Project Structure

```text
.
|-- main.py              # FastAPI app, Telegram bot, API endpoints, shop logic
|-- config.py            # Environment configuration helper
|-- database.py          # SQLAlchemy base/session helper
|-- models.py            # Order model prototype
|-- frontend/index.html  # Telegram Web App storefront and admin UI
|-- requirements.txt     # Python dependencies
`-- runtime.txt          # Runtime version for deployment
```

## Environment Variables

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
WEBAPP_URL=https://your-deployed-app.example.com
BOT_USERNAME=your_bot_username
ADMIN_IDS=123456789
MONO_TOKEN=your_monobank_token
NP_API_KEY=your_nova_poshta_api_key
DATABASE_PATH=shop.db
RUN_BOT=1
```

Required for a normal production run:

- `BOT_TOKEN`
- `WEBAPP_URL`
- one of `ADMIN_IDS`, `ADMIN_ID`, or `ADMIN_CHAT_ID`

Optional integrations:

- `MONO_TOKEN` enables Monobank invoice creation.
- `NP_API_KEY` enables Nova Poshta search and tracking.
- `DATABASE_PATH` lets cloud hosting use a mounted persistent path.

Do not commit real tokens, API keys, database files, or customer data.

## Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open the app:

```text
http://127.0.0.1:8000
```

For Telegram Web App testing, `WEBAPP_URL` must point to an HTTPS URL available to Telegram.

## Deployment Notes

- The app is designed for a single FastAPI process that also starts the Telegram bot.
- Use persistent storage for `shop.db` on cloud hosting.
- Set `RUN_BOT=0` only if you need to run the web API without Telegram polling.
- Run only one active polling instance per Telegram bot token.
