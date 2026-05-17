from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import logging
from app.database.session import AsyncSessionLocal
from sqlalchemy.future import select
from app.models.models import Medicine, Customer, Subscriber, UserSetting
from app.bot.keyboards import get_main_reply_keyboard
from app.core.config import settings
from app.services.sales_service import SalesService
from app.schemas.sales_schemas import CartItem
import asyncio

logger = logging.getLogger(__name__)

# Using in-memory dictionary for carts as requested to maintain original logic,
# but normally this should go to Redis.
user_carts = {}

def format_currency(value: float) -> str:
    return f"{round(value,2)} د"

async def _send_cart_message(source, uid: int, context: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
    is_admin = uid in settings.admin_ids
    
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(Subscriber).where(Subscriber.user_id == uid))
        sub = res.scalars().first()
        is_linked = bool(sub and sub.linked_account)
        
    current_mode = context.user_data.get("search_mode", "medicines")
    
    if not cart["items"]:
        msg = "🛒 السلة فارغة."
        markup = get_main_reply_keyboard(is_admin, current_mode, is_linked)
    else:
        lines = []
        total = 0.0
        kb_rows = []
        for item in cart["items"][:14]: 
            # item tuple: (code, name, category, qty, unit_price, orig_price)
            code, name, cat, qty, unit_price, orig = item
            line_total = round(qty * unit_price, 2)
            total += line_total
            lines.append(f"• {name[:30]} ×{qty} = {format_currency(line_total)}")
            kb_rows.append([InlineKeyboardButton("❌", callback_data=f"cart_del_{code}")])

        msg = f"🛒 السلة:\n\n" + "\n".join(lines) + f"\n\n🏥 الصيدلية: {cart.get('pharmacy') or 'غير محدد'}\n💵 الإجمالي: {format_currency(total)}"
        kb_rows.append([InlineKeyboardButton("✅ إنهاء الطلب", callback_data="finish_order")])
        markup = InlineKeyboardMarkup(kb_rows)

    if edit and context.user_data.get("last_cart_message_id"):
        try: await context.bot.edit_message_text(chat_id=source.chat.id, message_id=context.user_data["last_cart_message_id"], text=msg, reply_markup=markup)
        except Exception: pass
    else:
        sent = await context.bot.send_message(chat_id=source.chat.id, text=msg, reply_markup=markup)
        context.user_data["last_cart_message_id"] = sent.message_id


async def _show_qty_selection(source, context, uid, name, code, img_id, edit=False):
    qty = context.user_data.get("current_qty", 0)
    price = context.user_data.get("selecting_price", 0)
    mode = context.user_data.get("discount_mode", "credit")
    safe_price = price or 0.0
    
    rate = 0.90 if mode == "cash" else 0.95 if mode == "transfer" else 1.0
    price_disp = round(safe_price * rate, 2)
    
    is_admin = uid in settings.admin_ids
    
    msg = f"الصنف: {name}\nالكمية: {qty}\nالسعر: {price_disp} د"
    if is_admin: 
        msg += f"\nرصيد المخزن المتوفر: {context.user_data.get('selecting_quantity', 0)}"
        
    kb = [
        [InlineKeyboardButton("+1", callback_data="qty_inc_1"), InlineKeyboardButton("+5", callback_data="qty_inc_5"), InlineKeyboardButton("+50", callback_data="qty_inc_50")],
        [InlineKeyboardButton("-1", callback_data="qty_dec_1"), InlineKeyboardButton("-5", callback_data="qty_dec_5"), InlineKeyboardButton("-50", callback_data="qty_dec_50")],
        [InlineKeyboardButton("إضافة", callback_data="qty_add"), InlineKeyboardButton("إلغاء", callback_data="qty_cancel")]
    ]
    if is_admin and not img_id: 
        kb.append([InlineKeyboardButton("📸 إضافة صورة", callback_data=f"add_img_{code}")])
        
    if edit: 
        await source.edit_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    else: 
        await source.reply_text(msg, reply_markup=InlineKeyboardMarkup(kb))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    data = q.data or ""
    is_admin = uid in settings.admin_ids

    # --- تغيير الدفع (Payment Modes) ---
    if data in ("mode_cash", "mode_credit", "mode_transfer"):
        mode = "cash" if data == "mode_cash" else "transfer" if data == "mode_transfer" else "credit"
        mode_str = "كاش (خصم 10%)" if mode == "cash" else "تحويل (خصم 5%)" if mode == "transfer" else "أجل (بدون خصم)"
        
        context.user_data["discount_mode"] = mode
        async with AsyncSessionLocal() as db:
            user_set = await db.execute(select(UserSetting).where(UserSetting.user_id == uid))
            us = user_set.scalars().first()
            if us:
                us.discount_mode = mode
                await db.commit()

            sub_res = await db.execute(select(Subscriber).where(Subscriber.user_id == uid))
            sub = sub_res.scalars().first()
            is_linked = bool(sub and sub.linked_account)
            
        # Update prices in cart memory
        cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
        if cart["items"]:
            for i, item in enumerate(cart["items"]):
                c_code, c_name, c_cat, c_qty, c_unit, c_orig = item
                new_unit = round(c_orig * 0.90, 2) if mode == "cash" else round(c_orig * 0.95, 2) if mode == "transfer" else c_orig
                cart["items"][i] = (c_code, c_name, c_cat, c_qty, new_unit, c_orig)
        user_carts[uid] = cart

        await q.answer(f"تم اختيار الدفع: {mode_str}", show_alert=True)
        try:
            await q.message.reply_text(f"✅ تم التبديل إلى: {mode_str}.", reply_markup=get_main_reply_keyboard(is_admin, "medicines", is_linked))
            if context.user_data.get("last_cart_message_id") == q.message.message_id:
                await _send_cart_message(q.message, uid, context, edit=True)
        except Exception: pass
        return

    # --- مسح السلة ---
    if data == "clear_confirm_yes":
        user_carts[uid] = {"items": [], "pharmacy": ""}
        try: await q.edit_message_text("🗑️ تم مسح السلة بالكامل.")
        except: pass
        return

    # --- التعامل مع إضافة منتج للسلة ---
    if data.startswith("select_") and not data.startswith("select_cust_") and not data.startswith("select_supp_"):
        code = data.split("_", 1)[1]
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Medicine).where(Medicine.item_code == code))
            med = res.scalars().first()
            
            if not med: 
                return await q.edit_message_text("❌ المنتج غير موجود.")
            
            context.user_data["selecting_code"] = code
            context.user_data["selecting_name"] = med.name
            context.user_data["selecting_price"] = med.price
            context.user_data["selecting_quantity"] = med.quantity
            context.user_data["selecting_category"] = med.category
            context.user_data["current_qty"] = 0
            
            if med.image_file_id:
                try: await context.bot.send_photo(chat_id=uid, photo=med.image_file_id)
                except Exception: pass
                    
            await _show_qty_selection(q.message, context, uid, med.name, code, med.image_file_id, edit=False)
            return

    # --- التحكم في الكمية ---
    if data.startswith("qty_"):
        if "selecting_code" not in context.user_data: return await q.edit_message_text("⚠️ لا يوجد صنف محدد.")
        code = context.user_data["selecting_code"]
        name = context.user_data["selecting_name"]
        cat = context.user_data.get("selecting_category", "")
        curr_qty = context.user_data.get("current_qty", 0)
        
        if data == "qty_add":
            if curr_qty <= 0: return await q.edit_message_text("⚠️ اختر كمية أكبر من الصفر.")
            async with AsyncSessionLocal() as db:
                res = await db.execute(select(Medicine).where(Medicine.item_code == code))
                med = res.scalars().first()
                if not med or curr_qty > med.quantity:
                    return await q.edit_message_text("❌ الكمية غير متوفرة في المخزن.")
                    
                mode = context.user_data.get("discount_mode", "credit")
                safe_price = med.price or 0.0
                rate = 0.90 if mode == "cash" else 0.95 if mode == "transfer" else 1.0
                unit_price = round(safe_price * rate, 2)
                
                # إضافة للسلة
                cart = user_carts.setdefault(uid, {"items": [], "pharmacy": ""})
                found = False
                for i, it in enumerate(cart["items"]):
                    if it[0] == code:
                        cart["items"][i] = (it[0], it[1], it[2], it[3]+curr_qty, it[4], it[5])
                        found = True; break
                if not found:
                    cart["items"].append((code, name, cat, curr_qty, unit_price, safe_price))
                    
                return await q.edit_message_text(f"✅ تمت إضافة {curr_qty} من {name} إلى السلة.")
                
        elif data == "qty_cancel":
            return await q.edit_message_text("❌ تم الإلغاء.")
            
        parts = data.split("_")
        amt = int(parts[2])
        if parts[1] == "inc": curr_qty += amt
        else: curr_qty = max(0, curr_qty - amt)
        context.user_data["current_qty"] = curr_qty
        
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Medicine.image_file_id).where(Medicine.item_code == code))
            img_id = res.scalars().first()
            
        await _show_qty_selection(q.message, context, uid, name, code, img_id, edit=True)
        return

    # --- إنهاء الطلب والدفع ---
    if data == "finish_order":
        cart = user_carts.get(uid, {"items": [], "pharmacy": ""})
        if not cart["items"]: return await q.edit_message_text("❌ السلة فارغة.")
        
        orig = sum(i[3]*i[5] for i in cart["items"])
        final = sum(i[3]*i[4] for i in cart["items"])
        
        context.user_data["order_summary"] = {
            "orig": orig, "final": final, "discount": orig-final, 
            "items": cart["items"], "pharmacy": cart.get("pharmacy", "")
        }
        
        kb = [[InlineKeyboardButton("✅ نعم - أصدر الفاتورة", callback_data="pay_confirm")], [InlineKeyboardButton("🔙 لا", callback_data="back_to_cart")]]
        return await q.edit_message_text(f"💵 الإجمالي قبل الخصم: {format_currency(orig)}\n💰 الخصم: {format_currency(orig-final)}\n✅ النهائي: {format_currency(final)}\nإصدار؟", reply_markup=InlineKeyboardMarkup(kb))

    if data == "pay_confirm":
        s = context.user_data.get("order_summary")
        if not s: return await q.edit_message_text("⚠️ لا يوجد طلب.")
        
        await q.edit_message_text("⏳ جاري إصدار الفاتورة، يرجى الانتظار...")
        
        mode = context.user_data.get("discount_mode", "credit")
        method = "كاش" if mode == "cash" else "تحويل" if mode == "transfer" else "أجل"
        
        # تحويل عناصر السلة إلى Pydantic Models للـ Checkout
        cart_items = [
            CartItem(item_code=i[0], name=i[1], category=i[2], quantity=i[3], unit_price=i[4], original_price=i[5]) 
            for i in s["items"]
        ]
        
        totals = (s["orig"], s["discount"], s["final"])
        
        async with AsyncSessionLocal() as db:
            sub_res = await db.execute(select(Subscriber).where(Subscriber.user_id == uid))
            sub = sub_res.scalars().first()
            customer_id = sub.linked_account if sub else ""
            
            # عملية الدفع (تحديث القاعدة)
            invoice = await SalesService.checkout(
                db, 
                pharmacy=s["pharmacy"], 
                customer_id=customer_id, 
                payment_method=method, 
                items=cart_items, 
                totals=totals
            )
            
            # طباعة الفاتورة في Background Thread
            customer_name = q.from_user.first_name
            if customer_id:
                cust_res = await db.execute(select(Customer).where(Customer.customer_id == customer_id))
                cust = cust_res.scalars().first()
                if cust: customer_name = cust.customer_name
                
            pdf_path = await asyncio.to_thread(
                SalesService.create_invoice_pdf,
                invoice_no=invoice.invoice_no,
                pharmacy_name=s["pharmacy"],
                customer_name=customer_name,
                payment_method=method,
                items=cart_items,
                subtotal=s["orig"],
                discount=s["discount"],
                total=s["final"]
            )
        
        # إرسال الفاتورة للعميل
        await q.message.reply_document(open(pdf_path, "rb"), caption=f"✅ فاتورة رقم {invoice.invoice_no}")
        
        # مسح السلة
        user_carts[uid] = {"items": [], "pharmacy": ""}
        return
        
    if data == "back_to_cart":
        return await _send_cart_message(q.message, uid, context, edit=True)
