from fastapi import FastAPI
from database import SessionLocal, engine, Base
from models import Order
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import os

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app.mount("/static", StaticFiles(directory="frontend"), name="static")


# 🔥 создаём таблицы при старте
@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def home():
    return FileResponse(os.path.join(BASE_DIR, "frontend", "index.html"))


@app.post("/order")
def create_order(data: dict):
    db = SessionLocal()

    order = Order(
        name=data["name"],
        phone=data["phone"],
        items=data["items"],
        total=data["total"]
    )

    db.add(order)
    db.commit()
    db.refresh(order)
    db.close()

    return {"ok": True, "order_id": order.id}