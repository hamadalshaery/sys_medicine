from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import io
import numpy as np
import cv2
import logging
from app.database.session import AsyncSessionLocal
from sqlalchemy.future import select
from sqlalchemy import or_
from app.models.models import Medicine
from app.services.inventory_service import InventoryService
from app.core.config import settings

logger = logging.getLogger(__name__)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    is_admin = uid in settings.admin_ids
    
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
    except ImportError:
        logger.error("zxingcpp is not installed")
    except Exception as e:
        logger.error(f"Error reading barcode: {e}")

    if barcodes:
        barcode_val = barcodes[0].strip()
        barcode_clean = barcode_val.lstrip('0') if barcode_val.startswith('0') else barcode_val
        
        async with AsyncSessionLocal() as db:
            stmt = select(Medicine).where(or_(
                Medicine.barcode == barcode_val, 
                Medicine.item_code == barcode_val,
                Medicine.barcode == barcode_clean, 
                Medicine.item_code == barcode_clean
            ))
            res = await db.execute(stmt)
            medicine = res.scalars().first()
            
            if medicine:
                safe_price = medicine.price or 0.0
                discount_mode = context.user_data.get("discount_mode", "credit")
                rate = 0.90 if discount_mode == "cash" else 0.95 if discount_mode == "transfer" else 1.0
                price_disp = round(safe_price * rate, 2)
                cat_str = f" | {medicine.category}" if medicine.category else ""
                
                label = f"{medicine.name}{cat_str} | {price_disp}د | رصيد:{medicine.quantity} | كود:{medicine.item_code}" if is_admin else f"{medicine.name}{cat_str} | {price_disp}د | كود:{medicine.item_code}"
                kb = [[InlineKeyboardButton(label, callback_data=f"select_{medicine.item_code}")]]
                
                return await update.message.reply_text(f"✅ تم قراءة الباركود: {barcode_val}\n🔎 النتيجة:", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await update.message.reply_text(f"❌ تم قراءة الباركود: {barcode_val} ولكن الصنف غير موجود في القاعدة.")
                if not is_admin: return

    if not is_admin:
        if not barcodes:
            return await update.message.reply_text("❌ لم أتمكن من قراءة الباركود من الصورة. تأكد من وضوح الصورة وتوجيه الكاميرا مباشرة نحو الباركود.")
        return

    # Uploading Image to a medicine if admin and waiting for image
    state = context.user_data.get("waiting_for_image_for")
    if state:
        code = state
        async with AsyncSessionLocal() as db:
            res = await db.execute(select(Medicine).where(Medicine.item_code == code))
            med = res.scalars().first()
            if med:
                med.image_file_id = photo_file_id
                await db.commit()
                context.user_data.pop("waiting_for_image_for", None)
                await update.message.reply_text(f"✅ تمت إضافة الصورة بنجاح للصنف {code}.")
    elif not barcodes:
        await update.message.reply_text("❌ لم أتمكن من قراءة الباركود من الصورة ولم تكن بانتظار إضافة صورة لصنف.")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    if uid not in settings.admin_ids:
        return await update.message.reply_text("🚫 متاح للمدراء فقط.")
        
    doc = update.message.document
    if not doc or not doc.file_name.endswith('.xlsx'):
        return await update.message.reply_text("📂 الرجاء إرسال ملف Excel (.xlsx).")
    
    await update.message.reply_text("⏳ جاري معالجة الملف واستيراد البيانات...")
    
    f = await context.bot.get_file(doc.file_id)
    byte_arr = io.BytesIO()
    await f.download_to_memory(byte_arr)
    file_bytes = byte_arr.getvalue()
    
    async with AsyncSessionLocal() as db:
        ok, msg, notifications = await InventoryService.import_excel(db, file_bytes)
        
    await update.message.reply_text(msg)
    
    # إرسال الإشعارات للزبائن في حالة تغير الدين
    # This requires looking up Subscribers that have linked_account == notification.customer_id
    # We will implement this in NotificationService later.
