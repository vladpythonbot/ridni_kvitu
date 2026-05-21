import asyncio
import json
import os
import uuid
import logging
from contextlib import asynccontextmanager

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONO_TOKEN = os.getenv("MONO_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not found")

if not WEBAPP_URL:
    raise Exception("WEBAPP_URL not found")

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)

dp = Dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):

    asyncio.create_task(start_bot())

    yield


app = FastAPI(lifespan=lifespan)

app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


async def create_invoice(total, order_id):

    if not MONO_TOKEN:
        return None

    url = "https://api.monobank.ua/api/merchant/invoice/create"

    headers = {
        "X-Token": MONO_TOKEN
    }

    payload = {
        "amount": total * 100,
        "ccy": 980,
        "merchantPaymInfo": {
            "reference": order_id,
            "destination": f"Оплата замовлення {order_id}"
        },
        "redirectUrl": WEBAPP_URL
    }

    try:

        async with httpx.AsyncClient() as client:

            response = await client.post(
                url,
                json=payload,
                headers=headers
            )

            if response.status_code == 200:
                return response.json()

            print(response.text)

            return None

    except Exception as e:
        print(e)
        return None


@dp.message(Command("start"))
async def start(message: types.Message):

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🫙 Відкрити магазин",
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ]
    )

    await message.answer(
        "🌸 <b>Рідні квіти</b>\n\n"
        "Крафтове варення та квіти 🍯",
        reply_markup=kb
    )


@dp.message(F.web_app_data)
async def webapp_data(message: types.Message):

    try:

        data = json.loads(message.web_app_data.data)

        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        address = str(data.get("address", "")).strip()

        total = int(data.get("total", 0))

        if not name or not phone or not address:
            await message.answer("❌ Заповніть всі поля")
            return

        if total <= 0:
            await message.answer("❌ Невірна сума")
            return

        order_id = uuid.uuid4().hex[:10]

        text = (
            f"🆕 НОВЕ ЗАМОВЛЕННЯ\n\n"
            f"📦 ID: {order_id}\n"
            f"👤 {name}\n"
            f"📞 {phone}\n"
            f"🏠 {address}\n"
            f"💰 {total} грн"
        )

        print(text)

        invoice = await create_invoice(total, order_id)

        if not invoice:

            await message.answer(
                "❌ Помилка створення оплати"
            )

            return

        pay_url = invoice.get("pageUrl")

        pay_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 Оплатити",
                        url=pay_url
                    )
                ]
            ]
        )

        await message.answer(
            f"✅ Замовлення створено\n\n"
            f"💰 До оплати: {total} грн",
            reply_markup=pay_kb
        )

    except Exception as e:

        print(e)

        await message.answer(
            "❌ Помилка"
        )


@app.post("/api/order")
async def api_order(request: types):

    return JSONResponse({
        "ok": True
    })


async def start_bot():

    await dp.start_polling(bot)


if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", 8000)),
        reload=False
    )