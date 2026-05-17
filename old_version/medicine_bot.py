import os
import sys
import logging
import sqlite3
import datetime
import glob
from typing import List, Tuple, Dict, Any, Set

import pandas as pd
from fpdf import FPDF
import arabic_reshaper
from bidi.algorithm import get_display

import numpy as np
import cv2
import io

from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Bot,
    InlineQueryResultArticle,
    InputTextMessageContent,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
    CallbackQueryHandler,
    InlineQueryHandler,
)

load_dotenv()

# --------------------- إعدادات ---------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    BOT_TOKEN = "8338396074:AAF1lvSWgzv47m4He0-Wz4UnHu1UqktTvBA"

ADMINS_ENV = os.getenv("ADMINS")
if ADMINS_ENV:
    ADMINS: List[int] = [int(x.strip()) for x in ADMINS_ENV.split(",") if x.strip().isdigit()]
else:
    ADMINS: List[int] = [7332756293, 7298580811, 8303624288, 7414270251, 1165537354]

DB_FILE = "pharmacy.db"
COUNTER_FILE = "invoice_counter.txt"

DISCOUNT_RATE = 0.10  # 10% خصم للكاش

# مجلد حفظ الفواتير
INVOICE_DIR = "invoices"
os.makedirs(INVOICE_DIR, exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ---------- بيانات في الذاكرة ----------
user_carts: Dict[int, Dict[str, Any]] = {}
active_users: Dict[int, str] = {}


# --------------------- أدوات مساعدة ---------------------
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def format_currency(val: float) -> str:
    try:
        return f"{round(val, 2)} د"
    except Exception:
        return str(val)

def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def get_net_balance_details(debt: float, credit: float) -> str:
    net = debt - credit
    if net > 0:
        status = "مدين (عليه)"
    elif net < 0:
        status = "دائن (له)"
    else:
        status = "متزن"
    return f"{format_currency(abs(net))} ({status})"

def restart_program():
    logger.info("Restarting bot...")
    python = sys.executable
    os.execl(python, python, *sys.argv)

def _recalc_cart_prices(uid: int, mode: str):
    cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
    if not cart["items"]:
        return
    for i, item in enumerate(cart["items"]):
        code, name, cat, qty, unit_price, orig_price = item
        if mode == "cash":
            new_unit_price = round(orig_price * (1 - DISCOUNT_RATE), 2)
        elif mode == "transfer":
            new_unit_price = round(orig_price * 0.95, 2)
        else:
            new_unit_price = orig_price
        cart["items"][i] = (code, name, cat, qty, new_unit_price, orig_price)

# --------------------- قاعدة البيانات ---------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # جدول المشتركين
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS subscribers (
            user_id INTEGER PRIMARY KEY,
            role TEXT DEFAULT 'customer',
            linked_account TEXT DEFAULT NULL
        )
        """
    )
    
    # جدول الأدوية
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS medicines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_code TEXT UNIQUE,
            name TEXT,
            category TEXT,
            quantity INTEGER,
            expiry_date TEXT,
            price REAL,
            barcode TEXT,
            cost_price REAL DEFAULT 0.0,
            image_file_id TEXT DEFAULT NULL
        )
        """
    )
    for col, dtype in [("barcode", "TEXT DEFAULT ''"), ("cost_price", "REAL DEFAULT 0.0"), ("image_file_id", "TEXT DEFAULT NULL"), ("is_new_arrival", "INTEGER DEFAULT 0")]:
        try:
            c.execute(f"ALTER TABLE medicines ADD COLUMN {col} {dtype}")
        except sqlite3.OperationalError:
            pass 

    # جدول الإعدادات
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS user_settings (
            user_id INTEGER PRIMARY KEY,
            pharmacy TEXT,
            discount_mode TEXT DEFAULT 'credit'
        )
        """
    )

    # جدول الزبائن
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            customer_name TEXT,
            main_account TEXT,
            debt REAL,
            credit REAL,
            phone TEXT,
            address TEXT
        )
        """
    )

    # جدول الموردين
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id TEXT PRIMARY KEY,
            supplier_name TEXT,
            debt REAL DEFAULT 0.0,
            credit REAL DEFAULT 0.0
        )
        """
    )

    conn.commit()
    conn.close()

def get_subscriber(user_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT role, linked_account FROM subscribers WHERE user_id=?", (user_id,))
    res = c.fetchone()
    conn.close()
    return res

def register_subscriber(user_id: int, role: str = 'customer'):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO subscribers (user_id, role) VALUES (?, ?)", (user_id, role))
    conn.commit()
    conn.close()

def link_account(user_id: int, customer_id: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT customer_id FROM customers WHERE customer_id=?", (customer_id,))
    if c.fetchone():
        c.execute("UPDATE subscribers SET linked_account=? WHERE user_id=?", (customer_id, user_id))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def load_user_settings(uid: int) -> dict:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT discount_mode FROM user_settings WHERE user_id=?", (uid,))
    row = c.fetchone()
    conn.close()
    if row:
        discount_mode = row[0]
        return {"pharmacy": "", "discount_mode": discount_mode or "credit"}
    else:
        return {"pharmacy": "", "discount_mode": "credit"}

def save_user_settings(uid: int, discount_mode: str = None):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    if discount_mode is not None:
        c.execute("INSERT OR REPLACE INTO user_settings (user_id, discount_mode) VALUES (?, ?)", (uid, discount_mode))
    conn.commit()
    conn.close()

def _format_expiry(val) -> str:
    if pd.isna(val): return ""
    if isinstance(val, (pd.Timestamp, datetime.date, datetime.datetime)):
        try: return val.strftime("%Y-%m-%d")
        except: return str(val)
    return str(val)

def import_excel_to_db(path: str) -> Tuple[bool, str, list]:
    try:
        df = pd.read_excel(path)
    except Exception as e:
        return False, f"❌ فشل قراءة الملف: {e}", []

    if "رقم الزبون" in df.columns and "اسم الزبون" in df.columns:
        return _import_customers(df)
    
    if "رقم الحساب" in df.columns and "اسم الحساب" in df.columns:
        return _import_customers(df)
    
    if "رقم الصنف" in df.columns or "اسم الصنف" in df.columns:
        return _import_medicines(df)
    
    return False, "❌ الملف لا يحتوي على أعمدة معروفة (أدوية أو زبائن).", []

# كلمات مفتاحية لتصنيف الحساب كمورد
SUPPLIER_KEYWORDS = ["شركة", "مورد", "تشاركية", "مذخر"]

def _is_supplier(name: str) -> bool:
    """تحقق إذا كان اسم الحساب يدل على مورد"""
    name_lower = str(name).strip()
    return any(kw in name_lower for kw in SUPPLIER_KEYWORDS)

def _import_customers(df: pd.DataFrame) -> Tuple[bool, str, list]:
    # دعم المسميات القديمة والجديدة
    column_map = {
        "رقم الزبون": "customer_id", "اسم الزبون": "customer_name",
        "رقم الحساب": "customer_id", "اسم الحساب": "customer_name",
        "مدين": "debt", "مــدين": "debt",
        "دائن": "credit", "دائـــن": "credit",
        "الحساب الرئيسي": "main_account", "الهاتف": "phone", "العنوان": "address"
    }
    df = df.rename(columns=column_map)
    needed = ["customer_id", "customer_name", "main_account", "debt", "credit", "phone", "address"]
    for col in needed:
        if col not in df.columns: df[col] = 0.0 if col in ("debt", "credit") else ""
            
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    cust_inserted, supp_inserted = 0, 0
    notifications = []
    for _, row in df.iterrows():
        try:
            cust_id = str(row["customer_id"]).strip()
            if cust_id.endswith(".0"): cust_id = cust_id[:-2]
            if not cust_id or cust_id == "nan": continue
            c_name = str(row["customer_name"])
            m_acc = str(row["main_account"]) if not pd.isna(row["main_account"]) else ""
            debt = safe_float(row["debt"], 0.0)
            credit = safe_float(row["credit"], 0.0)
            phone = str(row["phone"]) if not pd.isna(row["phone"]) else ""
            addr = str(row["address"]) if not pd.isna(row["address"]) else ""

            # تصنيف ذكي: هل هو مورد؟
            if _is_supplier(c_name):
                c.execute("INSERT OR REPLACE INTO suppliers (supplier_id, supplier_name, debt, credit) VALUES (?, ?, ?, ?)", (cust_id, c_name, debt, credit))
                supp_inserted += 1
                continue

            # زبون عادي
            c.execute("SELECT debt, credit FROM customers WHERE customer_id=?", (cust_id,))
            res = c.fetchone()
            if res:
                old_debt, old_credit = res
                if old_debt != debt or old_credit != credit:
                    c.execute("SELECT user_id FROM subscribers WHERE linked_account=?", (cust_id,))
                    subs = c.fetchall()
                    for s in subs:
                        notifications.append({
                            "user_id": s[0],
                            "customer_name": c_name,
                            "debt": debt,
                            "credit": credit
                        })

            c.execute("INSERT OR REPLACE INTO customers (customer_id, customer_name, main_account, debt, credit, phone, address) VALUES (?, ?, ?, ?, ?, ?, ?)", (cust_id, c_name, m_acc, debt, credit, phone, addr))
            cust_inserted += 1
        except: continue
    conn.commit()
    conn.close()
    msg = f"✅ تم استيراد الملف: {cust_inserted} زبون"
    if supp_inserted: msg += f" + {supp_inserted} مورد"
    msg += "."
    return True, msg, notifications

def _import_medicines(df: pd.DataFrame) -> Tuple[bool, str, list]:
    column_map = {"رقم الصنف": "item_code", "اسم الصنف": "name", "سعر البيع": "price", "سعر التكلفة": "cost_price", "الرصيد": "quantity", "ت.الصلاحية": "expiry_date", "الرقم الاصلي": "barcode"}
    df["category"] = ""
    if "فئة الصنف" in df.columns: df["category"] = df["فئة الصنف"]
    column_map["category"] = "category"
    df = df.rename(columns=column_map)
    needed = ["item_code", "name", "category", "quantity", "expiry_date", "price", "cost_price"]
    for col in needed:
        if col not in df.columns: df[col] = 0 if col in ("quantity", "price", "cost_price") else ""

    df["expiry_date"] = df["expiry_date"].apply(_format_expiry)
    df["barcode"] = df["barcode"].fillna("") if "barcode" in df.columns else ""

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE medicines SET is_new_arrival = 0")
    inserted, skipped = 0, 0
    for _, row in df.iterrows():
        try:
            item_code = str(row["item_code"]).strip()
            if item_code.endswith(".0"): item_code = item_code[:-2]
            if not item_code or item_code == "nan": continue

            name, category, expiry = str(row["name"]).strip(), str(row["category"]).strip(), str(row["expiry_date"]).strip()
            barcode_val = str(row.get("barcode", "")).strip()
            if barcode_val.endswith(".0"): barcode_val = barcode_val[:-2]
            if barcode_val == "nan": barcode_val = ""

            qty, price, cost_price = int(safe_float(row["quantity"], 0)), safe_float(row["price"], 0.0), safe_float(row["cost_price"], 0.0)
            
            c.execute("SELECT quantity, image_file_id FROM medicines WHERE item_code=?", (item_code,))
            res = c.fetchone()
            
            is_new = 0
            img_id = None
            if res:
                old_qty, img_id = res
                if qty > old_qty: is_new = 1
            else:
                is_new = 1

            c.execute("INSERT OR REPLACE INTO medicines (item_code, name, category, quantity, expiry_date, price, barcode, cost_price, image_file_id, is_new_arrival) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (item_code, name, category, qty, expiry, price, barcode_val, cost_price, img_id, is_new))
            inserted += 1
        except: skipped += 1
    conn.commit()
    conn.close()
    msg = f"✅ تم استيراد ملف الأدوية: {inserted} سجل."
    if skipped: msg += f" ({skipped} تجاهل)."
    return True, msg, []

# --------------------- PDF Generators ---------------------
def ar_text(txt: str) -> str:
    try: return get_display(arabic_reshaper.reshape(str(txt)))
    except: return str(txt)

def load_ar_font(pdf: FPDF):
    ar_font_loaded = False
    try:
        if not os.path.exists("Amiri-Regular.ttf"):
            try:
                import urllib.request
                urllib.request.urlretrieve("https://github.com/google/fonts/raw/main/ofl/amiri/Amiri-Regular.ttf", "Amiri-Regular.ttf")
            except: pass
        if os.path.exists("Amiri-Regular.ttf"):
            pdf.add_font("Amiri", "", "Amiri-Regular.ttf", uni=True)
            ar_font_loaded = True
    except: pass
    return "Amiri" if ar_font_loaded else "Arial"

def get_next_invoice_number() -> int:
    if not os.path.exists(COUNTER_FILE):
        open(COUNTER_FILE, "w", encoding="utf-8").write("1")
        return 1
    with open(COUNTER_FILE, "r+", encoding="utf-8") as f:
        content = f.read().strip()
        num = int(content) if content.isdigit() else 0
        num += 1
        f.seek(0)
        f.write(str(num))
        f.truncate()
    return num

def generate_invoice_pdf(no: int, pharmacy: str, user: str, uid: int, items: List[Tuple], original_total: float, discount_amount: float, final_total: float, method: str) -> str:
    pdf = FPDF()
    pdf.add_page()
    font_name = load_ar_font(pdf)
    pdf.set_font(font_name, size=12)

    pdf.cell(0, 8, ar_text(f"🧾 فاتورة رقم {no}"), ln=True, align="R")
    pdf.cell(0, 8, ar_text(f"🏥 الصيدلية: {pharmacy}"), ln=True, align="R")
    pdf.cell(0, 8, ar_text(f"👤 الزبون: {user} (id:{uid})"), ln=True, align="R")
    pdf.cell(0, 8, ar_text(f"💳 الدفع: {method}"), ln=True, align="R")
    pdf.ln(6)

    pdf.set_fill_color(200, 220, 255)
    pdf.cell(25, 10, ar_text("الكود"), 1, 0, "C", True)
    pdf.cell(60, 10, ar_text("الصنف"), 1, 0, "C", True)
    pdf.cell(45, 10, ar_text("الفئة"), 1, 0, "C", True)
    pdf.cell(18, 10, ar_text("الكمية"), 1, 0, "C", True)
    pdf.cell(25, 10, ar_text("السعر"), 1, 0, "C", True)
    pdf.cell(25, 10, ar_text("الإجمالي"), 1, 1, "C", True)

    for code, name, category, qty, unit_price, orig_unit in items:
        line_total = round(qty * unit_price, 2)
        pdf.cell(25, 8, str(code), 1, 0, "C")
        pdf.cell(60, 8, ar_text(name[:30]), 1, 0, "C")
        pdf.cell(45, 8, ar_text(category[:18]), 1, 0, "C")
        pdf.cell(18, 8, str(qty), 1, 0, "C")
        pdf.cell(25, 8, format_currency(unit_price), 1, 0, "C")
        pdf.cell(25, 8, format_currency(line_total), 1, 1, "C")

    pdf.ln(6)
    pdf.cell(0, 8, ar_text(f"💵 الإجمالي قبل الخصم: {format_currency(original_total)}"), ln=True, align="R")
    if discount_amount > 0: pdf.cell(0, 8, ar_text(f"💰 قيمة الخصم: -{format_currency(discount_amount)}"), ln=True, align="R")
    pdf.cell(0, 8, ar_text(f"✅ الإجمالي النهائي: {format_currency(final_total)}"), ln=True, align="R")

    fname = f"invoice_{no}.pdf"
    path = os.path.join(INVOICE_DIR, fname)
    pdf.output(path)
    return path


# --------------------- UI Keyboards ---------------------
def get_main_reply_keyboard(uid: int, search_mode: str = "medicines", linked: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("🛒 السلة"), KeyboardButton("🏥 تغيير الصيدلية")],
        [KeyboardButton("💵 كاش"), KeyboardButton("🏦 تحويل"), KeyboardButton("🕐 أجل")],
        [KeyboardButton("📦 تصفح الأصناف"), KeyboardButton("🆕 الأصناف الجديدة")],
        [KeyboardButton("🔍 بحث بالباركود")]
    ]
    if not is_admin(uid):
        if not linked: kb.append([KeyboardButton("🔗 ربط حسابي")])
        else: kb.append([KeyboardButton("📄 استعلام عن ديني")])

    if is_admin(uid):
        kb.append([KeyboardButton("👥 عرض المستخدمين"), KeyboardButton("📊 تقرير الصلاحية")])
        toggle_text = "👤 بحث زبائن" if search_mode == "medicines" else "🔍 بحث أدوية"
        kb.append([KeyboardButton(toggle_text), KeyboardButton("🚚 بحث موردين")])
        kb.append([KeyboardButton("📢 إشعار عام")])
        kb.append([KeyboardButton("🗑️ حذف البيانات"), KeyboardButton("🔄 إعادة تشغيل البوت")])
        
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# --------------------- Handlers ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_name = update.effective_user.first_name or update.effective_user.username or f"User{uid}"
    active_users[uid] = user_name
    
    register_subscriber(uid, 'admin' if is_admin(uid) else 'customer')
    sub = get_subscriber(uid)
    is_linked = bool(sub and sub[1])

    settings = load_user_settings(uid)
    context.user_data["discount_mode"] = settings["discount_mode"]
    context.user_data["search_mode"] = "medicines"
    
    if uid not in user_carts:
        user_carts[uid] = {"items": [], "pharmacy": settings["pharmacy"]}

    kb = [
        [InlineKeyboardButton("💵 كاش (خصم 10%)", callback_data="mode_cash")],
        [InlineKeyboardButton("🏦 تحويل (خصم 5%)", callback_data="mode_transfer")],
        [InlineKeyboardButton("🕐 أجل (بدون خصم)", callback_data="mode_credit")],
    ]

    msg = "👋 أهلاً بك في منظومة شركة ابن النفيس !\n\nاختر طريقة الدفع:\n💵 كاش = خصم 10%\n🏦 تحويل = خصم 5%\n🕐 أجل = بدون خصم"
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    
    if not is_admin(uid) and not is_linked:
        await update.message.reply_text("💡 يرجى ربط حسابك في المنظومة للتمكن من الاستعلام عن ديونك.\nاضغط على '🔗 ربط حسابي' من القائمة.", reply_markup=get_main_reply_keyboard(uid, linked=is_linked))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.message.from_user.id
    user_name = update.effective_user.first_name or update.effective_user.username or f"User{uid}"
    active_users[uid] = user_name
    
    current_mode = context.user_data.get("search_mode", "medicines")
    sub = get_subscriber(uid)
    is_linked = bool(sub and sub[1])

    if context.user_data.get("waiting_for_link_account"):
        if text.lower() == "إلغاء":
            context.user_data["waiting_for_link_account"] = False
            return await update.message.reply_text("✅ تم إلغاء عملية الربط.", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
        
        success = link_account(uid, text)
        if success:
            context.user_data["waiting_for_link_account"] = False
            return await update.message.reply_text("✅ تم ربط حسابك بالمنظومة بنجاح!", reply_markup=get_main_reply_keyboard(uid, current_mode, linked=True))
        else:
            return await update.message.reply_text("❌ رقم الحساب غير موجود في المنظومة. تأكد من الرقم أو اكتب 'إلغاء'.")

    if not is_admin(uid) and text.isdigit():
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT customer_id, customer_name, main_account, debt, credit FROM customers WHERE customer_id=?", (text,))
        res = c.fetchone()
        conn.close()
        if res:
            cid, cname, m_acc, debt, credit = res
            return await update.message.reply_text(f"👤 **بيانات الزبون**\n🔢 رقم الزبون: `{cid}`\n🏷 الاسم: {cname}\n🏥 الحساب: {m_acc}\n🔴 مدين: {format_currency(debt)}\n🟢 دائن: {format_currency(credit)}\n💰 **الرصيد: {get_net_balance_details(debt, credit)}**", parse_mode="Markdown")

    if text == "🔗 ربط حسابي" and not is_admin(uid):
        if is_linked: return await update.message.reply_text("حسابك مربوط مسبقاً.")
        context.user_data["waiting_for_link_account"] = True
        return await update.message.reply_text("🔢 أرسل رقم حسابك في المنظومة لربطه بالتليجرام (أو اكتب 'إلغاء'):", reply_markup=ReplyKeyboardMarkup([["إلغاء"]], resize_keyboard=True))

    if text == "📄 استعلام عن ديني" and not is_admin(uid):
        if not is_linked: return await update.message.reply_text("❌ حسابك غير مربوط. يرجى ربط حسابك أولاً.")
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT customer_id, customer_name, main_account, debt, credit FROM customers WHERE customer_id=?", (sub[1],))
        res = c.fetchone()
        conn.close()
        if res:
            cid, cname, m_acc, debt, credit = res
            return await update.message.reply_text(f"👤 **كشف الحساب الخاص بك**\n🏷 الاسم: {cname}\n🏥 الحساب: {m_acc}\n🔴 مدين (عليك): {format_currency(debt)}\n🟢 دائن (لك): {format_currency(credit)}\n💰 **الرصيد النهائي: {get_net_balance_details(debt, credit)}**", parse_mode="Markdown")
        else: return await update.message.reply_text("❌ لم أتمكن من العثور على بياناتك في المنظومة.")

    if context.user_data.get("waiting_for_pharmacy"):
        cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
        cart["pharmacy"] = text
        user_carts[uid] = cart
        context.user_data["waiting_for_pharmacy"] = False
        return await update.message.reply_text(f"✅ تم حفظ اسم الصيدلية: {text}", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))

    if text in ("🛒 السلة", "🏥 تغيير الصيدلية", "💵 كاش", "🏦 تحويل", "🕐 أجل", "📦 تصفح الأصناف", "🆕 الأصناف الجديدة", "🔍 بحث بالباركود"):
        if text == "🔍 بحث بالباركود": return await update.message.reply_text("📷 يرجى تمرير المنتج على قارئ الباركود، أو كتابة رقم الباركود مباشرة في الدردشة وسيتم البحث عنه فوراً.")
        if text == "📦 تصفح الأصناف": return await _show_browse_page(update.message, uid, 0, filter_new=False)
        if text == "🆕 الأصناف الجديدة": return await _show_browse_page(update.message, uid, 0, filter_new=True)
        if text == "🛒 السلة": return await _send_cart_message(update.message, uid, context, edit=False)
        if text == "🏥 تغيير الصيدلية":
            context.user_data["waiting_for_pharmacy"] = True
            return await update.message.reply_text("✍️ اكتب اسم الصيدلية الجديدة:", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
        if text == "💵 كاش":
            context.user_data["discount_mode"] = "cash"
            _recalc_cart_prices(uid, "cash")
            save_user_settings(uid, discount_mode="cash")
            await update.message.reply_text("✅ تم التبديل إلى: كاش (خصم 10%).", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
            return await _send_cart_message(update.message, uid, context, edit=False)
        if text == "🏦 تحويل":
            context.user_data["discount_mode"] = "transfer"
            _recalc_cart_prices(uid, "transfer")
            save_user_settings(uid, discount_mode="transfer")
            await update.message.reply_text("✅ تم التبديل إلى: تحويل (خصم 5%).", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
            return await _send_cart_message(update.message, uid, context, edit=False)
        if text == "🕐 أجل":
            context.user_data["discount_mode"] = "credit"
            _recalc_cart_prices(uid, "credit")
            save_user_settings(uid, discount_mode="credit")
            await update.message.reply_text("✅ تم التبديل إلى: أجل (بدون خصم).", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
            return await _send_cart_message(update.message, uid, context, edit=False)

    if is_admin(uid):
        if text == "👥 عرض المستخدمين": return await _show_users_list(update.message, uid)
        if text == "📊 تقرير الصلاحية": return await _generate_expiry_report(update.message, uid)
        if text == "📢 إشعار عام":
            context.user_data["waiting_for_notify_message"] = True
            return await update.message.reply_text("✍️ اكتب الرسالة التي تريد إرسالها لجميع المستخدمين:")
        if text == "🗑️ حذف البيانات":
            kb = [[InlineKeyboardButton("🗑️ حذف ملفات Excel", callback_data="del_excel")], [InlineKeyboardButton("☢️ حذف بيانات القاعدة", callback_data="del_db")], [InlineKeyboardButton("🚫 إلغاء", callback_data="del_cancel")]]
            return await update.message.reply_text("⚠️ **قائمة الحذف المتقدمة**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        if text == "🔄 إعادة تشغيل البوت":
            kb = [[InlineKeyboardButton("✅ نعم", callback_data="restart_confirm")], [InlineKeyboardButton("❌ إلغاء", callback_data="restart_cancel")]]
            return await update.message.reply_text("⚠️ **هل أنت متأكد؟**", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        if text in ("👤 بحث زبائن", "🔍 بحث أدوية"):
            new_mode = "customers" if text == "👤 بحث زبائن" else "medicines"
            context.user_data["search_mode"] = new_mode
            return await update.message.reply_text(f"🔄 تم تفعيل وضع البحث عن: {'الزبائن 👤' if new_mode == 'customers' else 'الأدوية 🔍'}", reply_markup=get_main_reply_keyboard(uid, new_mode, is_linked))
        if text == "🚚 بحث موردين":
            context.user_data["search_mode"] = "suppliers"
            return await update.message.reply_text("🔄 تم تفعيل وضع البحث عن: الموردين 🚚\nاكتب اسم أو رقم المورد للبحث.", reply_markup=get_main_reply_keyboard(uid, "suppliers", is_linked))
        
        if context.user_data.get("waiting_for_notify_message"):
            context.user_data.pop("waiting_for_notify_message", None)
            success, fail = 0, 0
            for u in list(active_users.keys()):
                try:
                    await context.bot.send_message(chat_id=u, text=text)
                    success += 1
                except: fail += 1
            return await update.message.reply_text(f"✅ تم الإرسال.\nنجاح: {success}\nفشل: {fail}", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    query = f"%{text}%"

    if current_mode == "customers" and is_admin(uid):
        c.execute("SELECT customer_id, customer_name, main_account, debt, credit FROM customers WHERE customer_name LIKE ? OR customer_id LIKE ? LIMIT 50", (query, query))
        results = c.fetchall()
        conn.close()
        if not results: return await update.message.reply_text(f"❌ لم يتم العثور على زبون '{text}'")
        kb = [[InlineKeyboardButton(f"{cname} ({cid}) | {get_net_balance_details(debt, credit)}", callback_data=f"select_cust_{cid}")] for cid, cname, m_acc, debt, credit in results]
        return await update.message.reply_text("👤 نتائج بحث الزبائن:", reply_markup=InlineKeyboardMarkup(kb))

    if current_mode == "suppliers" and is_admin(uid):
        c.execute("SELECT supplier_id, supplier_name, debt, credit FROM suppliers WHERE supplier_name LIKE ? OR supplier_id LIKE ? LIMIT 50", (query, query))
        results = c.fetchall()
        conn.close()
        if not results: return await update.message.reply_text(f"❌ لم يتم العثور على مورد '{text}'")
        kb = []
        for sid, sname, debt, credit in results:
            net = credit - debt
            if net > 0:
                balance_str = f"🟢 لنا: {format_currency(net)}"
            elif net < 0:
                balance_str = f"🔴 علينا: {format_currency(abs(net))}"
            else:
                balance_str = "⚪ متوازن"
            kb.append([InlineKeyboardButton(f"{sname} ({sid}) | {balance_str}", callback_data=f"select_supp_{sid}")])
        return await update.message.reply_text("🚚 نتائج بحث الموردين:", reply_markup=InlineKeyboardMarkup(kb))

    c.execute("SELECT item_code, name, category, price, quantity, expiry_date, barcode, image_file_id FROM medicines WHERE name LIKE ? OR item_code LIKE ? OR barcode LIKE ? LIMIT 100", (query, query, query))
    meds = c.fetchall()
    conn.close()

    if not meds: return await update.message.reply_text("❌ لا توجد نتائج.")

    mode = context.user_data.get("discount_mode", "credit")
    kb = []
    for item in meds[:50]:
        code, name, category, price, qty, expiry, barcode, img = item
        safe_price = price if price else 0.0
        price_disp = round(safe_price * (1 - DISCOUNT_RATE) if mode == "cash" else safe_price * 0.95 if mode == "transfer" else safe_price, 2)
        cat_str = f" | {category}" if category else ""
        label = f"{name}{cat_str} | {price_disp}د | رصيد:{qty} | كود:{code}" if is_admin(uid) else f"{name}{cat_str} | {price_disp}د | كود:{code}"
        kb.append([InlineKeyboardButton(label, callback_data=f"select_{code}")])

    await update.message.reply_text("🔎 اختر من النتائج:", reply_markup=InlineKeyboardMarkup(kb))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    
    photo_file_id = update.message.photo[-1].file_id
    f = await context.bot.get_file(photo_file_id)
    byte_arr = io.BytesIO()
    await f.download_to_memory(byte_arr)
    byte_arr.seek(0)
    
    barcodes = []
    try:
        file_bytes = np.asarray(bytearray(byte_arr.read()), dtype=np.uint8)
        img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
        import zxingcpp
        results = zxingcpp.read_barcodes(img)
        barcodes = [res.text for res in results if res.text]
    except Exception as e:
        pass

    if barcodes:
        barcode_val = barcodes[0].strip()
        barcode_clean = barcode_val.lstrip('0') if barcode_val.startswith('0') else barcode_val
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT item_code, name, category, price, quantity, expiry_date, barcode, image_file_id FROM medicines WHERE barcode=? OR item_code=? OR barcode=? OR item_code=?", (barcode_val, barcode_val, barcode_clean, barcode_clean))
        res = c.fetchone()
        conn.close()
        
        if res:
            code, name, category, price, qty, expiry, barcode, img_id = res
            safe_price = price if price else 0.0
            mode = context.user_data.get("discount_mode", "credit")
            price_disp = round(safe_price * (1 - DISCOUNT_RATE) if mode == "cash" else safe_price * 0.95 if mode == "transfer" else safe_price, 2)
            cat_str = f" | {category}" if category else ""
            label = f"{name}{cat_str} | {price_disp}د | رصيد:{qty} | كود:{code}" if is_admin(uid) else f"{name}{cat_str} | {price_disp}د | كود:{code}"
            kb = [[InlineKeyboardButton(label, callback_data=f"select_{code}")]]
            return await update.message.reply_text(f"✅ تم قراءة الباركود: {barcode_val}\n🔎 النتيجة:", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(f"❌ تم قراءة الباركود: {barcode_val} ولكن الصنف غير موجود في القاعدة.")
            if not is_admin(uid): return

    if not is_admin(uid):
        if not barcodes:
            return await update.message.reply_text("❌ لم أتمكن من قراءة الباركود من الصورة. تأكد من وضوح الصورة وتوجيه الكاميرا مباشرة نحو الباركود.")
        return

    state = context.user_data.get("waiting_for_image_for")
    if state:
        code = state
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("UPDATE medicines SET image_file_id=? WHERE item_code=?", (photo_file_id, code))
        conn.commit()
        conn.close()
        context.user_data.pop("waiting_for_image_for", None)
        await update.message.reply_text(f"✅ تمت إضافة الصورة بنجاح للصنف {code}.")
    elif not barcodes:
        await update.message.reply_text("❌ لم أتمكن من قراءة الباركود من الصورة.")

async def upload_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if not is_admin(uid): return await update.message.reply_text("🚫 متاح للمدراء فقط.")
    doc = update.message.document
    if not doc or not doc.file_name.endswith('.xlsx'): return await update.message.reply_text("📂 الرجاء إرسال ملف Excel (.xlsx).")
    
    path = f"meds_{uid}.xlsx"
    f = await context.bot.get_file(doc.file_id)
    await f.download_to_drive(path)
    ok, msg, notifications = import_excel_to_db(path)
    await update.message.reply_text(msg)
    
    for n in notifications:
        try:
            net_balance = get_net_balance_details(n['debt'], n['credit'])
            notif_text = f"🔔 **إشعار تحديث الرصيد**\nعزيزي {n['customer_name']}،\nتم تحديث رصيد حسابك في المنظومة.\n🔴 مدين (عليك): {format_currency(n['debt'])}\n🟢 دائن (لك): {format_currency(n['credit'])}\n💰 **الرصيد النهائي: {net_balance}**"
            await context.bot.send_message(chat_id=n["user_id"], text=notif_text, parse_mode="Markdown")
        except:
            pass

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query.query.strip()
    if not query: return
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT item_code, name, category, price, quantity FROM medicines WHERE name LIKE ? LIMIT 30", (f"%{query}%",))
    meds = c.fetchall()
    conn.close()

    results = []
    for code, name, cat, price, qty in meds:
        p = price or 0.0
        text = f"الصنف: {name}\nالكود: {code}\nالفئة: {cat}\nالسعر: {format_currency(p)}\nالمخزون المتوفر: {qty}"
        results.append(
            InlineQueryResultArticle(
                id=code,
                title=f"{name} ({qty} قطعة)",
                description=f"السعر: {format_currency(p)} د | الكود: {code}",
                input_message_content=InputTextMessageContent(text)
            )
        )
    await update.inline_query.answer(results, cache_time=10)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""

    
    if data in ("mode_cash", "mode_credit", "mode_transfer"):
        mode = "cash" if data == "mode_cash" else "transfer" if data == "mode_transfer" else "credit"
        mode_str = "كاش (خصم 10%)" if mode == "cash" else "تحويل (خصم 5%)" if mode == "transfer" else "أجل (بدون خصم)"
        context.user_data["discount_mode"] = mode
        _recalc_cart_prices(uid, mode)
        save_user_settings(uid, discount_mode=mode)
        current_mode = context.user_data.get("search_mode", "medicines")
        sub = get_subscriber(uid)
        is_linked = bool(sub and sub[1])
        
        # Show alert directly
        await q.answer(f"تم اختيار الدفع: {mode_str}", show_alert=True)
        
        # Edit the message if it was the start message
        try:
            if context.user_data.get("last_cart_message_id") != q.message.message_id:
                await q.edit_message_text(f"👋 أهلاً بك في نظام الصيدلية المتكامل!\n\n✅ تم اختيار طريقة الدفع: {mode_str}")
        except Exception as e:
            pass

        try:
            # Send confirmation with the main keyboard
            await q.message.reply_text(f"✅ تم التبديل إلى: {mode_str}.", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
            
            # If clicked from inside the cart, update the cart message
            if context.user_data.get("last_cart_message_id") == q.message.message_id:
                await _send_cart_message(q.message, uid, context, edit=True)
        except Exception as e:
            pass
            
        return

    if data == "change_pharmacy":
        context.user_data["waiting_for_pharmacy"] = True
        try: return await q.edit_message_text("✍️ اكتب اسم الصيدلية الجديدة:")
        except: return await q.message.reply_text("✍️ اكتب اسم الصيدلية الجديدة:")

    if data == "clear_cart":
        kb = [[InlineKeyboardButton("نعم، امسح", callback_data="clear_confirm_yes")], [InlineKeyboardButton("لا، إلغاء", callback_data="clear_confirm_no")]]
        try: return await q.edit_message_text("🗑️ هل أنت متأكد أنك تريد مسح السلة بالكامل؟", reply_markup=InlineKeyboardMarkup(kb))
        except: return await q.message.reply_text("🗑️ هل أنت متأكد أنك تريد مسح السلة بالكامل؟", reply_markup=InlineKeyboardMarkup(kb))

    if data == "clear_confirm_yes":
        user_carts[uid] = {"items": [], "pharmacy": ""}
        current_mode = context.user_data.get("search_mode", "medicines")
        sub = get_subscriber(uid)
        is_linked = bool(sub and sub[1])
        try: await q.edit_message_text("🗑️ تم مسح السلة بالكامل.")
        except: await q.message.reply_text("🗑️ تم مسح السلة بالكامل.")
        return await q.message.reply_text("🔙 عاد للقائمة الرئيسية:", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))

    if data == "clear_confirm_no":
        return await _send_cart_message(q.message, uid, context, edit=True)

    if data == "back_main":
        current_mode = context.user_data.get("search_mode", "medicines")
        sub = get_subscriber(uid)
        is_linked = bool(sub and sub[1])
        try: return await q.message.reply_text("⬅️ رجعت للقائمة الرئيسية.", reply_markup=get_main_reply_keyboard(uid, current_mode, is_linked))
        except: return

    if data.startswith("cart_"):
        parts = data.split("_", 3)
        if len(parts) < 3: return await q.edit_message_text("⚠️ أمر غير معروف.")
        action = parts[1]
        if action == "del":
            code = parts[2]
            cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
            for i, item in enumerate(cart["items"]):
                if item[0] == code:
                    cart["items"].pop(i)
                    break
            user_carts[uid] = cart
            return await _send_cart_message(q.message, uid, context, edit=True)
        elif action == "adjust":
            amount = int(parts[2])
            code = parts[3]
            cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
            for i, item in enumerate(cart["items"]):
                if item[0] == code:
                    code_i, name_i, cat_i, qty_i, unit_i, orig_i = item
                    qty_i += amount
                    if qty_i <= 0: cart["items"].pop(i)
                    else: cart["items"][i] = (code_i, name_i, cat_i, qty_i, unit_i, orig_i)
                    break
            user_carts[uid] = cart
            return await _send_cart_message(q.message, uid, context, edit=True)
    
    if data.startswith("add_img_"):
        if not is_admin(uid): return
        code = data.split("_")[2]
        context.user_data["waiting_for_image_for"] = code
        await q.edit_message_text(f"📸 أرسل الصورة الآن للصنف كود: {code} ...")
        return

    if data == "del_cancel" or data == "restart_cancel": return await q.edit_message_text("✅ تم الإلغاء.")
    if data == "del_db_confirm":
        if not is_admin(uid): return
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("DELETE FROM medicines")
        c.execute("DELETE FROM customers")
        conn.commit()
        conn.close()
        return await q.edit_message_text("☢️ تم تفريغ القاعدة بنجاح.")
    if data == "restart_confirm":
        if not is_admin(uid): return
        await q.edit_message_text("🔄 جاري إعادة التشغيل...")
        restart_program()
        return

    if data.startswith("browse_") or data.startswith("new_"):
        is_new = data.startswith("new_")
        prefix_len = 4 if is_new else 7
        page = int(data[prefix_len:])
        await _show_browse_page(q.message, uid, page, edit=True, filter_new=is_new)
        return
        
    if data.startswith("select_"):
        if data.startswith("select_cust_"):
            if not is_admin(uid): return
            cid = data.split("_", 2)[2]
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT customer_id, customer_name, main_account, debt, credit FROM customers WHERE customer_id=?", (cid,))
            res = c.fetchone()
            conn.close()
            if res: await q.edit_message_text(f"👤 **{res[1]}**\nرقم: {cid}\nحساب: {res[2]}\nالرصيد: {get_net_balance_details(res[3], res[4])}", parse_mode="Markdown")
            return

        if data.startswith("select_supp_"):
            if not is_admin(uid): return
            sid = data.split("_", 2)[2]
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT supplier_id, supplier_name, debt, credit FROM suppliers WHERE supplier_id=?", (sid,))
            res = c.fetchone()
            conn.close()
            if res:
                s_id, s_name, debt, credit = res
                net = credit - debt
                if net > 0:
                    balance_str = f"🟢 لنا عند المورد: {format_currency(net)}"
                elif net < 0:
                    balance_str = f"🔴 علينا للمورد: {format_currency(abs(net))}"
                else:
                    balance_str = "⚪ الحساب متوازن"
                await q.edit_message_text(f"🚚 **بيانات المورد**\n\n🏷 الاسم: {s_name}\n🔢 الرقم: {s_id}\n🔴 مدين: {format_currency(debt)}\n🟢 دائن: {format_currency(credit)}\n💰 **صافي الرصيد: {balance_str}**", parse_mode="Markdown")
            return

        code = data.split("_", 1)[1]
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT name, price, quantity, image_file_id FROM medicines WHERE item_code=?", (code,))
        med = c.fetchone()
        conn.close()
        if not med: return await q.edit_message_text("❌ غير موجود.")
        
        name, price, qty, img_id = med
        context.user_data["selecting_code"] = code
        context.user_data["selecting_name"] = name
        context.user_data["selecting_price"] = price
        context.user_data["selecting_quantity"] = qty
        context.user_data["current_qty"] = 0
        
        if img_id:
            try: await context.bot.send_photo(chat_id=uid, photo=img_id)
            except: pass
                
        await _show_qty_selection(q.message, context, uid, name, code, img_id, edit=False)
        return

    if data.startswith("qty_"):
        if "selecting_code" not in context.user_data: return await q.edit_message_text("⚠️ لا يوجد صنف محدد.")
        code = context.user_data["selecting_code"]
        name = context.user_data["selecting_name"]
        curr_qty = context.user_data.get("current_qty", 0)
        
        if data == "qty_add":
            if curr_qty <= 0: return await q.edit_message_text("⚠️ اختر كمية > صفر.")
            conn = sqlite3.connect(DB_FILE)
            c = conn.cursor()
            c.execute("SELECT quantity, price, category FROM medicines WHERE item_code=?", (code,))
            med = c.fetchone()
            if not med: 
                conn.close()
                return await q.edit_message_text("❌ غير موجود.")
            stock, price, cat = med
            if curr_qty > stock:
                conn.close()
                return await q.edit_message_text("❌ الكمية غير متوفرة.")
                
            mode = context.user_data.get("discount_mode", "credit")
            safe_price = price or 0.0
            unit_price = round(safe_price * (1-DISCOUNT_RATE) if mode=="cash" else safe_price*0.95 if mode=="transfer" else safe_price, 2)
            
            cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
            found = False
            for i, it in enumerate(cart["items"]):
                if it[0] == code:
                    cart["items"][i] = (it[0], it[1], it[2], it[3]+curr_qty, it[4], it[5])
                    found = True; break
            if not found: cart["items"].append((code, name, cat, curr_qty, unit_price, safe_price))
            user_carts[uid] = cart
            
            c.execute("UPDATE medicines SET quantity = quantity - ? WHERE item_code = ?", (curr_qty, code))
            conn.commit()
            
            c.execute("SELECT quantity FROM medicines WHERE item_code=?", (code,))
            new_qty = c.fetchone()[0]
            conn.close()
            
            if new_qty < 5:
                for a in ADMINS:
                    try: await context.bot.send_message(chat_id=a, text=f"⚠️ تنبيه مخزون: الصنف '{name}' (كود: {code}) انخفض مخزونه إلى {new_qty} قطع فقط!")
                    except: pass
                    
            return await q.edit_message_text(f"✅ تمت إضافة {curr_qty} إلى السلة.")
            
        elif data == "qty_cancel":
            return await q.edit_message_text("❌ تم الإلغاء.")
        
        parts = data.split("_")
        amt = int(parts[2])
        if parts[1] == "inc": curr_qty += amt
        else: curr_qty = max(0, curr_qty - amt)
        context.user_data["current_qty"] = curr_qty
        
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT image_file_id FROM medicines WHERE item_code=?", (code,))
        res = c.fetchone()
        conn.close()
        img_id = res[0] if res else None
        
        await _show_qty_selection(q.message, context, uid, name, code, img_id, edit=True)
        return

    if data == "finish_order":
        cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
        if not cart["items"]: return await q.edit_message_text("❌ السلة فارغة.")
        orig = sum(i[3]*i[5] for i in cart["items"])
        final = sum(i[3]*i[4] for i in cart["items"])
        context.user_data["order_summary"] = {"orig": orig, "final": final, "discount": orig-final, "items": cart["items"], "pharmacy": cart.get("pharmacy", "")}
        kb = [[InlineKeyboardButton("✅ نعم - أصدر الفاتورة", callback_data="pay_confirm")], [InlineKeyboardButton("🔙 لا", callback_data="back_to_cart")]]
        return await q.edit_message_text(f"💵 الإجمالي قبل الخصم: {format_currency(orig)}\n💰 الخصم: {format_currency(orig-final)}\n✅ النهائي: {format_currency(final)}\nإصدار؟", reply_markup=InlineKeyboardMarkup(kb))

    if data == "back_to_cart": return await _send_cart_message(q.message, uid, context, edit=True)

    if data == "pay_confirm":
        s = context.user_data.get("order_summary")
        if not s: return await q.edit_message_text("⚠️ لا يوجد طلب.")
        ino = get_next_invoice_number()
        mode = context.user_data.get("discount_mode")
        method = "كاش" if mode == "cash" else "تحويل" if mode == "transfer" else "أجل"
        path = generate_invoice_pdf(ino, s["pharmacy"], q.from_user.first_name, uid, s["items"], s["orig"], s["discount"], s["final"], method)
        
        await q.message.reply_document(open(path, "rb"), caption=f"✅ فاتورة رقم {ino}")
        for a in ADMINS:
            try: await context.bot.send_document(chat_id=a, document=open(path, "rb"), caption=f"🧾 فاتورة جديدة\nالزبون: {q.from_user.first_name}\nالإجمالي: {format_currency(s['final'])}")
            except: pass
        user_carts[uid] = {"items": [], "pharmacy": ""}
        return await q.edit_message_text("✅ تم الإصدار.")

async def _show_browse_page(source, uid, page: int, edit: bool = False, filter_new: bool = False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    where_clause = "WHERE is_new_arrival = 1" if filter_new else ""
    c.execute(f"SELECT item_code, name, price, quantity FROM medicines {where_clause} LIMIT 10 OFFSET ?", (page * 10,))
    meds = c.fetchall()
    
    c.execute(f"SELECT COUNT(*) FROM medicines {where_clause}")
    total_count = c.fetchone()[0]
    conn.close()

    if not meds and page == 0:
        msg = "❌ لا توجد أصناف جديدة." if filter_new else "❌ لا توجد أصناف في المخزون."
        if edit: 
            try: await source.edit_text(msg)
            except: pass
        else: await source.reply_text(msg)
        return

    kb = []
    for code, name, price, qty in meds:
        safe_price = price or 0.0
        if is_admin(uid):
            label = f"💊 {name[:20]} | رصيد: {qty} | {safe_price}د"
        else:
            label = f"💊 {name[:25]} | {safe_price}د"
        kb.append([InlineKeyboardButton(label, callback_data=f"select_{code}")])

    nav_row = []
    prefix = "new_" if filter_new else "browse_"
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ السابق", callback_data=f"{prefix}{page-1}"))
    if (page + 1) * 10 < total_count:
        nav_row.append(InlineKeyboardButton("التالي ➡️", callback_data=f"{prefix}{page+1}"))
        
    if nav_row:
        kb.append(nav_row)

    title = "🆕 الأصناف الجديدة" if filter_new else "📦 تصفح الأصناف"
    msg = f"{title} (صفحة {page+1}):\nاضغط على الصنف لعرض الصورة والكمية."
    if edit:
        try: await source.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb))
        except: pass
    else:
        await source.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def _show_qty_selection(source, context, uid, name, code, img_id, edit=False):
    qty = context.user_data.get("current_qty", 0)
    price = context.user_data.get("selecting_price", 0)
    mode = context.user_data.get("discount_mode", "credit")
    safe_price = price or 0.0
    price_disp = round(safe_price * (1-DISCOUNT_RATE) if mode=="cash" else safe_price*0.95 if mode=="transfer" else safe_price, 2)
    
    msg = f"الصنف: {name}\nالكمية: {qty}\nالسعر: {price_disp} د"
    if is_admin(uid): msg += f"\nرصيد: {context.user_data.get('selecting_quantity', 0)}"
        
    kb = [
        [InlineKeyboardButton("+1", callback_data="qty_inc_1"), InlineKeyboardButton("+5", callback_data="qty_inc_5"), InlineKeyboardButton("+50", callback_data="qty_inc_50")],
        [InlineKeyboardButton("-1", callback_data="qty_dec_1"), InlineKeyboardButton("-5", callback_data="qty_dec_5"), InlineKeyboardButton("-50", callback_data="qty_dec_50")],
        [InlineKeyboardButton("إضافة", callback_data="qty_add"), InlineKeyboardButton("إلغاء", callback_data="qty_cancel")]
    ]
    if is_admin(uid) and not img_id: kb.append([InlineKeyboardButton("📸 إضافة صورة", callback_data=f"add_img_{code}")])
        
    if edit: await source.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else: await source.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))

async def _send_cart_message(source, uid: int, context: ContextTypes.DEFAULT_TYPE = None, edit: bool = False):
    cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
    sub = get_subscriber(uid)
    is_linked = bool(sub and sub[1])
    current_mode = context.user_data.get("search_mode", "medicines")
    
    if not cart["items"]:
        msg = "🛒 السلة فارغة."
        markup = get_main_reply_keyboard(uid, current_mode, is_linked)
    else:
        lines = []
        total = 0.0
        kb_rows = []
        for code, name, cat, qty, unit_price, orig in cart["items"][:14]: 
            line_total = round(qty * unit_price, 2)
            total += line_total
            lines.append(f"• {name[:30]} ×{qty} = {format_currency(line_total)}")
            kb_rows.append([InlineKeyboardButton("❌", callback_data=f"cart_del_{code}")])

        msg = f"🛒 السلة:\n\n" + "\n".join(lines) + f"\n\n🏥 الصيدلية: {cart.get('pharmacy') or 'غير محدد'}\n💵 الإجمالي: {format_currency(total)}"
        kb_rows.append([InlineKeyboardButton("✅ إنهاء الطلب", callback_data="finish_order")])
        markup = InlineKeyboardMarkup(kb_rows)

    if edit and context.user_data.get("last_cart_message_id"):
        try: await context.bot.edit_message_text(chat_id=source.chat.id, message_id=context.user_data["last_cart_message_id"], text=msg, reply_markup=markup)
        except: pass
    else:
        sent = await context.bot.send_message(chat_id=source.chat.id, text=msg, reply_markup=markup)
        context.user_data["last_cart_message_id"] = sent.message_id

async def _show_users_list(source, uid):
    users = [f"{u_name} (ID: {u_id}) - سلة: {len(user_carts.get(u_id, {'items': []})['items'])} صنف" for u_id, u_name in active_users.items()]
    msg = "👥 قائمة المستخدمين النشطين:\n" + "\n".join(users) if users else "👥 لا يوجد مستخدمين نشطين."
    await source.reply_text(msg, reply_markup=get_main_reply_keyboard(uid, linked=False))

async def _generate_expiry_report(source, uid):
    from datetime import datetime, timedelta
    now = datetime.now()
    expiry_threshold = now + timedelta(days=45)

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT name, item_code, expiry_date, quantity FROM medicines")
    all_meds = c.fetchall()
    conn.close()

    expiring = []
    for name, code, expiry, qty in all_meds:
        if not expiry: continue
        try:
            exp_str = expiry.strip()
            if "-" in exp_str: exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
            else: continue
            if exp_date <= expiry_threshold: expiring.append((name, code, expiry, qty))
        except: continue

    if not expiring: return await source.reply_text("📊 لا توجد أصناف منتهية الصلاحية قريبًا.")

    pdf = FPDF()
    pdf.add_page()
    font_name = load_ar_font(pdf)
    pdf.set_font(font_name, size=12)
    pdf.cell(0, 10, ar_text("📊 تقرير الأصناف المنتهية الصلاحية"), ln=True, align="C")
    for name, code, expiry, qty in expiring:
        pdf.cell(0, 10, ar_text(f"{name} | {code} | {expiry} | {qty}"), ln=True)

    path = os.path.join(INVOICE_DIR, f"expiry_{now.strftime('%Y%m%d')}.pdf")
    pdf.output(path)
    await source.reply_document(open(path, "rb"), caption="📊 تقرير الصلاحية")

async def _generate_profit_report(source, uid):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT item_code, name, quantity, price, cost_price FROM medicines WHERE quantity > 0")
    meds = c.fetchall()
    conn.close()
    
    if not meds: return await source.reply_text("لا توجد أدوية متوفرة.")
        
    pdf = FPDF()
    pdf.add_page()
    font_name = load_ar_font(pdf)
    pdf.set_font(font_name, size=12)
    
    pdf.cell(0, 10, ar_text("📊 تقرير أرباح المخزون المتوفر"), ln=True, align="C")
    pdf.ln(5)
    
    total_expected_profit = 0
    for code, name, qty, price, cost in meds:
        p = price or 0.0
        c_p = cost or 0.0
        profit_per_unit = p - c_p
        total_profit = profit_per_unit * qty
        total_expected_profit += total_profit
        
        pdf.cell(0, 8, ar_text(f"{name[:20]} | بيع: {p} | تكلفة: {c_p} | كمية: {qty} | ربح متوقع: {round(total_profit,2)}"), ln=True)
        
    pdf.ln(5)
    pdf.cell(0, 10, ar_text(f"💰 إجمالي الأرباح المتوقعة: {format_currency(total_expected_profit)}"), ln=True, align="R")
    
    path = os.path.join(INVOICE_DIR, "profit_report.pdf")
    pdf.output(path)
    await source.reply_document(open(path, "rb"), caption="📊 تقرير الأرباح")

async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    for admin in ADMINS:
        try:
            await context.bot.send_document(chat_id=admin, document=open(DB_FILE, "rb"), caption="🔄 نسخة احتياطية أسبوعية (pharmacy.db)")
        except: pass

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.job_queue.run_repeating(backup_job, interval=604800, first=10)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_file))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(InlineQueryHandler(inline_query))

    logger.info("🤖 Bot starting...")
    app.run_polling()

if __name__ == "__main__":
    main()
