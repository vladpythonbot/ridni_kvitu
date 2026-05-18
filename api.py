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

WEBAPP_URL = "https://railway.app"
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
