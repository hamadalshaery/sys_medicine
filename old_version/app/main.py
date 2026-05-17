import os
import httpx
from fastapi import FastAPI, Request, Depends, HTTPException, UploadFile, File, Form, Body, status
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from .database import engine, Base, get_db, SessionLocal
from . import models, crud, auth, utils
from .auth import authenticate_user, create_access_token, get_current_user, get_current_admin_user

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

app = FastAPI(title="Pharmacy - ابن النفيس")
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def render(tpl: str, request: Request, **ctx):
    """Starlette 0.x + 1.x compatible TemplateResponse."""
    return templates.TemplateResponse(request=request, name=tpl, context=ctx)


@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        crud.get_or_create_user(
            db,
            os.getenv("ADMIN_USERNAME", "admin"),
            os.getenv("ADMIN_PASSWORD", "Admin@123"),
            role="admin"
        )


# ── Auth ──────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def home():
    return RedirectResponse("/store")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render("login.html", request, error=None)


@app.post("/login")
def do_login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = authenticate_user(db, username.strip(), password)
    if not user:
        return render("login.html", request, error="بيانات تسجيل الدخول غير صحيحة")
    token = create_access_token({"sub": user.username})
    resp = RedirectResponse(url="/dashboard" if user.role == "admin" else "/store", status_code=302)
    resp.set_cookie("access_token", token, httponly=True, max_age=28800)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


# ── Pages ─────────────────────────────────────
@app.get("/store", response_class=HTMLResponse)
def storefront(request: Request, db: Session = Depends(get_db), q: str = "", new: bool = False):
    user = None
    try:
        user = auth.get_current_user(request, db)
    except Exception:
        pass
    products = crud.query_products(db, new_arrivals=new, query=q)
    return render("store.html", request, user=user, products=products, query=q, new=new)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, current_user: models.User = Depends(get_current_admin_user), db: Session = Depends(get_db)):
    total_debt    = db.query(func.sum(models.Customer.debt)).scalar() or 0.0
    total_credit  = db.query(func.sum(models.Customer.credit)).scalar() or 0.0
    expiring_count = db.query(models.Medicine).filter(
        models.Medicine.expiry_date != "",
        models.Medicine.expiry_date <= func.strftime("%Y-%m-%d", func.date("now", "+45 days"))
    ).count()
    total_users   = db.query(models.User).count()
    new_arrivals  = db.query(models.Medicine).filter(models.Medicine.is_new_arrival == True).count()
    return render("dashboard.html", request,
                  user=current_user,
                  total_debt=total_debt, total_credit=total_credit,
                  expiring_count=expiring_count, total_users=total_users,
                  new_arrivals=new_arrivals)


@app.get("/profile", response_class=HTMLResponse)
def profile_page(request: Request, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    customer = None
    if current_user.linked_customer_id:
        customer = db.query(models.Customer).filter(
            models.Customer.customer_id == current_user.linked_customer_id).first()
    return render("profile.html", request, user=current_user, customer=customer)


# ── APIs ──────────────────────────────────────
@app.get("/api/products")
def api_products(db: Session = Depends(get_db), q: str = "", new: bool = False):
    return [
        {
            "item_code": p.item_code, "name": p.name, "category": p.category,
            "quantity": p.quantity, "price": p.price, "barcode": p.barcode,
            "is_new_arrival": p.is_new_arrival, "expiry_date": p.expiry_date,
            "image_url": getattr(p, "image_url", None),
        }
        for p in crud.query_products(db, new_arrivals=new, query=q)
    ]


@app.get("/api/barcode-search")
def barcode_search(code: str, db: Session = Depends(get_db)):
    item = crud.get_product_by_barcode(db, code.strip())
    if not item:
        raise HTTPException(404, "المنتج غير موجود")
    return {"item_code": item.item_code, "name": item.name, "category": item.category,
            "quantity": item.quantity, "price": item.price, "expiry_date": item.expiry_date}


@app.get("/api/customers")
def api_customers(q: str = "", current_user: models.User = Depends(get_current_admin_user), db: Session = Depends(get_db)):
    qry = db.query(models.Customer)
    if q:
        t = f"%{q}%"
        qry = qry.filter(models.Customer.customer_name.ilike(t) | models.Customer.customer_id.ilike(t))
    return [{"customer_id": c.customer_id, "customer_name": c.customer_name, "main_account": c.main_account,
             "debt": c.debt, "credit": c.credit, "phone": c.phone, "address": c.address}
            for c in qry.limit(100).all()]


@app.post("/api/upload-excel")
async def upload_excel(file: UploadFile = File(...), current_user: models.User = Depends(get_current_admin_user), db: Session = Depends(get_db)):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(400, "يجب أن يكون الملف .xlsx")
    path = os.path.join(os.getcwd(), "uploads", os.path.basename(file.filename))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(await file.read())
    ok, msg, notifs = crud.import_excel(db, path)
    return {"success": ok, "message": msg, "notifications_sent": len(notifs)}


@app.post("/api/cart/checkout")
def checkout(order: dict = Body(...), current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    items = order.get("cart_items", [])
    if not items:
        raise HTTPException(400, "السلة فارغة")
    method = order.get("payment_method", "credit")
    pharmacy = order.get("pharmacy", "")
    subtotal, discount, total = crud.calculate_cart_totals(items, method)
    invoice = crud.create_invoice(db, pharmacy, order.get("customer_id"), method, items, (subtotal, discount, total))
    utils.create_invoice_pdf(invoice.invoice_no, pharmacy, current_user.username, method, items, subtotal, discount, total)
    return {"invoice_id": invoice.id, "pdf_url": f"/invoices/{invoice.id}"}


@app.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = db.query(models.Invoice).filter(models.Invoice.id == invoice_id).first()
    if not inv:
        raise HTTPException(404, "الفاتورة غير موجودة")
    path = os.path.join(os.getcwd(), "invoices", f"invoice_{inv.invoice_no}.pdf")
    if not os.path.exists(path):
        raise HTTPException(404, "ملف الفاتورة غير موجود")
    return FileResponse(path, media_type="application/pdf")


@app.post("/api/notify-all")
async def notify_all(body: dict = Body(...), current_user: models.User = Depends(get_current_admin_user)):
    msg = body.get("message", "").strip()
    if not msg:
        raise HTTPException(400, "الرسالة فارغة")
    if not BOT_TOKEN:
        return {"message": "⚠️ BOT_TOKEN غير مكوّن"}
    import sqlite3
    rows = []
    try:
        conn = sqlite3.connect(os.path.join(os.getcwd(), "pharmacy.db"))
        rows = conn.execute("SELECT user_id FROM subscribers").fetchall()
        conn.close()
    except Exception:
        pass
    ok = fail = 0
    async with httpx.AsyncClient() as client:
        for (uid,) in rows:
            try:
                await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                  json={"chat_id": uid, "text": f"📢 إشعار:\n\n{msg}"}, timeout=5)
                ok += 1
            except Exception:
                fail += 1
    return {"message": f"✅ نجاح: {ok}  فشل: {fail}"}


@app.get("/api/bot-status")
async def bot_status():
    if not BOT_TOKEN:
        return {"ok": False, "reason": "BOT_TOKEN not set"}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=5)
            d = r.json()
            return {"ok": d.get("ok", False), "bot": d.get("result", {})}
    except Exception as e:
        return {"ok": False, "reason": str(e)}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}
    msg = update.get("message", {})
    if not msg:
        return {"ok": True}
    chat_id = msg.get("chat", {}).get("id")
    doc = msg.get("document")
    if doc and doc.get("file_name", "").endswith(".xlsx") and BOT_TOKEN:
        import sqlite3
        admins = []
        try:
            conn = sqlite3.connect(os.path.join(os.getcwd(), "pharmacy.db"))
            admins = [r[0] for r in conn.execute("SELECT user_id FROM subscribers WHERE role='admin'").fetchall()]
            conn.close()
        except Exception:
            pass
        if chat_id in admins:
            try:
                async with httpx.AsyncClient() as client:
                    fp = (await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={doc['file_id']}", timeout=10)).json()["result"]["file_path"]
                    data = (await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{fp}", timeout=30)).content
                    lp = os.path.join(os.getcwd(), "uploads", doc["file_name"])
                    os.makedirs(os.path.dirname(lp), exist_ok=True)
                    with open(lp, "wb") as f:
                        f.write(data)
                    ok, result_msg, _ = crud.import_excel(db, lp)
                    await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                                      json={"chat_id": chat_id, "text": f"{'✅' if ok else '❌'} {result_msg}\n🔄 تم تحديث الموقع!"})
            except Exception:
                pass
    return {"ok": True}
