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
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "").rstrip("/")
NP_API_KEY = os.getenv("NP_API_KEY", "").strip()
MONO_TOKEN = os.getenv("MONO_TOKEN", "").strip()
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "").strip()
RUN_BOT = os.getenv("RUN_BOT", "1") == "1"

if not BOT_TOKEN or not WEBAPP_URL:
    raise Exception("BOT_TOKEN або WEBAPP_URL не знайдено!")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()


def db():
    conn = sqlite3.connect("shop.db")
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(cur, table, column, definition):
    cur.execute(f"PRAGMA table_info({table})")
    columns = [row["name"] for row in cur.fetchall()]
    if column not in columns:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


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
            mono_invoice_id TEXT,
            mono_page_url TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            paid_at TEXT
        )
    """)

    ensure_column(cur, "orders", "phone_shared", "INTEGER DEFAULT 0")
    ensure_column(cur, "orders", "mono_invoice_id", "TEXT")
    ensure_column(cur, "orders", "mono_page_url", "TEXT")
    ensure_column(cur, "orders", "paid_at", "TEXT")

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
    rows = conn.execute("SELECT id, name, price, emoji FROM products WHERE active=1").fetchall()
    conn.close()
    return rows


def get_order(order_id):
    conn = db()
    row = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_order_by_invoice(invoice_id):
    conn = db()
    row = conn.execute("SELECT * FROM orders WHERE mono_invoice_id=?", (invoice_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_order(data):
    order_id = data.get("orderId") or os.urandom(4).hex()
    customer = data.get("customer") or {}
    delivery = data.get("delivery") or {}
    items = data.get("items") or []
    total = int(data.get("total") or 0)

    conn = db()
    conn.execute(
        """
        INSERT OR REPLACE INTO orders (
            id, tg_user_id, tg_username, name, phone, phone_shared,
            city, city_ref, warehouse, warehouse_ref,
            comment, items_json, total, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            "payment_waiting",
        ),
    )
    conn.commit()
    conn.close()
    return order_id


def update_order_payment(order_id, invoice_id=None, page_url=None, status=None):
    sets = []
    params = []
    if invoice_id is not None:
        sets.append("mono_invoice_id=?")
        params.append(invoice_id)
    if page_url is not None:
        sets.append("mono_page_url=?")
        params.append(page_url)
    if status is not None:
        sets.append("status=?")
        params.append(status)
        if status == "paid":
            sets.append("paid_at=CURRENT_TIMESTAMP")
    if not sets:
        return
    params.append(order_id)
    conn = db()
    conn.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()


def admin_panel_markup():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚙️ Відкрити адмін панель",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}?admin=1"),
        )
    ]])


def order_text(order_id, data_or_order, paid=False):
    if "items_json" in data_or_order:
        items = json.loads(data_or_order.get("items_json") or "[]")
        customer = {
            "name": data_or_order.get("name"),
            "phone": data_or_order.get("phone"),
            "phoneShared": bool(data_or_order.get("phone_shared")),
            "username": data_or_order.get("tg_username"),
        }
        delivery = {
            "city": data_or_order.get("city"),
            "warehouse": data_or_order.get("warehouse"),
        }
        total = data_or_order.get("total")
        comment = data_or_order.get("comment")
    else:
        items = data_or_order.get("items") or []
        customer = data_or_order.get("customer") or {}
        delivery = data_or_order.get("delivery") or {}
        total = data_or_order.get("total", 0)
        comment = data_or_order.get("comment")

    phone = customer.get("phone") or ("надіслано окремо в Telegram" if customer.get("phoneShared") else "—")
    title = "✅ <b>Оплачене замовлення</b>" if paid else "🧾 <b>Нове замовлення, очікує оплату</b>"
    lines = [
        f"{title} #{order_id}",
        "",
        f"👤 {customer.get('name') or '—'}",
        f"📞 {phone}",
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
        lines.append(f"{item.get('emoji', '🫙')} {item.get('name')} × {item.get('qty')} — {item.get('sum')} ₴")
    lines.extend(["", f"Разом: <b>{total} ₴</b>"])
    if comment:
        lines.extend(["", f"Коментар: {comment}"])
    return "\n".join(lines)


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
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Nova Poshta недоступна: {exc}") from exc

    if not data.get("success"):
        errors = ", ".join(data.get("errors") or [])
        warnings = ", ".join(data.get("warnings") or [])
        info = ", ".join(data.get("info") or [])
        raise RuntimeError(errors or warnings or info or "невідома помилка Nova Poshta")
    return data.get("data") or []


async def np_search_cities(query):
    try:
        data = await asyncio.to_thread(
            nova_poshta_request,
            "AddressGeneral",
            "searchSettlements",
            {"CityName": query, "Limit": "10", "Page": "1"},
        )
        addresses = []
        for item in data:
            addresses.extend(item.get("Addresses") or [])
        cities = [
            {
                "ref": x.get("DeliveryCity") or x.get("Ref"),
                "name": x.get("Present") or x.get("MainDescription"),
                "area": x.get("Area"),
            }
            for x in addresses
            if x.get("DeliveryCity") or x.get("Ref")
        ]
        if cities:
            return cities
    except Exception as exc:
        logger.warning("Nova Poshta searchSettlements failed, trying getSettlements: %s", exc)

    data = await asyncio.to_thread(
        nova_poshta_request,
        "AddressGeneral",
        "getSettlements",
        {"FindByString": query, "Warehouse": "1", "Limit": "10", "Page": "1"},
    )
    return [
        {
            "ref": x.get("Ref"),
            "name": ", ".join(
                part for part in [
                    x.get("SettlementTypeDescription"),
                    x.get("Description"),
                    x.get("AreaDescription"),
                    x.get("RegionsDescription"),
                ] if part
            ),
            "area": x.get("AreaDescription"),
        }
        for x in data
        if x.get("Ref") and x.get("Description")
    ]


async def np_search_warehouses(city_ref, query=""):
    props = {"CityRef": city_ref, "Limit": "30", "Page": "1"}
    if query:
        props["FindByString"] = query
    data = await asyncio.to_thread(nova_poshta_request, "AddressGeneral", "getWarehouses", props)
    return [
        {"ref": x.get("Ref"), "name": x.get("Description"), "number": x.get("Number")}
        for x in data
        if x.get("Ref") and x.get("Description")
    ]


# ====================== MONOBANK ======================
def monobank_request(path, payload):
    if not MONO_TOKEN:
        raise RuntimeError("MONO_TOKEN не налаштовано")

    req = urllib.request.Request(
        "https://api.monobank.ua" + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Token": MONO_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Monobank HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Monobank недоступний: {exc}") from exc


async def create_mono_invoice(order_id, data):
    total = int(data.get("total") or 0)
    items = data.get("items") or []
    payload = {
        "amount": total * 100,
        "ccy": 980,
        "redirectUrl": f"{WEBAPP_URL}?payment=done&orderId={order_id}",
        "webHookUrl": f"{WEBAPP_URL}/api/mono/webhook",
        "merchantPaymInfo": {
            "reference": order_id,
            "destination": f"Замовлення Рідні квіти #{order_id}",
            "basketOrder": [
                {
                    "name": item.get("name", "Товар"),
                    "qty": int(item.get("qty") or 1),
                    "sum": int(item.get("sum") or 0) * 100,
                    "code": str(item.get("id", "")),
                    "icon": item.get("emoji", "🫙"),
                    "unit": "шт.",
                }
                for item in items
            ],
        },
    }
    return await asyncio.to_thread(monobank_request, "/api/merchant/invoice/create", payload)


# ====================== FASTAPI ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    if RUN_BOT:
        asyncio.create_task(start_bot())
        logger.info("🤖 Бот запущений")
    else:
        logger.info("🌐 RUN_BOT=0, бот не запускається")
    logger.info("✅ Сервер запущено")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


@app.get("/payment-result")
async def payment_result():
    return PlainTextResponse("Дякуємо! Якщо оплата успішна, бот надішле підтвердження.")


@app.get("/api/products")
async def api_products():
    products = get_all_products()
    return [{"id": p["id"], "name": p["name"], "price": p["price"], "emoji": p["emoji"]} for p in products]


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


@app.post("/api/payment/create")
async def api_payment_create(request: Request):
    data = await request.json()
    order_id = save_order(data)

    try:
        invoice = await create_mono_invoice(order_id, data)
    except Exception as exc:
        logger.exception("Monobank invoice creation failed")
        return JSONResponse({"error": str(exc)}, status_code=502)

    invoice_id = invoice.get("invoiceId")
    page_url = invoice.get("pageUrl")
    if not invoice_id or not page_url:
        return JSONResponse({"error": "Monobank не повернув invoiceId/pageUrl"}, status_code=502)

    update_order_payment(order_id, invoice_id=invoice_id, page_url=page_url, status="payment_waiting")

    if ADMIN_CHAT_ID:
        await bot.send_message(
            int(ADMIN_CHAT_ID),
            order_text(order_id, data, paid=False),
            reply_markup=admin_panel_markup(),
        )

    return {"ok": True, "orderId": order_id, "invoiceId": invoice_id, "paymentUrl": page_url}


@app.post("/api/mono/webhook")
async def mono_webhook(request: Request):
    data = await request.json()
    invoice_id = data.get("invoiceId")
    status = data.get("status")
    order = get_order_by_invoice(invoice_id) if invoice_id else None
    if not order:
        logger.warning("Mono webhook for unknown invoice: %s", data)
        return {"ok": True}

    if status == "success" and order.get("status") != "paid":
        update_order_payment(order["id"], status="paid")
        paid_order = get_order(order["id"])

        if paid_order.get("tg_user_id"):
            await bot.send_message(
                int(paid_order["tg_user_id"]),
                f"✅ Оплату отримано!\nЗамовлення #{paid_order['id']} передано в обробку.",
            )
        if ADMIN_CHAT_ID:
            await bot.send_message(
                int(ADMIN_CHAT_ID),
                order_text(paid_order["id"], paid_order, paid=True),
                reply_markup=admin_panel_markup(),
            )
    elif status in {"failure", "expired", "reversed"}:
        update_order_payment(order["id"], status=status)

    return {"ok": True}


# ====================== BOT ======================
@dp.message(Command("start"))
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🫙 Відкрити магазин", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )
    await message.answer("🌸 <b>Рідні квіти</b>", reply_markup=kb)


@dp.message(Command("admin"))
async def admin(message: types.Message):
    if ADMIN_CHAT_ID and str(message.from_user.id) != str(ADMIN_CHAT_ID):
        await message.answer("⛔ Доступ заборонено")
        return
    await message.answer("Адмін панель:", reply_markup=admin_panel_markup())


@dp.message(F.contact)
async def contact_received(message: types.Message):
    contact = message.contact
    if not contact or not contact.phone_number:
        return
    await message.answer(
        f"✅ Телефон отримано: {contact.phone_number}\n"
        "Тепер можете повернутися до оформлення замовлення."
    )


@dp.message(F.web_app_data)
async def webapp_data(message: types.Message):
    await message.answer("✅ Дані отримано. Якщо оплата пройде успішно, ви отримаєте підтвердження.")


async def start_bot():
    logger.info("Start polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))