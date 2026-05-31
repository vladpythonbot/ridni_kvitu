import asyncio
import hashlib
import hmac
import json
import os
import logging
import shutil
import sqlite3
import urllib.request
import urllib.error
import urllib.parse
import time
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN") or ""
WEBAPP_URL = (os.getenv("WEBAPP_URL") or "").rstrip("/")
NP_API_KEY = os.getenv("NP_API_KEY", "").strip()
MONO_TOKEN = os.getenv("MONO_TOKEN", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "shop.db").strip() or "shop.db"
NP_TRACKING_INTERVAL_SECONDS = int(os.getenv("NP_TRACKING_INTERVAL_SECONDS", "1800"))
ADMIN_IDS = {
    item.strip()
    for item in (os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or os.getenv("ADMIN_CHAT_ID") or "").split(",")
    if item.strip()
}
RUN_BOT = os.getenv("RUN_BOT", "1") == "1"

if not BOT_TOKEN or not WEBAPP_URL:
    raise Exception("BOT_TOKEN або WEBAPP_URL не знайдено!")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()


def db():
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    if DATABASE_PATH != "shop.db" and not os.path.exists(DATABASE_PATH) and os.path.exists("shop.db"):
        shutil.copyfile("shop.db", DATABASE_PATH)
    conn = sqlite3.connect(DATABASE_PATH)
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
            volume TEXT DEFAULT '30 мл',
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            tg_user_id INTEGER,
            tg_username TEXT,
            tg_first_name TEXT,
            tg_last_name TEXT,
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
            paid_at TEXT,
            received_at TEXT,
            hidden_at TEXT,
            np_ttn TEXT,
            np_status TEXT,
            np_status_code TEXT,
            np_checked_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_contacts (
            tg_user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            phone TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_order_messages (
            order_id TEXT NOT NULL,
            admin_id TEXT NOT NULL,
            message_id INTEGER NOT NULL,
            PRIMARY KEY (order_id, admin_id)
        )
    """)

    ensure_column(cur, "products", "volume", "TEXT DEFAULT '30 мл'")
    ensure_column(cur, "orders", "tg_first_name", "TEXT")
    ensure_column(cur, "orders", "tg_last_name", "TEXT")
    ensure_column(cur, "orders", "phone_shared", "INTEGER DEFAULT 0")
    ensure_column(cur, "orders", "mono_invoice_id", "TEXT")
    ensure_column(cur, "orders", "mono_page_url", "TEXT")
    ensure_column(cur, "orders", "paid_at", "TEXT")
    ensure_column(cur, "orders", "received_at", "TEXT")
    ensure_column(cur, "orders", "hidden_at", "TEXT")
    ensure_column(cur, "orders", "np_ttn", "TEXT")
    ensure_column(cur, "orders", "np_status", "TEXT")
    ensure_column(cur, "orders", "np_status_code", "TEXT")
    ensure_column(cur, "orders", "np_checked_at", "TEXT")

    cur.execute("SELECT COUNT(*) AS count FROM products")
    if cur.fetchone()["count"] == 0:
        cur.executemany(
            "INSERT INTO products (id, name, price, emoji, volume) VALUES (?, ?, ?, ?, ?)",
            [
                (1, "Варення з чорнобривців", 150, "🌼", "30 мл"),
                (2, "Варення з м'яти", 150, "🌿", "30 мл"),
                (3, "Варення з фіалки лісової", 150, "💜", "30 мл"),
                (4, "Імеретинський шафран", 150, "🟡", "30 мл"),
            ],
        )

    conn.commit()
    conn.close()


init_db()


def get_all_products():
    conn = db()
    rows = conn.execute("SELECT id, name, price, emoji, volume FROM products WHERE active=1").fetchall()
    conn.close()
    return rows


def product_row_to_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "price": row["price"],
        "emoji": row["emoji"] or "🫙",
        "volume": row["volume"] or "30 мл",
    }


def create_product(name, price, emoji, volume):
    conn = db()
    cur = conn.execute(
        "INSERT INTO products (name, price, emoji, volume, active) VALUES (?, ?, ?, ?, 1)",
        (name, price, emoji or "🫙", volume or "30 мл"),
    )
    conn.commit()
    row = conn.execute("SELECT id, name, price, emoji, volume FROM products WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return product_row_to_dict(row)


def update_product(product_id, name=None, price=None, emoji=None, volume=None):
    sets = []
    params = []
    if name is not None:
        sets.append("name=?")
        params.append(name)
    if price is not None:
        sets.append("price=?")
        params.append(price)
    if emoji is not None:
        sets.append("emoji=?")
        params.append(emoji or "🫙")
    if volume is not None:
        sets.append("volume=?")
        params.append(volume or "30 мл")
    if not sets:
        return None

    params.append(product_id)
    conn = db()
    conn.execute(f"UPDATE products SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    row = conn.execute(
        "SELECT id, name, price, emoji, volume FROM products WHERE id=? AND active=1",
        (product_id,),
    ).fetchone()
    conn.close()
    return product_row_to_dict(row) if row else None


def hide_product(product_id):
    conn = db()
    cur = conn.execute("UPDATE products SET active=0 WHERE id=?", (product_id,))
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


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


def save_user_contact(tg_user_id, first_name, last_name, phone):
    conn = db()
    conn.execute(
        """
        INSERT INTO user_contacts (tg_user_id, first_name, last_name, phone, updated_at)
        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(tg_user_id) DO UPDATE SET
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            phone=excluded.phone,
            updated_at=CURRENT_TIMESTAMP
        """,
        (tg_user_id, first_name or "", last_name or "", phone),
    )
    conn.commit()
    conn.close()


def get_saved_contact(tg_user_id):
    if not tg_user_id:
        return None
    conn = db()
    row = conn.execute(
        "SELECT first_name, last_name, phone FROM user_contacts WHERE tg_user_id=?",
        (tg_user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def save_order(data):
    order_id = data.get("orderId") or os.urandom(4).hex()
    customer = data.get("customer") or {}
    delivery = data.get("delivery") or {}
    items = data.get("items") or []
    total = int(data.get("total") or 0)
    tg_user_id = customer.get("telegramId")
    phone = customer.get("phone", "")
    saved_contact = get_saved_contact(tg_user_id)
    if customer.get("phoneShared") and not phone and saved_contact:
        phone = saved_contact.get("phone", "")
    name = customer.get("name")
    if (not name or not str(name).strip()) and saved_contact:
        name = " ".join(
            part for part in [saved_contact.get("first_name"), saved_contact.get("last_name")] if part
        )

    conn = db()
    conn.execute(
        """
        INSERT OR REPLACE INTO orders (
            id, tg_user_id, tg_username, tg_first_name, tg_last_name, name, phone, phone_shared,
            city, city_ref, warehouse, warehouse_ref,
            comment, items_json, total, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            order_id,
            tg_user_id,
            customer.get("username"),
            customer.get("firstName"),
            customer.get("lastName"),
            name,
            phone,
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
        if status == "received":
            sets.append("received_at=CURRENT_TIMESTAMP")
    if not sets:
        return
    params.append(order_id)
    conn = db()
    conn.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()


def update_order_np(order_id, ttn=None, np_status=None, np_status_code=None, mark_checked=False):
    sets = []
    params = []
    if ttn is not None:
        sets.append("np_ttn=?")
        params.append(ttn)
    if np_status is not None:
        sets.append("np_status=?")
        params.append(np_status)
    if np_status_code is not None:
        sets.append("np_status_code=?")
        params.append(str(np_status_code))
    if mark_checked:
        sets.append("np_checked_at=CURRENT_TIMESTAMP")
    if not sets:
        return
    params.append(order_id)
    conn = db()
    conn.execute(f"UPDATE orders SET {', '.join(sets)} WHERE id=?", params)
    conn.commit()
    conn.close()


def save_admin_order_message(order_id, admin_id, message_id):
    conn = db()
    conn.execute(
        """
        INSERT INTO admin_order_messages (order_id, admin_id, message_id)
        VALUES (?, ?, ?)
        ON CONFLICT(order_id, admin_id) DO UPDATE SET
            message_id=excluded.message_id
        """,
        (order_id, str(admin_id), message_id),
    )
    conn.commit()
    conn.close()


def get_admin_order_message(order_id, admin_id):
    conn = db()
    row = conn.execute(
        "SELECT message_id FROM admin_order_messages WHERE order_id=? AND admin_id=?",
        (order_id, str(admin_id)),
    ).fetchone()
    conn.close()
    return row["message_id"] if row else None


def admin_panel_markup():
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="⚙️ Відкрити адмін панель",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )
    ]])


def join_api_messages(value):
    if not value:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def verify_telegram_init_data(init_data):
    if not init_data:
        return None

    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    received_hash = parsed.pop("hash", None)
    if not received_hash:
        return None

    auth_date = int(parsed.get("auth_date") or 0)
    if auth_date and time.time() - auth_date > 60 * 60 * 24:
        return None

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(parsed.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, str(received_hash)):
        return None

    try:
        return json.loads(parsed.get("user") or "{}")
    except json.JSONDecodeError:
        return None


def admin_from_request(request):
    user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if not user:
        return None
    if str(user.get("id")) in ADMIN_IDS:
        return user
    return None


async def send_admin_message(text, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(int(admin_id), text, reply_markup=reply_markup)
        except TelegramBadRequest as exc:
            logger.warning(
                "Cannot send admin message to %s: %s. Check ADMIN_IDS and make sure this account pressed /start.",
                admin_id,
                exc.message,
            )
        except Exception:
            logger.exception("Failed to send admin message to %s", admin_id)


async def send_or_edit_admin_order_message(order_id, text, reply_markup=None, edit=False):
    for admin_id in ADMIN_IDS:
        try:
            message_id = get_admin_order_message(order_id, admin_id) if edit else None
            if message_id:
                try:
                    await bot.edit_message_text(
                        text,
                        chat_id=int(admin_id),
                        message_id=int(message_id),
                        reply_markup=reply_markup,
                    )
                    continue
                except TelegramBadRequest as exc:
                    if "message is not modified" in exc.message.lower():
                        continue
                    logger.warning("Could not edit admin order message %s/%s: %s", order_id, admin_id, exc.message)

            sent = await bot.send_message(int(admin_id), text, reply_markup=reply_markup)
            save_admin_order_message(order_id, admin_id, sent.message_id)
        except TelegramBadRequest as exc:
            logger.warning(
                "Cannot send admin order message to %s: %s. Check ADMIN_IDS and make sure this account pressed /start.",
                admin_id,
                exc.message,
            )
        except Exception:
            logger.exception("Failed to send/edit admin order message to %s", admin_id)


def order_text(order_id, data_or_order, paid=False):
    if "items_json" in data_or_order:
        items = json.loads(data_or_order.get("items_json") or "[]")
        customer = {
            "name": data_or_order.get("name"),
            "phone": data_or_order.get("phone"),
            "phoneShared": bool(data_or_order.get("phone_shared")),
            "username": data_or_order.get("tg_username"),
            "firstName": data_or_order.get("tg_first_name"),
            "lastName": data_or_order.get("tg_last_name"),
        }
        delivery = {
            "city": data_or_order.get("city"),
            "warehouse": data_or_order.get("warehouse"),
            "npTtn": data_or_order.get("np_ttn"),
            "npStatus": data_or_order.get("np_status"),
            "npStatusCode": data_or_order.get("np_status_code"),
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
        f"👤 {customer.get('name') or ' '.join(part for part in [customer.get('firstName'), customer.get('lastName')] if part) or '—'}",
        f"📞 {phone}",
    ]
    if customer.get("username"):
        lines.append(f"💬 @{customer.get('username')}")
    lines.extend([
        "",
        f"🏙 {delivery.get('city') or '—'}",
        f"📦 {delivery.get('warehouse') or '—'}",
        *(["ТТН: " + str(delivery.get("npTtn"))] if delivery.get("npTtn") else []),
        *(["НП: " + str(delivery.get("npStatus"))] if delivery.get("npStatus") else []),
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
        errors = join_api_messages(data.get("errors"))
        warnings = join_api_messages(data.get("warnings"))
        info = join_api_messages(data.get("info"))
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


def normalize_phone_for_np(phone):
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("380") and len(digits) == 12:
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return "38" + digits
    return digits


def np_status_is_received(status, status_code):
    code = str(status_code or "").strip()
    text = str(status or "").lower()
    return code in {"9", "10", "11"} or "отрим" in text or "получ" in text


async def np_tracking_status(ttn, phone=""):
    document = {"DocumentNumber": str(ttn).strip()}
    normalized_phone = normalize_phone_for_np(phone)
    if normalized_phone:
        document["Phone"] = normalized_phone

    data = await asyncio.to_thread(
        nova_poshta_request,
        "TrackingDocument",
        "getStatusDocuments",
        {"Documents": [document]},
    )
    if not data:
        raise RuntimeError("Nova Poshta не повернула статус посилки")

    item = data[0]
    return {
        "ttn": item.get("Number") or ttn,
        "status": item.get("Status") or item.get("StatusDescription") or "",
        "statusCode": item.get("StatusCode") or "",
    }


async def refresh_order_np_status(order_id):
    order = get_order(order_id)
    if not order:
        raise RuntimeError("Замовлення не знайдено")
    ttn = str(order.get("np_ttn") or "").strip()
    if not ttn:
        raise RuntimeError("Спочатку додайте ТТН")

    status = await np_tracking_status(ttn, order.get("phone"))
    update_order_np(
        order_id,
        ttn=status["ttn"],
        np_status=status["status"],
        np_status_code=status["statusCode"],
        mark_checked=True,
    )

    if np_status_is_received(status["status"], status["statusCode"]):
        update_order_payment(order_id, status="received")

    updated_order = get_order(order_id)
    await send_or_edit_admin_order_message(
        order_id,
        order_text(order_id, updated_order, paid=updated_order.get("status") in {"paid", "received"}),
        reply_markup=admin_panel_markup(),
        edit=True,
    )

    if updated_order and updated_order.get("status") == "received" and updated_order.get("tg_user_id") and order.get("status") != "received":
        try:
            await bot.send_message(
                int(updated_order["tg_user_id"]),
                f"📦 Замовлення #{order_id} отримано. Дякуємо, що обрали Рідні квіти!",
            )
        except Exception:
            logger.exception("Failed to notify user about NP received order %s", order_id)

    return updated_order


async def np_tracking_worker():
    if not NP_API_KEY:
        logger.info("Nova Poshta tracking disabled: NP_API_KEY is not set")
        return

    while True:
        await asyncio.sleep(max(NP_TRACKING_INTERVAL_SECONDS, 300))
        try:
            conn = db()
            rows = conn.execute(
                """
                SELECT id
                FROM orders
                WHERE hidden_at IS NULL
                  AND np_ttn IS NOT NULL
                  AND TRIM(np_ttn) != ''
                  AND status != 'received'
                ORDER BY COALESCE(np_checked_at, '1970-01-01') ASC
                LIMIT 20
                """
            ).fetchall()
            conn.close()

            for row in rows:
                try:
                    await refresh_order_np_status(row["id"])
                    await asyncio.sleep(1)
                except Exception:
                    logger.exception("Nova Poshta tracking failed for order %s", row["id"])
        except Exception:
            logger.exception("Nova Poshta tracking worker failed")


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


def monobank_get(path, query):
    if not MONO_TOKEN:
        raise RuntimeError("MONO_TOKEN не налаштовано")

    url = "https://api.monobank.ua" + path + "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(
        url,
        headers={"X-Token": MONO_TOKEN},
        method="GET",
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


async def get_mono_invoice_status(invoice_id):
    return await asyncio.to_thread(
        monobank_get,
        "/api/merchant/invoice/status",
        {"invoiceId": invoice_id},
    )


# ====================== FASTAPI ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    _ = app
    if RUN_BOT:
        await configure_bot_profile()
        asyncio.create_task(start_bot())
        asyncio.create_task(np_tracking_worker())
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
    return [product_row_to_dict(p) for p in products]


@app.get("/api/contact/me")
async def api_contact_me(request: Request):
    user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    tg_user_id = user.get("id") if user else request.headers.get("X-Telegram-User-Id")
    if not tg_user_id:
        return JSONResponse({"error": "Telegram користувача не підтверджено"}, status_code=403)

    contact = get_saved_contact(tg_user_id)
    if not contact:
        return {"phone": "", "name": ""}

    name = " ".join(part for part in [contact.get("first_name"), contact.get("last_name")] if part)
    return {"phone": contact.get("phone", ""), "name": name}


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
    saved_order = get_order(order_id)

    await send_or_edit_admin_order_message(
        order_id,
        order_text(order_id, saved_order or data, paid=False),
        reply_markup=admin_panel_markup(),
    )

    return {"ok": True, "orderId": order_id, "invoiceId": invoice_id, "paymentUrl": page_url}


@app.get("/api/payment/status")
async def api_payment_status(orderId: str):
    order = get_order(orderId)
    if not order:
        return JSONResponse({"error": "Замовлення не знайдено"}, status_code=404)

    invoice_id = order.get("mono_invoice_id")
    if not invoice_id:
        return {"ok": True, "orderId": orderId, "status": order.get("status"), "paymentUrl": order.get("mono_page_url")}

    try:
        mono_status = await get_mono_invoice_status(invoice_id)
    except Exception as exc:
        logger.exception("Monobank status check failed")
        return JSONResponse({"error": str(exc)}, status_code=502)

    status = mono_status.get("status")
    if status == "success" and order.get("status") != "paid":
        update_order_payment(orderId, status="paid")
        order = get_order(orderId)
        if order and order.get("tg_user_id"):
            await bot.send_message(
                int(order["tg_user_id"]),
                f"✅ Оплату отримано!\nЗамовлення #{order['id']} передано в обробку.",
            )
        if order:
            await send_or_edit_admin_order_message(
                order["id"],
                order_text(order["id"], order, paid=True),
                reply_markup=admin_panel_markup(),
                edit=True,
            )
    elif status in {"failure", "expired", "reversed"} and order.get("status") != status:
        update_order_payment(orderId, status=status)

    updated_order = get_order(orderId)
    return {
        "ok": True,
        "orderId": orderId,
        "status": updated_order.get("status") if updated_order else order.get("status"),
        "monoStatus": status,
        "paymentUrl": order.get("mono_page_url"),
    }


@app.get("/api/admin/me")
async def api_admin_me(request: Request):
    user = admin_from_request(request)
    return {
        "isAdmin": bool(user),
        "user": {
            "id": user.get("id"),
            "firstName": user.get("first_name"),
            "username": user.get("username"),
        } if user else None,
    }


@app.get("/api/admin/orders")
async def api_admin_orders(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    conn = db()
    rows = conn.execute(
        """
        SELECT id, tg_user_id, tg_username, tg_first_name, tg_last_name, name, phone, phone_shared, city, warehouse,
               items_json, total, status, created_at, paid_at, received_at,
               np_ttn, np_status, np_status_code, np_checked_at
        FROM orders
        WHERE hidden_at IS NULL
        ORDER BY created_at DESC
        LIMIT 50
        """
    ).fetchall()
    conn.close()

    orders: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = dict(row)
        try:
            item["items"] = json.loads(item.pop("items_json") or "[]")
        except json.JSONDecodeError:
            item["items"] = []
        orders.append(item)

    return {"orders": orders}


@app.get("/api/orders/my")
async def api_my_orders(request: Request):
    user = verify_telegram_init_data(request.headers.get("X-Telegram-Init-Data", ""))
    if not user:
        return JSONResponse({"error": "Telegram користувача не підтверджено"}, status_code=403)

    conn = db()
    rows = conn.execute(
        """
        SELECT id, items_json, total, status, city, warehouse, created_at, paid_at, received_at, mono_page_url,
               np_ttn, np_status, np_status_code, np_checked_at
        FROM orders
        WHERE tg_user_id=?
        ORDER BY created_at DESC
        LIMIT 30
        """,
        (user.get("id"),),
    ).fetchall()
    conn.close()

    orders: list[dict[str, object]] = []
    for row in rows:
        item: dict[str, object] = dict(row)
        try:
            item["items"] = json.loads(item.pop("items_json") or "[]")
        except json.JSONDecodeError:
            item["items"] = []
        orders.append(item)

    return {"orders": orders}


@app.post("/api/admin/order/received")
async def api_admin_order_received(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    order_id = str(data.get("orderId") or "").strip()
    if not order_id:
        return JSONResponse({"error": "Невірний ID замовлення"}, status_code=400)

    order = get_order(order_id)
    if not order:
        return JSONResponse({"error": "Замовлення не знайдено"}, status_code=404)

    update_order_payment(order_id, status="received")
    updated_order = get_order(order_id)
    await send_or_edit_admin_order_message(
        order_id,
        order_text(order_id, updated_order, paid=True),
        reply_markup=admin_panel_markup(),
        edit=True,
    )

    if updated_order and updated_order.get("tg_user_id"):
        try:
            await bot.send_message(
                int(updated_order["tg_user_id"]),
                f"📦 Замовлення #{order_id} позначено як отримане. Дякуємо!",
            )
        except Exception:
            logger.exception("Failed to notify user about received order %s", order_id)

    return {"ok": True, "order": updated_order}


@app.post("/api/admin/order/shipped")
async def api_admin_order_shipped(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    order_id = str(data.get("orderId") or "").strip()
    if not order_id:
        return JSONResponse({"error": "Невірний ID замовлення"}, status_code=400)

    order = get_order(order_id)
    if not order:
        return JSONResponse({"error": "Замовлення не знайдено"}, status_code=404)

    update_order_payment(order_id, status="shipped")
    updated_order = get_order(order_id)
    await send_or_edit_admin_order_message(
        order_id,
        order_text(order_id, updated_order, paid=True),
        reply_markup=admin_panel_markup(),
        edit=True,
    )

    if updated_order and updated_order.get("tg_user_id"):
        try:
            await bot.send_message(
                int(updated_order["tg_user_id"]),
                f"📦 Замовлення #{order_id} відправлено. Статус доставки можна дивитися у застосунку Нової Пошти.",
            )
        except Exception:
            logger.exception("Failed to notify user about shipped order %s", order_id)

    return {"ok": True, "order": updated_order}


@app.post("/api/admin/order/ttn")
async def api_admin_order_ttn(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    order_id = str(data.get("orderId") or "").strip()
    ttn = str(data.get("ttn") or "").strip().replace(" ", "")
    if not order_id:
        return JSONResponse({"error": "Невірний ID замовлення"}, status_code=400)
    if not ttn or not ttn.isdigit() or len(ttn) < 10:
        return JSONResponse({"error": "Введіть коректний ТТН Нової Пошти"}, status_code=400)

    order = get_order(order_id)
    if not order:
        return JSONResponse({"error": "Замовлення не знайдено"}, status_code=404)

    update_order_np(order_id, ttn=ttn, np_status="", np_status_code="", mark_checked=False)
    updated_order = get_order(order_id)
    await send_or_edit_admin_order_message(
        order_id,
        order_text(order_id, updated_order, paid=updated_order.get("status") in {"paid", "received"}),
        reply_markup=admin_panel_markup(),
        edit=True,
    )
    return {"ok": True, "order": updated_order}


@app.post("/api/admin/order/np/check")
async def api_admin_order_np_check(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    order_id = str(data.get("orderId") or "").strip()
    if not order_id:
        return JSONResponse({"error": "Невірний ID замовлення"}, status_code=400)

    try:
        updated_order = await refresh_order_np_status(order_id)
    except Exception as exc:
        logger.exception("Nova Poshta status check failed for order %s", order_id)
        return JSONResponse({"error": str(exc)}, status_code=502)

    return {"ok": True, "order": updated_order}


@app.post("/api/admin/order/delete")
async def api_admin_order_delete(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    order_id = str(data.get("orderId") or "").strip()
    if not order_id:
        return JSONResponse({"error": "Невірний ID замовлення"}, status_code=400)

    conn = db()
    cur = conn.execute("UPDATE orders SET hidden_at=CURRENT_TIMESTAMP WHERE id=?", (order_id,))
    conn.commit()
    conn.close()

    if cur.rowcount == 0:
        return JSONResponse({"error": "Замовлення не знайдено"}, status_code=404)

    return {"ok": True}


@app.post("/api/admin/product/add")
async def api_admin_product_add(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    name = str(data.get("name") or "").strip()
    emoji = str(data.get("emoji") or "🫙").strip()
    volume = str(data.get("volume") or "30 мл").strip()
    try:
        price = int(data.get("price") or 0)
    except (TypeError, ValueError):
        price = 0

    if not name:
        return JSONResponse({"error": "Вкажіть назву товару"}, status_code=400)
    if price <= 0:
        return JSONResponse({"error": "Вкажіть коректну ціну"}, status_code=400)
    if not volume:
        return JSONResponse({"error": "Вкажіть обʼєм або склад набору"}, status_code=400)

    product = create_product(name, price, emoji, volume)
    return {"ok": True, "product": product}


@app.post("/api/admin/product/update")
async def api_admin_product_update(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    try:
        product_id = int(data.get("productId") or data.get("id") or 0)
    except (TypeError, ValueError):
        product_id = 0

    if product_id <= 0:
        return JSONResponse({"error": "Невірний ID товару"}, status_code=400)

    name = data.get("name")
    emoji = data.get("emoji")
    volume = data.get("volume")
    price = data.get("price")

    clean_name = str(name).strip() if name is not None else None
    clean_emoji = str(emoji).strip() if emoji is not None else None
    clean_volume = str(volume).strip() if volume is not None else None
    clean_price = None
    if price is not None:
        try:
            clean_price = int(price)
        except (TypeError, ValueError):
            return JSONResponse({"error": "Вкажіть коректну ціну"}, status_code=400)
        if clean_price <= 0:
            return JSONResponse({"error": "Вкажіть коректну ціну"}, status_code=400)

    if clean_name == "":
        return JSONResponse({"error": "Назва не може бути порожньою"}, status_code=400)
    if clean_volume == "":
        return JSONResponse({"error": "Обʼєм не може бути порожнім"}, status_code=400)

    product = update_product(
        product_id,
        name=clean_name,
        price=clean_price,
        emoji=clean_emoji,
        volume=clean_volume,
    )
    if not product:
        return JSONResponse({"error": "Товар не знайдено"}, status_code=404)

    return {"ok": True, "product": product}


@app.post("/api/admin/product/delete")
async def api_admin_product_delete(request: Request):
    if not admin_from_request(request):
        return JSONResponse({"error": "Доступ заборонено"}, status_code=403)

    data = await request.json()
    try:
        product_id = int(data.get("productId") or data.get("id") or 0)
    except (TypeError, ValueError):
        product_id = 0

    if product_id <= 0:
        return JSONResponse({"error": "Невірний ID товару"}, status_code=400)

    if not hide_product(product_id):
        return JSONResponse({"error": "Товар не знайдено"}, status_code=404)

    return {"ok": True}


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
        await send_or_edit_admin_order_message(
            paid_order["id"],
            order_text(paid_order["id"], paid_order, paid=True),
            reply_markup=admin_panel_markup(),
            edit=True,
        )
    elif status in {"failure", "expired", "reversed"}:
        update_order_payment(order["id"], status=status)

    return {"ok": True}


# ====================== BOT ======================
async def configure_bot_profile():
    await bot.set_my_short_description(
        short_description="Крафтове варення з квітів від майстерні «Рідні квіти»."
    )
    await bot.set_my_description(
        description=(
            "🌸 Рідні квіти — маленька майстерня крафтового варення з квітів.\n\n"
            "У магазині можна вибрати варення, оформити доставку Новою Поштою "
            "та оплатити замовлення онлайн."
        )
    )


@dp.message(Command("start"))
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🫙 Відкрити магазин", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
    )
    await message.answer("🌸 <b>Рідні квіти</b>", reply_markup=kb)


@dp.message(Command("admin"))
async def admin(message: types.Message):
    if str(message.from_user.id) not in ADMIN_IDS:
        await message.answer("⛔ Доступ заборонено")
        return
    await message.answer("Адмін панель:", reply_markup=admin_panel_markup())


@dp.message(F.contact)
async def contact_received(message: types.Message):
    contact = message.contact
    if not contact or not contact.phone_number:
        return
    save_user_contact(
        message.from_user.id,
        contact.first_name or message.from_user.first_name,
        contact.last_name or message.from_user.last_name,
        contact.phone_number,
    )
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
