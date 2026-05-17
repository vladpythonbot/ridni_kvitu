from sqlalchemy import Column, Integer, String
from database import Base

class Order(Base):
    __tablename__ = 'orders'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    phone = Column(String)
    items = Column(String)
    total = Column(Integer)
