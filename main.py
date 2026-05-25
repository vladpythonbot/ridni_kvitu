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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            tg_user_id INTEGER,
            tg_username TEXT,
            name TEXT,
            phone TEXT,
            phone_shared INTEGER DEFAULT 0,
            city TEXT,
            city_ref TEXT,
            warehouse TEXT,
            warehouse_ref TEXT,
            comment TEXT,
            items_json TEXT NOT NULL,
            total INTEGER NOT NULL,
            status TEXT DEFAULT 'new',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Дефолтні товари
    cur.execute("SELECT COUNT(*) as count FROM products")
    if cur.fetchone()["count"] == 0:
        cur.executemany(
            "INSERT INTO products (name, price, emoji) VALUES (?, ?, ?)",
            [
                ("Варення з чорнобривців", 150, "🌼"),
                ("Варення з м'яти", 150, "🌿"),
                ("Варення з фіалки", 180, "💜"),
                ("Імеретинський шафран", 160, "🟡"),
            ]
        )

    conn.commit()
    conn.close()


init_db()


def get_all_products():
    conn = db()
    rows = conn.execute("SELECT id, name, price, emoji FROM products WHERE active=1").fetchall()
    conn.close()
    return rows


def save_order(data):
    order_id = data.get("orderId") or os.urandom(4).hex()
    customer = data.get("customer") or {}
    delivery = data.get("delivery") or {}
    items = data.get("items") or []
    total = int(data.get("total") or 0)

    conn = db()
    conn.execute(
        """
        INSERT INTO orders (
            id, tg_user_id, tg_username, name, phone, phone_shared,
            city, city_ref, warehouse, warehouse_ref, comment, items_json, total
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            customer.get("telegramId"),
            customer.get("username"),
            customer.get("name"),
            customer.get("phone", ""),
            1 if customer.get("phoneShared") else 0,
            delivery.get("city"),
            delivery.get("cityRef"),
            delivery.get("warehouse"),
            delivery.get("warehouseRef"),
            data.get("comment", ""),
            json.dumps(items, ensure_ascii=False),
            total,
        )
    )
    conn.commit()
    conn.close()
    return order_id


# ====================== NOVA POSHTA ======================
def nova_poshta_request(model_name, called_method, method_properties):
    if not NP_API_KEY:
        raise RuntimeError("NP_API_KEY не налаштовано")

    payload = {
        "apiKey": NP_API_KEY,
        "modelName": model_name,
        "calledMethod": called_method,
        "methodProperties": method_properties,
    }

    req = urllib.request.Request(
        "https://api.novaposhta.ua/v2.0/json/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as res:
            data = json.loads(res.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Nova Poshta error: {exc}")

    if not data.get("success"):
        raise RuntimeError(", ".join(data.get("errors") or ["Невідома помилка"]))

    return data.get("data") or []


async def np_search_cities(query: str):
    try:
        data = await asyncio.to_thread(
            nova_poshta_request, "AddressGeneral", "searchSettlements",
            {"CityName": query, "Limit": "10"}
        )
        # ... (твій код обробки)
        return data  # спростив для прикладу
    except Exception as e:
        logger.warning(e)
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
    return [{"id": p["id"], "name": p["name"], "price": p["price"], "emoji": p["emoji"]} for p in products]


@app.get("/api/np/cities")
async def api_np_cities(q: str = ""):
    if len(q) < 2:
        return []
    try:
        return await np_search_cities(q)
    except Exception as e:
        logger.error(e)
        return JSONResponse({"error": "Помилка Нової Пошти"}, status_code=502)


@app.post("/api/order")
async def api_order(request: Request):
    data = await request.json()
    order_id = save_order(data)

    if ADMIN_CHAT_ID:
        # Тут можна відправити повідомлення адміну
        pass

    return {"ok": True, "orderId": order_id}


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
        order_id = save_order(data)

        await message.answer("✅ Замовлення успішно оформлено!\nМи скоро з вами зв'яжемося.")

        if ADMIN_CHAT_ID:
            await bot.send_message(int(ADMIN_CHAT_ID), f"Нове замовлення #{order_id}")
    except Exception as e:
        logger.error(e)
        await message.answer("❌ Помилка оформлення замовлення.")


async def start_bot():
    logger.info("🤖 Бот запущений")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))