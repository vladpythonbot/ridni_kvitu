import asyncio
from fastapi import FastAPI
from fastapi.responses import FileResponse
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from config import BOT_TOKEN, ADMIN_ID

# 1. Инициализация FastAPI (для Mini App)
app = FastAPI()

# 2. Инициализация Aiogram (для бота)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

WEBAPP_URL = "https://ridnikvitu-production.up.railway.app/"

PRODUCTS = ['🌼 Чорнобривці', '🌹 Троянда', '🫐 Смородина', '💜 Лаванда']

# Хендлеры вашего бота
@dp.message(Command('start'))
async def start(msg: types.Message):
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text='🫙 Відкрити магазин',
                web_app=WebAppInfo(url=WEBAPP_URL)
            )
        ]]
    )
    await msg.answer(
        '🌸 <b>Вітаю в Рідні квіти!</b>\n\n'
        'Крафтове варення з квітів та ягід 🍯',
        reply_markup=kb
    )

@dp.message(Command('catalog'))
async def catalog(msg: types.Message):
    text = '📦 <b>Наші товари:</b>\n\n' + '\n'.join(PRODUCTS)
    await msg.answer(text)

from fastapi import Request

@app.post("/api/order")
async def create_order(request: Request):
    data = await request.json()

    customer = data["customer"]
    delivery = data["delivery"]
    items = data["items"]
    total = data["total"]

    items_text = "\n".join(
        [f"{i['emoji']} {i['name']} × {i['qty']} — {i['sum']} ₴" for i in items]
    )

    text = (
        f"🆕 <b>Нове замовлення</b>\n\n"
        f"👤 {customer['name']}\n"
        f"📞 {customer['phone'] or 'Telegram contact'}\n"
        f"🏙 {delivery['city']}\n"
        f"📦 {delivery['warehouse']}\n\n"
        f"{items_text}\n\n"
        f"💰 Разом: {total} ₴"
    )

    await bot.send_message(ADMIN_ID, text)

    telegram_id = customer.get("telegramId")

    if telegram_id:
        user_text = (
            f"✅ <b>Оплату отримано!</b>\n\n"
            f"📦 Ваше замовлення оформлене.\n\n"
            f"{items_text}\n\n"
            f"🚚 Доставка:\n"
            f"{delivery['city']}\n"
            f"{delivery['warehouse']}\n\n"
            f"💰 Сума: {total} ₴\n\n"
            f"🌸 Дякуємо за замовлення у Рідні квіти!"
        )

        await bot.send_message(telegram_id, user_text)

    return {"ok": True}

from aiogram import F
import json

@dp.message(F.web_app_data)
async def webapp_order(message: types.Message):
    data = json.loads(message.web_app_data.data)

    customer = data["customer"]
    delivery = data["delivery"]
    items = data["items"]
    total = data["total"]

    items_text = "\n".join(
        f"{i['emoji']} {i['name']} × {i['qty']} — {i['sum']} ₴"
        for i in items
    )

    admin_text = (
        f"🆕 <b>Нове замовлення</b>\n\n"
        f"👤 {customer['name']}\n"
        f"📞 {customer['phone'] or 'Telegram contact'}\n"
        f"🏙 {delivery['city']}\n"
        f"📦 {delivery['warehouse']}\n\n"
        f"{items_text}\n\n"
        f"💰 Разом: {total} ₴"
    )

    # админу
    await bot.send_message(ADMIN_ID, admin_text)

    # клиенту
    user_text = (
        f"✅ <b>Оплату отримано!</b>\n\n"
        f"📦 Ваше замовлення оформлене.\n\n"
        f"{items_text}\n\n"
        f"🚚 Доставка:\n"
        f"{delivery['city']}\n"
        f"{delivery['warehouse']}\n\n"
        f"💰 Сума: {total} ₴\n\n"
        f"🌸 Дякуємо за замовлення!"
    )

    await message.answer(user_text)

async def notify_admin(text: str):
    await bot.send_message(ADMIN_ID, text)

@dp.message(Command('test'))
async def test(msg: types.Message):
    await notify_admin('🆕 Тестове замовлення!')
    await msg.answer('✅ Адміну відправлено повідомлення')


# 3. Раздача фронтенда Mini App
@app.get("/")
def home():
    return FileResponse("frontend/index.html")


# 4. Главная магия: запуск бота параллельно с сайтом при старте FastAPI
@app.on_event("startup")
async def on_startup():
    print("🤖 Бот успешно запущен внутри FastAPI процесса!")
    # create_task запускает бота в фоновом потоке, не мешая сайту работать
    asyncio.create_task(dp.start_polling(bot))
