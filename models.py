from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="customer", nullable=False)
    linked_customer_id = Column(String, ForeignKey("customers.customer_id"), nullable=True)

    customer = relationship("Customer", back_populates="users")

class Medicine(Base):
    __tablename__ = "medicines"
    id = Column(Integer, primary_key=True, index=True)
    item_code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, default="")
    quantity = Column(Integer, default=0)
    expiry_date = Column(String, default="")
    price = Column(Float, default=0.0)
    barcode = Column(String, index=True, default="")
    cost_price = Column(Float, default=0.0)
    is_new_arrival = Column(Boolean, default=False)
    image_url = Column(String, default=None, nullable=True)

class Customer(Base):
    __tablename__ = "customers"
    customer_id = Column(String, primary_key=True, index=True)
    customer_name = Column(String, default="")
    main_account = Column(String, default="")
    debt = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    phone = Column(String, default="")
    address = Column(String, default="")

    users = relationship("User", back_populates="customer")

class Supplier(Base):
    __tablename__ = "suppliers"
    supplier_id = Column(String, primary_key=True, index=True)
    supplier_name = Column(String, default="")
    debt = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(Integer, nullable=False)
    customer_id = Column(String, ForeignKey("customers.customer_id"), nullable=True)
    pharmacy_name = Column(String, default="")
    payment_method = Column(String, default="credit")
    total_before_discount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    total_after_discount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    items = relationship("InvoiceItem", back_populates="invoice")

class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False)
    item_code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, default="")
    quantity = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    original_price = Column(Float, default=0.0)

    invoice = relationship("Invoice", back_populates="items")
