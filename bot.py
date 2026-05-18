from aiogram import Bot, Dispatcher, types
import os
import uvicorn
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo
)

import asyncio

from config import BOT_TOKEN, ADMIN_ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# 🔥 ПОСЛЕ ДЕПЛОЯ НА RAILWAY ВСТАВЬ СЮДА СВОЙ HTTPS URL
WEBAPP_URL= "https://ridni-kvitu-production.up.railway.app"

PRODUCTS = [
    '🌼 Чорнобривці',
    '🌹 Троянда',
    '🫐 Смородина',
    '💜 Лаванда'
]


@dp.message(Command('start'))
async def start(msg: types.Message):

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text='🫙 Відкрити магазин',
                    web_app=WebAppInfo(url=WEBAPP_URL)
                )
            ]
        ]
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


async def main():

    print('BOT STARTED')

    await dp.start_polling(bot)


if __name__ == "__main__":
    # Считываем порт, который выдал Railway, иначе берем 8000 по умолчанию
    port = int(os.environ.get("PORT", 8000))

    uvicorn.run("main:app", host="0.0.0.0", port=port)