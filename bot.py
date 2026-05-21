import asyncio
import json
import os
import uuid
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, WebAppInfo

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL")

if not BOT_TOKEN or not WEBAPP_URL:
    raise Exception("BOT_TOKEN або WEBAPP_URL не знайдено в .env")

WEBAPP_URL = WEBAPP_URL.rstrip("/")

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(start_bot())
    logger.info("✅ Тестовий режим запущено")
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")


# ====================== ГЛАВНИЙ ХЕНДЛЕР ======================
@dp.message(Command("start"))
async def start(message: types.Message):
    kb = ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text="🫙 Відкрити магазин", web_app=WebAppInfo(url=WEBAPP_URL))
        ]],
        resize_keyboard=True,
        persistent=True
    )

    await message.answer(
        "🌸 <b>Рідні квіти — тестовий режим</b>\n\n"
        "Натисни кнопку нижче та оформи тестове замовлення.",
        reply_markup=kb
    )


@dp.message(F.web_app_data)
async def webapp_data(message: types.Message):
    """Симуляція оплати"""
    try:
        data = json.loads(message.web_app_data.data)

        name = str(data.get("name", "")).strip()
        phone = str(data.get("phone", "")).strip()
        address = str(data.get("address", "")).strip()
        total = int(data.get("total", 0))

        if not name or not phone or not address:
            return await message.answer("❌ Заповніть усі обов'язкові поля!")

        if total < 10:
            return await message.answer("❌ Мінімальна сума — 10 грн")

        order_id = f"TEST-{uuid.uuid4().hex[:8].upper()}"

        # Симуляція успішної оплати
        await message.answer(f"""
✅ <b>Замовлення #{order_id}</b> успішно оформлено!

👤 {name}
📞 {phone}
🏠 {address}
💰 Сума: <b>{total} ₴</b>

🧪 <i>Тестовий режим — оплата пройшла успішно (симуляція)</i>
""")

        logger.info(f"ТЕСТОВЕ ЗАМОВЛЕННЯ | {order_id} | {total} грн | {name}")

    except Exception as e:
        logger.error(e)
        await message.answer("❌ Помилка обробки замовлення.")


async def start_bot():
    logger.info("🤖 Бот запущений")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)))