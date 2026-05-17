from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from app.database.session import AsyncSessionLocal
from sqlalchemy.future import select
from sqlalchemy import or_
from app.models.models import Customer, Subscriber, Medicine, Supplier
from app.bot.keyboards import get_main_reply_keyboard
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = update.message.from_user.id
    is_admin = uid in settings.admin_ids

    async with AsyncSessionLocal() as db:
        sub_result = await db.execute(select(Subscriber).where(Subscriber.user_id == uid))
        sub = sub_result.scalars().first()
        is_linked = bool(sub and sub.linked_account)

        current_mode = context.user_data.get("search_mode", "medicines")

        # --- ربط الحساب ---
        if context.user_data.get("waiting_for_link_account"):
            if text.lower() == "إلغاء":
                context.user_data["waiting_for_link_account"] = False
                return await update.message.reply_text("✅ تم إلغاء عملية الربط.", reply_markup=get_main_reply_keyboard(is_admin, current_mode, is_linked))
            
            cust_result = await db.execute(select(Customer).where(Customer.customer_id == text))
            cust = cust_result.scalars().first()
            if cust:
                if sub:
                    sub.linked_account = cust.customer_id
                    await db.commit()
                context.user_data["waiting_for_link_account"] = False
                return await update.message.reply_text("✅ تم ربط حسابك بالمنظومة بنجاح!", reply_markup=get_main_reply_keyboard(is_admin, current_mode, True))
            else:
                return await update.message.reply_text("❌ رقم الحساب غير موجود في المنظومة. تأكد من الرقم أو اكتب 'إلغاء'.")

        # --- استعلام الزبون المباشر باستخدام الرقم (Admin) ---
        if not is_admin and text.isdigit():
            cust_result = await db.execute(select(Customer).where(Customer.customer_id == text))
            cust = cust_result.scalars().first()
            if cust:
                net = cust.debt - cust.credit
                status = "مدين (عليه)" if net > 0 else "دائن (له)" if net < 0 else "متزن"
                return await update.message.reply_text(
                    f"👤 **بيانات الزبون**\n🔢 رقم الزبون: `{cust.customer_id}`\n🏷 الاسم: {cust.customer_name}\n"
                    f"🏥 الحساب: {cust.main_account}\n🔴 مدين: {cust.debt} د\n🟢 دائن: {cust.credit} د\n"
                    f"💰 **الرصيد: {abs(net)} د ({status})**", parse_mode="Markdown"
                )

        # --- أزرار القائمة الثابتة ---
        if text == "🔗 ربط حسابي" and not is_admin:
            if is_linked: return await update.message.reply_text("حسابك مربوط مسبقاً.")
            context.user_data["waiting_for_link_account"] = True
            return await update.message.reply_text("🔢 أرسل رقم حسابك في المنظومة لربطه بالتليجرام (أو اكتب 'إلغاء'):", reply_markup=ReplyKeyboardMarkup([["إلغاء"]], resize_keyboard=True))

        if text == "📄 استعلام عن ديني" and not is_admin:
            if not is_linked: return await update.message.reply_text("❌ حسابك غير مربوط.")
            cust_result = await db.execute(select(Customer).where(Customer.customer_id == sub.linked_account))
            cust = cust_result.scalars().first()
            if cust:
                net = cust.debt - cust.credit
                status = "مدين (عليك)" if net > 0 else "دائن (لك)" if net < 0 else "متزن"
                return await update.message.reply_text(
                    f"👤 **كشف الحساب الخاص بك**\n🏷 الاسم: {cust.customer_name}\n"
                    f"🔴 مدين (عليك): {cust.debt} د\n🟢 دائن (لك): {cust.credit} د\n"
                    f"💰 **الرصيد النهائي: {abs(net)} د ({status})**", parse_mode="Markdown"
                )
            else: return await update.message.reply_text("❌ لم أتمكن من العثور على بياناتك في المنظومة.")

        # --- البحث عن الأدوية أو الزبائن حسب النص العشوائي ---
        if text not in ("🛒 السلة", "🏥 تغيير الصيدلية", "💵 كاش", "🏦 تحويل", "🕐 أجل", "📦 تصفح الأصناف", "🆕 الأصناف الجديدة", "🔍 بحث بالباركود"):
            # بحث زبائن (Admin)
            if current_mode == "customers" and is_admin:
                query = f"%{text}%"
                result = await db.execute(select(Customer).where(or_(Customer.customer_name.ilike(query), Customer.customer_id.ilike(query))).limit(50))
                customers = result.scalars().all()
                if not customers: return await update.message.reply_text(f"❌ لم يتم العثور على زبون '{text}'")
                kb = []
                for c in customers:
                    net = c.debt - c.credit
                    status = f"مدين {net}" if net > 0 else f"دائن {abs(net)}" if net < 0 else "متزن"
                    kb.append([InlineKeyboardButton(f"{c.customer_name} ({c.customer_id}) | {status}", callback_data=f"select_cust_{c.customer_id}")])
                return await update.message.reply_text("👤 نتائج بحث الزبائن:", reply_markup=InlineKeyboardMarkup(kb))

            # بحث أدوية
            query = f"%{text}%"
            result = await db.execute(select(Medicine).where(or_(Medicine.name.ilike(query), Medicine.item_code.ilike(query), Medicine.barcode.ilike(query))).limit(50))
            meds = result.scalars().all()
            
            if not meds: return await update.message.reply_text("❌ لا توجد نتائج.")
            
            discount_mode = context.user_data.get("discount_mode", "credit")
            kb = []
            for item in meds[:50]:
                safe_price = item.price or 0.0
                rate = 0.90 if discount_mode == "cash" else 0.95 if discount_mode == "transfer" else 1.0
                price_disp = round(safe_price * rate, 2)
                cat_str = f" | {item.category}" if item.category else ""
                label = f"{item.name}{cat_str} | {price_disp}د | رصيد:{item.quantity} | كود:{item.item_code}" if is_admin else f"{item.name}{cat_str} | {price_disp}د | كود:{item.item_code}"
                kb.append([InlineKeyboardButton(label, callback_data=f"select_{item.item_code}")])
            await update.message.reply_text("🔎 اختر من النتائج:", reply_markup=InlineKeyboardMarkup(kb))
