import asyncio
import json
import os
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
NP_API_KEY = os.getenv("NP_API_KEY", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")

if not BOT_TOKEN or not WEBAPP_URL:
    raise Exception("BOT_TOKEN або WEBAPP_URL не знайдено!")

WEBAPP_URL = WEBAPP_URL.rstrip("/")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()


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

    cur.execute("SELECT COUNT(*) AS count FROM products")
    if cur.fetchone()["count"] == 0:
        cur.executemany(
            "INSERT INTO products (id, name, price, emoji) VALUES (?, ?, ?, ?)",
            [
                (1, "Варення з чорнобривців", 150, "🌼"),
                (2, "Варення з м'яти", 150, "🌿"),
                (3, "Варення з фіалки лісової", 150, "💜"),
                (4, "Імеретинський шафран", 150, "🟡"),
            ],
        )

    conn.commit()
    conn.close()


init_db()


def get_all_products():
    conn = db()
    rows = conn.execute(
        "SELECT id, name, price, emoji FROM products WHERE active=1"
    ).fetchall()
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
            id, tg_user_id, tg_username, name, phone,
            city, city_ref, warehouse, warehouse_ref,
            comment, items_json, total
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            customer.get("telegramId"),
            customer.get("username"),
            customer.get("name"),
            customer.get("phone"),
            delivery.get("city"),
            delivery.get("cityRef"),
            delivery.get("warehouse"),
            delivery.get("warehouseRef"),
            data.get("comment", ""),
            json.dumps(items, ensure_ascii=False),
            total,
        ),
    )
    conn.commit()
    conn.close()
    return order_id


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
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Nova Poshta недоступна: {exc}") from exc

    if not data.get("success"):
        errors = ", ".join(data.get("errors") or ["невідома помилка"])
        raise RuntimeError(errors)

    return data.get("data") or []


async def np_search_cities(query):
    data = await asyncio.to_thread(
        nova_poshta_request,
        "AddressGeneral",
        "searchSettlements",
        {"CityName": query, "Limit": "10", "Page": "1"},
    )

    addresses = []
    for item in data:
        addresses.extend(item.get("Addresses") or [])

    return [
        {
            "ref": x.get("DeliveryCity") or x.get("Ref"),
            "name": x.get("Present") or x.get("MainDescription"),
            "area": x.get("Area"),
        }
        for x in addresses
        if x.get("DeliveryCity") or x.get("Ref")
    ]


async def np_search_warehouses(city_ref, query=""):
    props = {"CityRef": city_ref, "Limit": "30", "Page": "1"}
    if query:
        props["FindByString"] = query

    data = await asyncio.to_thread(
        nova_poshta_request,
        "AddressGeneral",
        "getWarehouses",
        props,
    )

    return [
        {
            "ref": x.get("Ref"),
            "name": x.get("Description"),
            "number": x.get("Number"),
        }
        for x in data
        if x.get("Ref") and x.get("Description")
    ]


def order_text(order_id, data):
    customer = data.get("customer") or {}
    delivery = data.get("delivery") or {}
    items = data.get("items") or []

    lines = [
        f"🧾 <b>Нове замовлення #{order_id}</b>",
        "",
        f"👤 {customer.get('name') or '—'}",
        f"📞 {customer.get('phone') or '—'}",
    ]

    if customer.get("username"):
        lines.append(f"💬 @{customer.get('username')}")

    lines.extend([
        "",
        f"🏙 {delivery.get('city') or '—'}",
        f"📦 {delivery.get('warehouse') or '—'}",
        "",
        "<b>Товари:</b>",
    ])

    for item in items:
        lines.append(
            f"{item.get('emoji', '🫙')} {item.get('name')} × {item.get('qty')} — {item.get('sum')} ₴"
        )

    lines.extend(["", f"Разом: <b>{data.get('total', 0)} ₴</b>"])

    if data.get("comment"):
        lines.extend(["", f"Коментар: {data.get('comment')}"])

    return "\n".join(lines)


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(start_bot())
    logger.info("✅ Сервер запущено")
    yield


app = FastAPI(lifespan=lifespan)

if os.path.isdir("frontend"):
    app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.get("/")
async def index():
    if os.path.exists("frontend/index.html"):
        return FileResponse("frontend/index.html")
    return FileResponse("index.html")


@app.get("/api/products")
async def api_products():
    products = get_all_products()
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "price": p["price"],
            "emoji": p["emoji"],
        }
        for p in products
    ]


@app.get("/api/np/cities")
async def api_np_cities(q: str = ""):
    q = q.strip()
    if len(q) < 2:
        return []

    try:
        return await np_search_cities(q)
    except Exception as exc:
        logger.exception("Nova Poshta city search failed")
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.get("/api/np/warehouses")
async def api_np_warehouses(cityRef: str, q: str = ""):
    if not cityRef:
        return []

    try:
        return await np_search_warehouses(cityRef, q.strip())
    except Exception as exc:
        logger.exception("Nova Poshta warehouse search failed")
        return JSONResponse({"error": str(exc)}, status_code=502)


@app.post("/api/order")
async def api_order(request: Request):
    data = await request.json()
    order_id = save_order(data)

    if ADMIN_CHAT_ID:
        await bot.send_message(int(ADMIN_CHAT_ID), order_text(order_id, data))

    return {"ok": True, "orderId": order_id}


@dp.message(Command("start"))
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🫙 Відкрити магазин",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ],
        resize_keyboard=True,
    )
    await message.answer("🌸 Рідні квіти", reply_markup=kb)


@dp.message(F.web_app_data)
async def webapp_data(message: types.Message):
    try:
        data = json.loads(message.web_app_data.data)
        order_id = save_order(data)

        await message.answer("✅ Замовлення отримано!\nМи скоро звʼяжемося з вами.")

        if ADMIN_CHAT_ID:
            await bot.send_message(int(ADMIN_CHAT_ID), order_text(order_id, data))
    except Exception:
        logger.exception("WebApp data error")
        await message.answer("❌ Помилка під час оформлення замовлення")


async def start_bot():
    logger.info("🤖 Бот запущений")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))