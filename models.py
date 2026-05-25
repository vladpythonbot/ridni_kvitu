from sqlalchemy import Column, Integer, String, Text
from database import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    order_code = Column(String, unique=True, index=True)
    tg_user_id = Column(Integer)
    tg_username = Column(String)
    name = Column(String)
    phone = Column(String)
    phone_shared = Column(Integer, default=0)
    city = Column(String)
    city_ref = Column(String)
    warehouse = Column(String)
    warehouse_ref = Column(String)
    items = Column(Text)
    total = Column(Integer)
    comment = Column(Text)
    status = Column(String, default="payment_waiting")
    mono_invoice_id = Column(String, index=True)
    mono_page_url = Column(String)
    created_at = Column(String)
    paid_at = Column(String)
