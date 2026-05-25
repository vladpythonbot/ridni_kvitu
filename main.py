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


# ====================== БАЗА ДАНИХ ======================
def db():
    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            emoji TEXT,
            active INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    conn.close()

init_db()

def get_all_products():
    conn = db()
    rows = conn.execute("SELECT id, name, price, emoji FROM products WHERE active=1").fetchall()
    conn.close()
    return rows


# ====================== NOVA POSHTA ======================
def nova_poshta_request(model_name, called_method, method_properties):
    if not NP_API_KEY:
        return []

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": model_name,
        "calledMethod": called_method,
        "methodProperties": method_properties,
    }

    try:
        req = urllib.request.Request(
            "https://api.novaposhta.ua/v2.0/json/",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            data = json.loads(res.read().decode("utf-8"))
        return data.get("data") or []
    except Exception as e:
        logger.error(f"Nova Poshta error: {e}")
        return []


async def np_search_cities(query: str):
    if len(query) < 2:
        return []
    try:
        return await asyncio.to_thread(
            nova_poshta_request,
            "AddressGeneral",
            "searchSettlements",
            {"CityName": query, "Limit": "10"}
        )
    except:
        return []


async def np_search_warehouses(city_ref: str, query: str = ""):
    if not city_ref:
        return []
    try:
        return await asyncio.to_thread(
            nova_poshta_request,
            "AddressGeneral",
            "getWarehouses",
            {"CityRef": city_ref, "Limit": "30"}
        )
    except:
        return []


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
    return [{"id": p[0], "name": p[1], "price": p[2], "emoji": p[3]} for p in products]


@app.get("/api/np/cities")
async def api_np_cities(q: str = ""):
    return await np_search_cities(q)


@app.get("/api/np/warehouses")
async def api_np_warehouses(cityRef: str, q: str = ""):
    return await np_search_warehouses(cityRef, q)


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
        await message.answer("✅ Замовлення отримано!\nМи скоро з вами зв'яжемося.")
    except Exception as e:
        logger.error(e)
        await message.answer("❌ Помилка оформлення.")


async def start_bot():
    logger.info("🤖 Бот запущений")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))