import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://ridnikvitu-production.up.railway.app").rstrip("/")
NP_API_KEY = os.getenv("NP_API_KEY", "").strip()
MONO_TOKEN = os.getenv("MONO_TOKEN", "").strip()
RUN_BOT = os.getenv("RUN_BOT", "1") == "1"

ADMIN_ID_RAW = os.getenv("ADMIN_ID") or os.getenv("ADMIN_CHAT_ID") or "0"
ADMIN_ID = int(ADMIN_ID_RAW)

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не знайдено в .env")

if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID або ADMIN_CHAT_ID не знайдено в .env")