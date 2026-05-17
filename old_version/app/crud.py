import os
import pandas as pd
from typing import Tuple, List
from sqlalchemy.orm import Session
from . import models
from .auth import get_password_hash
from datetime import datetime

SUPPLIER_KEYWORDS = ["شركة", "مورد", "تشاركية", "مذخر"]


def get_or_create_user(db: Session, username: str, password: str, role: str = "customer"):
    user = db.query(models.User).filter(models.User.username == username).first()
    if user:
        return user
    user = models.User(username=username, password_hash=get_password_hash(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def query_products(db: Session, new_arrivals: bool = False, query: str = ""):
    q = db.query(models.Medicine)
    if new_arrivals:
        q = q.filter(models.Medicine.is_new_arrival == True)
    if query:
        term = f"%{query}%"
        q = q.filter((models.Medicine.name.ilike(term)) | (models.Medicine.item_code.ilike(term)) | (models.Medicine.barcode.ilike(term)))
    return q.order_by(models.Medicine.name).limit(100).all()


def get_product_by_barcode(db: Session, code: str):
    return db.query(models.Medicine).filter((models.Medicine.barcode == code) | (models.Medicine.item_code == code)).first()


def calculate_cart_totals(items: list, payment_method: str):
    subtotal = 0.0
    total = 0.0
    for item in items:
        quantity = int(item.get("quantity", 0))
        unit_price = float(item.get("unit_price", 0.0))
        subtotal += quantity * float(item.get("original_price", unit_price))
        total += quantity * unit_price
    discount = round(subtotal - total, 2)
    return subtotal, discount, total


def create_invoice(db: Session, pharmacy: str, customer_id: str, payment_method: str, items: list, totals: Tuple[float, float, float]):
    subtotal, discount, total = totals
    invoice_no = get_next_invoice_number()
    invoice = models.Invoice(
        invoice_no=invoice_no,
        customer_id=customer_id,
        pharmacy_name=pharmacy,
        payment_method=payment_method,
        total_before_discount=subtotal,
        discount_amount=discount,
        total_after_discount=total,
    )
    db.add(invoice)
    db.flush()
    for item in items:
        db_item = models.InvoiceItem(
            invoice_id=invoice.id,
            item_code=item["item_code"],
            name=item["name"],
            category=item.get("category", ""),
            quantity=int(item["quantity"]),
            unit_price=float(item["unit_price"]),
            original_price=float(item.get("original_price", item["unit_price"])),
        )
        db.add(db_item)
    db.commit()
    db.refresh(invoice)
    return invoice


def get_next_invoice_number():
    counter_file = os.path.join(os.getcwd(), "invoice_counter.txt")
    if not os.path.exists(counter_file):
        with open(counter_file, "w", encoding="utf-8") as f:
            f.write("1")
        return 1
    with open(counter_file, "r+", encoding="utf-8") as f:
        content = f.read().strip()
        no = int(content) if content.isdigit() else 0
        no += 1
        f.seek(0)
        f.write(str(no))
        f.truncate()
    return no


def _format_expiry(val):
    if pd.isna(val):
        return ""
    if isinstance(val, (pd.Timestamp, datetime)):
        return val.strftime("%Y-%m-%d")
    return str(val)


def import_excel(db: Session, file_path: str) -> Tuple[bool, str, List[dict]]:
    try:
        df = pd.read_excel(file_path)
    except Exception as e:
        return False, f"Failed to read Excel file: {e}", []

    if "رقم الزبون" in df.columns or "رقم الحساب" in df.columns:
        return import_customers(db, df)
    if "رقم الصنف" in df.columns or "اسم الصنف" in df.columns:
        return import_medicines(db, df)
    return False, "Excel file does not contain recognizable columns.", []


def _is_supplier(name: str) -> bool:
    text = str(name or "").strip()
    return any(keyword in text for keyword in SUPPLIER_KEYWORDS)


def import_customers(db: Session, df):
    column_map = {
        "رقم الزبون": "customer_id", "اسم الزبون": "customer_name",
        "رقم الحساب": "customer_id", "اسم الحساب": "customer_name",
        "مدين": "debt", "مــدين": "debt",
        "دائن": "credit", "دائـــن": "credit",
        "الحساب الرئيسي": "main_account", "الهاتف": "phone", "العنوان": "address"
    }
    df = df.rename(columns=column_map)
    for col in ["customer_id", "customer_name", "main_account", "debt", "credit", "phone", "address"]:
        if col not in df.columns:
            df[col] = "" if col not in ("debt", "credit") else 0.0

    notifications = []
    for _, row in df.iterrows():
        customer_id = str(row.get("customer_id", "")).strip()
        if customer_id.endswith(".0"):
            customer_id = customer_id[:-2]
        if not customer_id or customer_id.lower() == "nan":
            continue
        name = str(row.get("customer_name", ""))
        main_account = str(row.get("main_account", ""))
        debt = float(row.get("debt", 0.0) or 0.0)
        credit = float(row.get("credit", 0.0) or 0.0)
        phone = str(row.get("phone", ""))
        address = str(row.get("address", ""))

        if _is_supplier(name):
            supplier = db.query(models.Supplier).filter(models.Supplier.supplier_id == customer_id).first()
            if not supplier:
                supplier = models.Supplier(supplier_id=customer_id, supplier_name=name, debt=debt, credit=credit)
                db.add(supplier)
            else:
                supplier.supplier_name = name
                supplier.debt = debt
                supplier.credit = credit
            continue

        customer = db.query(models.Customer).filter(models.Customer.customer_id == customer_id).first()
        if not customer:
            customer = models.Customer(
                customer_id=customer_id,
                customer_name=name,
                main_account=main_account,
                debt=debt,
                credit=credit,
                phone=phone,
                address=address,
            )
            db.add(customer)
        else:
            customer.customer_name = name
            customer.main_account = main_account
            customer.debt = debt
            customer.credit = credit
            customer.phone = phone
            customer.address = address
    db.commit()
    return True, "Customer import completed.", notifications


def import_medicines(db: Session, df):
    column_map = {
        "رقم الصنف": "item_code", "اسم الصنف": "name", "سعر البيع": "price",
        "سعر التكلفة": "cost_price", "الرصيد": "quantity", "ت.الصلاحية": "expiry_date",
        "الرقم الاصلي": "barcode", "فئة الصنف": "category"
    }
    df = df.rename(columns=column_map)
    for col in ["item_code", "name", "category", "quantity", "expiry_date", "price", "cost_price", "barcode"]:
        if col not in df.columns:
            df[col] = 0 if col in ("quantity", "price", "cost_price") else ""

    df["expiry_date"] = df["expiry_date"].apply(_format_expiry)
    df["barcode"] = df["barcode"].fillna("")
    db.query(models.Medicine).update({models.Medicine.is_new_arrival: False})
    for _, row in df.iterrows():
        item_code = str(row.get("item_code", "")).strip()
        if item_code.endswith(".0"):
            item_code = item_code[:-2]
        if not item_code or item_code.lower() == "nan":
            continue
        name = str(row.get("name", "") or "").strip()
        category = str(row.get("category", "") or "").strip()
        expiry = str(row.get("expiry_date", "") or "").strip()
        barcode = str(row.get("barcode", "") or "").strip()
        if barcode.endswith(".0"):
            barcode = barcode[:-2]
        quantity = int(float(row.get("quantity", 0) or 0))
        price = float(row.get("price", 0.0) or 0.0)
        cost_price = float(row.get("cost_price", 0.0) or 0.0)

        medicine = db.query(models.Medicine).filter(models.Medicine.item_code == item_code).first()
        is_new = True
        if medicine:
            medicine.name = name
            medicine.category = category
            medicine.quantity = quantity
            medicine.expiry_date = expiry
            medicine.price = price
            medicine.cost_price = cost_price
            medicine.barcode = barcode
            medicine.is_new_arrival = is_new
        else:
            medicine = models.Medicine(
                item_code=item_code,
                name=name,
                category=category,
                quantity=quantity,
                expiry_date=expiry,
                price=price,
                barcode=barcode,
                cost_price=cost_price,
                is_new_arrival=is_new,
            )
            db.add(medicine)
    db.commit()
    return True, "Medicine import completed.", []
