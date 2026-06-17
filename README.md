# Ridni Kvitu

Telegram-bot and mini app for a small flower shop. The project combines a product catalog, admin tools, PostgreSQL storage, and a lightweight web interface for presenting bouquets.

## Features

- Product catalog inside Telegram
- Product cards with photo, description, and price
- Admin panel for adding and deleting products
- PostgreSQL database initialization on startup
- Separate user and admin routers
- Telegram Mini App / web catalog prototype
- Clean environment-based configuration

## Tech Stack

- Python 3.11+
- aiogram 3
- asyncpg
- PostgreSQL / Supabase
- python-dotenv
- Vite + React for the web app prototype

## Project Structure

```text
.
├── main.py                  # Bot entry point
├── bot.py                   # Telegram bot instance
├── db/                      # Database connection and queries
├── routers/                 # User and admin bot logic
├── keyboards/               # Reply and inline keyboards
├── ridni-kvitu-miniapp/     # Simple static mini app
└── ridni-kvitu-app/         # React/Vite app prototype
```

## Environment Variables

Create a `.env` file in the project root:

```env
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=your_postgresql_connection_url
```

Do not commit real tokens, database URLs, or admin credentials.

## Run Locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

For the React app:

```bash
cd ridni-kvitu-app
npm install
npm run dev
```

## Notes

The bot uses long polling. For production deployment, set environment variables in the hosting dashboard and connect a persistent PostgreSQL database.
