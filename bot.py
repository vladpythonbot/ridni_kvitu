import asyncio
import json
import os
import uuid
import logging
import sqlite3
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

load_dotenv()

# ====================== НАЛАШТУВАННЯ ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))   # ← Зміни в .env

if not BOT_TOKEN or not WEBAPP_URL:
    raise Exception("BOT_TOKEN або WEBAPP_URL не знайдено в .env!")

WEBAPP_URL = WEBAPP_URL.rstrip("/")

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()

# ====================== БАЗА ДАНИХ ======================
def init_db():
    conn = sqlite3.connect("shop.db")
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
    conn = sqlite3.connect("shop.db")
    cur = conn.cursor()
    cur.execute("SELECT id, name, price, emoji FROM products WHERE active=1")
    products = cur.fetchall()
    conn.close()
    return products

def add_product(name: str, price: int, emoji: str = "🫙"):
    conn = sqlite3.connect("shop.db")
    cur = conn.cursor()
    cur.execute("INSERT INTO products (name, price, emoji) VALUES (?, ?, ?)", (name, price, emoji))
    conn.commit()
    prod_id = cur.lastrowid
    conn.close()
    return prod_id

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


# Адмін API для додавання товару
@app.post("/api/admin/add_product")
async def admin_add_product(request: Request):
    try:
        data = await request.json()
        user_id = data.get("userId")

        if user_id != ADMIN_ID:
            return JSONResponse({"error": "Access denied"}, status_code=403)

        name = data.get("name")
        price = int(data.get("price"))
        emoji = data.get("emoji", "🫙")

        if not name or not price:
            return JSONResponse({"error": "Invalid data"}, status_code=400)

        prod_id = add_product(name, price, emoji)
        return {"success": True, "id": prod_id}

    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


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
        items = data.get("items", [])
        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        address = str(data.get("address", "")).strip()

        if not name or not phone or not address:
            return await message.answer("❌ Заповніть усі поля!")

        total = 0
        order_list = []

        for item in items:
            prod = next((p for p in get_all_products() if p[0] == int(item["id"])), None)
            if prod:
                qty = int(item["qty"])
                total += prod[2] * qty
                order_list.append(f"{prod[1]} × {qty}")

        if total < 10:
            return await message.answer("❌ Мінімальна сума — 10 грн")

        order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

        await message.answer(f"""
✅ <b>Замовлення #{order_id}</b> прийнято!

👤 {name}
📞 {phone}
🏠 {address}
💰 Сума: <b>{total} ₴</b>

📋 {chr(10).join(order_list)}
""")

    except Exception as e:
        logger.error(e)
        await message.answer("❌ Помилка обробки замовлення.")


async def start_bot():
    logger.info("🤖 Бот запущений")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))