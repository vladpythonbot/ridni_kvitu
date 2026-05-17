from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
import asyncio

from config import BOT_TOKEN, ADMIN_ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

PRODUCTS = [
    '🌼 Чорнобривці',
    '🌹 Троянда',
    '🫐 Смородина',
    '💜 Лаванда'
]

@dp.message(Command('start'))
async def start(msg: types.Message):
    await msg.answer(
        '🌸 Вітаю в Рідні квіти!\n\n'
        '/catalog - товари'
    )

@dp.message(Command('catalog'))
async def catalog(msg: types.Message):
    text = '📦 Наші товари:\n\n' + '\n'.join(PRODUCTS)
    await msg.answer(text)

async def notify_admin(text: str):
    await bot.send_message(ADMIN_ID, text)

@dp.message(Command('test'))
async def test(msg: types.Message):
    await notify_admin('🆕 Тестове замовлення!')

async def main():
    await dp.start_polling(bot)
