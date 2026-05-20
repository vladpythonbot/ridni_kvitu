import asyncio
import json
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo
)
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager

from config import BOT_TOKEN, ADMIN_ID

# ====================== ІНІЦІАЛІЗАЦІЯ ======================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


# FastAPI для віддачі Mini App
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(main_bot())  # запускаємо бота в фоні
    yield


app = FastAPI(lifespan=lifespan)

# Підключаємо папку webapp як статичні файли
app.mount("/static", StaticFiles(directory="webapp"), name="static")


@app.get("/")
async def serve_webapp():
    return FileResponse("webapp/index.html")


# ====================== ХЕНДЛЕРИ AIOGRAM ======================

@dp.message(Command('start'))
async def start(msg: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text='🫙 Відкрити магазин',
            web_app=WebAppInfo(url=f"{os.getenv('WEBAPP_URL', 'https://ridni-kvitu-production.up.railway.app')}")
        )
    ]])

    await msg.answer(
        '🌸 <b>Вітаю в Рідні квіти!</b>\n\n'
        'Крафтове варення з квітів та ягід 🍯',
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.message(F.web_app_data)
async def handle_webapp_order(message: types.Message):
    """Обробка даних, які приходять з Mini App"""
    try:
        data = json.loads(message.web_app_data.data)

        if data.get("action") == "new_order":
            items_text = "\n".join([
                f"• {item['name']} × {item['qty']} — {item['price'] * item['qty']} ₴"
                for item in data.get("items", [])
            ])

            text = f"""
🛍 <b>Нове замовлення!</b>

👤 Ім'я: {data.get('name')}
📞 Телефон: {data.get('phone')}
📍 Адреса: {data.get('address')}

🫙 <b>Товари:</b>
{items_text}

💰 Сума: <b>{data.get('total', 0)} ₴</b>
"""

            if data.get('comment'):
                text += f"\n💬 Коментар: {data['comment']}"

            # Відправляємо адміну
            await bot.send_message(ADMIN_ID, text, parse_mode="HTML")

            # Відповідаємо користувачу
            await message.answer(
                "✅ <b>Замовлення прийнято!</b>\n\n"
                "Ми скоро з вами зв'яжемося для підтвердження.",
                parse_mode="HTML"
            )

    except Exception as e:
        print("Помилка обробки WebApp даних:", e)
        await message.answer("❌ Виникла помилка при обробці замовлення.")


# ====================== ЗАПУСК ======================
async def main_bot():
    print("🤖 Бот запущений (polling)")
    await dp.start_polling(bot)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))