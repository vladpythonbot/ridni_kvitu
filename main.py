import asyncio
import json
import os
import uuid
import logging
import sqlite3
import urllib.request
import urllib.error
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
NP_API_KEY = os.getenv("NP_API_KEY", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")

if not BOT_TOKEN or not WEBAPP_URL:
    raise Exception("BOT_TOKEN або WEBAPP_URL не знайдено!")

WEBAPP_URL = WEBAPP_URL.rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ====================== БАЗА ======================
def db():
    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, price INTEGER NOT NULL, 
        emoji TEXT, active INTEGER DEFAULT 1)""")
    conn.commit()
    conn.close()

init_db()

def get_all_products():
    conn = db()
    rows = conn.execute("SELECT id, name, price, emoji FROM products WHERE active=1").fetchall()
    conn.close()
    return rows

# ====================== FASTAPI ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(start_bot())
    logger.info("✅ Сервер запущено")
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


@app.get("/api/products")
async def api_products():
    products = get_all_products()
    return [{"id": p["id"], "name": p["name"], "price": p["price"], "emoji": p["emoji"]} for p in products]


# ====================== BOT ======================
@dp.message(Command("start"))
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🫙 Відкрити магазин", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True
    )
    await message.answer("🌸 <b>Рідні квіти</b>", reply_markup=kb)


@dp.message(F.web_app_data)
async def webapp_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        # ... (твоя логіка збереження замовлення)
        await message.answer("✅ Замовлення отримано!\nМи скоро з вами зв'яжемося.")
    except Exception as e:
        logger.error(e)
        await message.answer("❌ Помилка оформлення.")


async def start_bot():
    logger.info("🤖 Бот запущений (polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))