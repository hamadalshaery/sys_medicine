import os
import io
from datetime import datetime, timedelta
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI, HTTPException, UploadFile, File, Request, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from jose import JWTError, jwt
from mangum import Mangum
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, func
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from fpdf import FPDF
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 480

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL must be set in environment variables")

# Example connection string for Supabase (PostgreSQL):
# postgres+pg8000://<DB_USER>:<DB_PASS>@<PROJECT_REF>.supabase.co:5432/postgres
# Use environment variable NETLIFY_DUMP to store this safely in Netlify settings.

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
app = FastAPI(title="Pharmacy Serverless API")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="customer", nullable=False)
    linked_customer_id = Column(String, nullable=True)


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


class Customer(Base):
    __tablename__ = "customers"
    customer_id = Column(String, primary_key=True, index=True)
    customer_name = Column(String, default="")
    main_account = Column(String, default="")
    debt = Column(Float, default=0.0)
    credit = Column(Float, default=0.0)
    phone = Column(String, default="")
    address = Column(String, default="")


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
    customer_id = Column(String, nullable=True)
    pharmacy_name = Column(String, default="")
    payment_method = Column(String, default="credit")
    total_before_discount = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    total_after_discount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    id = Column(Integer, primary_key=True, index=True)
    invoice_id = Column(Integer, nullable=False)
    item_code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    category = Column(String, default="")
    quantity = Column(Integer, default=0)
    unit_price = Column(Float, default=0.0)
    original_price = Column(Float, default=0.0)


class LoginPayload(BaseModel):
    username: str
    password: str


class ProductPayload(BaseModel):
    item_code: str
    name: str
    category: Optional[str] = ""
    quantity: int
    unit_price: float
    original_price: float


class CheckoutPayload(BaseModel):
    cart_items: List[ProductPayload]
    payment_method: str = "credit"
    pharmacy: Optional[str] = ""
    customer_id: Optional[str] = None


@app.on_event("startup")
def startup_event():
    Base.metadata.create_all(bind=engine)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(username: str):
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else auth_header
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        username = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


def calculate_cart_totals(items: List[ProductPayload], payment_method: str):
    subtotal = 0.0
    total = 0.0
    for item in items:
        subtotal += item.quantity * item.original_price
        total += item.quantity * item.unit_price
    return subtotal, round(subtotal - total, 2), total


def invoice_pdf_bytes(invoice_no: int, pharmacy: str, customer_name: str, payment_method: str, items: List[ProductPayload], subtotal: float, discount: float, total: float) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(0, 10, f"فاتورة رقم {invoice_no}", ln=True, align="R")
    pdf.cell(0, 10, f"صيدلية: {pharmacy}", ln=True, align="R")
    pdf.cell(0, 10, f"الزبون: {customer_name}", ln=True, align="R")
    pdf.cell(0, 10, f"طريقة الدفع: {payment_method}", ln=True, align="R")
    pdf.ln(5)
    pdf.cell(30, 8, "الكود", 1, 0, "C")
    pdf.cell(60, 8, "الاسم", 1, 0, "C")
    pdf.cell(30, 8, "الكمية", 1, 0, "C")
    pdf.cell(30, 8, "سعر الوحدة", 1, 0, "C")
    pdf.cell(40, 8, "الإجمالي", 1, 1, "C")
    for item in items:
        pdf.cell(30, 8, item.item_code, 1, 0, "C")
        pdf.cell(60, 8, item.name[:20], 1, 0, "C")
        pdf.cell(30, 8, str(item.quantity), 1, 0, "C")
        pdf.cell(30, 8, f"{item.unit_price:.2f}", 1, 0, "C")
        pdf.cell(40, 8, f"{item.quantity * item.unit_price:.2f}", 1, 1, "C")
    pdf.ln(5)
    pdf.cell(0, 10, f"الإجمالي قبل الخصم: {subtotal:.2f}", ln=True, align="R")
    pdf.cell(0, 10, f"الخصم: {discount:.2f}", ln=True, align="R")
    pdf.cell(0, 10, f"الإجمالي النهائي: {total:.2f}", ln=True, align="R")
    return pdf.output(dest="S").encode("latin-1")


@app.post("/login")
def login(payload: LoginPayload, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(user.username)
    return {"access_token": token, "token_type": "bearer", "role": user.role}


@app.get("/products")
def list_products(q: Optional[str] = None, new_arrivals: bool = False, db: Session = Depends(get_db)):
    query = db.query(Medicine)
    if new_arrivals:
        query = query.filter(Medicine.is_new_arrival == True)
    if q:
        term = f"%{q}%"
        query = query.filter((Medicine.name.ilike(term)) | (Medicine.item_code.ilike(term)) | (Medicine.barcode.ilike(term)))
    products = query.order_by(Medicine.name).limit(100).all()
    return [
        {
            "item_code": p.item_code,
            "name": p.name,
            "category": p.category,
            "quantity": p.quantity,
            "price": p.price,
            "barcode": p.barcode,
            "is_new_arrival": p.is_new_arrival,
        }
        for p in products
    ]


@app.get("/barcode-search")
def barcode_search(code: str, db: Session = Depends(get_db)):
    item = db.query(Medicine).filter((Medicine.barcode == code) | (Medicine.item_code == code)).first()
    if not item:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "item_code": item.item_code,
        "name": item.name,
        "category": item.category,
        "quantity": item.quantity,
        "price": item.price,
        "barcode": item.barcode,
    }


@app.post("/upload-excel")
def upload_excel(file: UploadFile = File(...), user: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be an .xlsx workbook")
    data = file.file.read()
    df = pd.read_excel(io.BytesIO(data))
    return {"success": True, "message": "Excel received", "rows": len(df)}


@app.post("/checkout")
def checkout(payload: CheckoutPayload, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not payload.cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")
    subtotal, discount, total = calculate_cart_totals(payload.cart_items, payload.payment_method)
    invoice_no = int(datetime.utcnow().timestamp())
    pdf_data = invoice_pdf_bytes(invoice_no, payload.pharmacy or "-", user.username, payload.payment_method, payload.cart_items, subtotal, discount, total)
    return StreamingResponse(io.BytesIO(pdf_data), media_type="application/pdf", headers={"Content-Disposition": f"attachment; filename=invoice_{invoice_no}.pdf"})


@app.get("/admin/dashboard")
def admin_dashboard(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_debt = db.query(func.sum(Customer.debt)).scalar() or 0.0
    total_credit = db.query(func.sum(Customer.credit)).scalar() or 0.0
    cutoff_date = (datetime.utcnow() + timedelta(days=45)).strftime("%Y-%m-%d")
    expiring_count = db.query(Medicine).filter(Medicine.expiry_date != "", Medicine.expiry_date <= cutoff_date).count()
    total_users = db.query(User).count()
    return {
        "total_debt": total_debt,
        "total_credit": total_credit,
        "expiring_count": expiring_count,
        "total_users": total_users,
    }


handler = Mangum(app)
