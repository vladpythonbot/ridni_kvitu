from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List
import os
from dotenv import load_dotenv

# ======================
# LOAD ENV
# ======================
load_dotenv()

raw_admins = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = set(map(int, raw_admins.split(","))) if raw_admins else set()

# ======================
# APP
# ======================
app = FastAPI()

# ======================
# STATIC FRONTEND
# ======================
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# ======================
# MODELS
# ======================
class Item(BaseModel):
    name: str
    qty: int
    price: int


class Order(BaseModel):
    name: str
    phone: str
    address: str
    items: List[Item]
    total: int


class AdminChange(BaseModel):
    master_id: int
    new_admin_id: int


# ======================
# ADMIN CHECK
# ======================
@app.get("/check-admin")
def check_admin(userId: int):
    return {"isAdmin": userId in ADMIN_IDS}


# ======================
# ORDER
# ======================
@app.post("/order")
def create_order(order: Order):
    print("NEW ORDER:", order)
    return {"ok": True}


# ======================
# ADMIN ADD
# ======================
@app.post("/admin/add")
def add_admin(data: AdminChange):
    if data.master_id not in ADMIN_IDS:
        return {"ok": False, "error": "no access"}

    ADMIN_IDS.add(data.new_admin_id)
    return {"ok": True}


# ======================
# ADMIN REMOVE
# ======================
@app.post("/admin/remove")
def remove_admin(data: AdminChange):
    if data.master_id not in ADMIN_IDS:
        return {"ok": False, "error": "no access"}

    ADMIN_IDS.discard(data.new_admin_id)
    return {"ok": True}