"""
وظيفة هذا الملف: تعريف الجداول (Models) باستخدام SQLAlchemy 2.0.
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.sql import func
from app.database.session import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="customer") # 'admin', 'customer'
    linked_customer_id = Column(String, nullable=True) # لربط حساب تيليجرام بالمنظومة
    totp_secret = Column(String, nullable=True)
    is_totp_enabled = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Subscriber(Base):
    __tablename__ = "subscribers"
    user_id = Column(Integer, primary_key=True) # Telegram User ID
    role = Column(String, default='customer')
    linked_account = Column(String, nullable=True)

class UserSetting(Base):
    __tablename__ = "user_settings"
    user_id = Column(Integer, primary_key=True) # Telegram User ID
    pharmacy = Column(String, nullable=True)
    discount_mode = Column(String, default='credit') # cash, transfer, credit

class Medicine(Base):
    __tablename__ = "medicines"
    id = Column(Integer, primary_key=True, index=True)
    item_code = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False, index=True)
    category = Column(String, nullable=True)
    quantity = Column(Integer, default=0)
    expiry_date = Column(String, nullable=True)
    price = Column(Float, default=0.0)
    cost_price = Column(Float, default=0.0)
    barcode = Column(String, index=True, nullable=True)
    image_file_id = Column(String, nullable=True) # Telegram file_id
    is_new_arrival = Column(Boolean, default=False)
    min_stock_level = Column(Integer, default=5) # للتنبيهات

class Customer(Base):
    __tablename__ = "customers"
    customer_id = Column(String, primary_key=True, index=True)
    customer_name = Column(String, nullable=False, index=True)
    main_account = Column(String, nullable=True)
    debt = Column(Float, default=0.0) # مدين
    credit = Column(Float, default=0.0) # دائن
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)

class Supplier(Base):
    __tablename__ = "suppliers"
    supplier_id = Column(String, primary_key=True, index=True)
    supplier_name = Column(String, nullable=False, index=True)
    debt = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)

class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True, index=True)
    invoice_no = Column(Integer, unique=True, index=True)
    pharmacy_name = Column(String, nullable=True)
    customer_id = Column(String, ForeignKey("customers.customer_id"), nullable=True)
    payment_method = Column(String, default="credit") # cash, transfer, credit
    total_amount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    final_amount = Column(Float, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    details = Column(Text, nullable=True) # JSON string for items

class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, nullable=True)
    action = Column(String, nullable=False)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
