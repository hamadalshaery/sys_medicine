from telegram import Update
from telegram.ext import ContextTypes
from app.database.session import AsyncSessionLocal
from sqlalchemy.future import select
from app.models.models import Subscriber, UserSetting
from app.bot.keyboards import get_main_reply_keyboard, get_payment_modes_keyboard
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    user_name = update.effective_user.first_name or update.effective_user.username or f"User{uid}"
    
    is_admin = uid in settings.admin_ids
    role = 'admin' if is_admin else 'customer'

    async with AsyncSessionLocal() as db:
        # تسجيل المستخدم
        result = await db.execute(select(Subscriber).where(Subscriber.user_id == uid))
        sub = result.scalars().first()
        if not sub:
            sub = Subscriber(user_id=uid, role=role)
            db.add(sub)
        else:
            sub.role = role
            
        # إعدادات المستخدم
        result_settings = await db.execute(select(UserSetting).where(UserSetting.user_id == uid))
        user_set = result_settings.scalars().first()
        if not user_set:
            user_set = UserSetting(user_id=uid, discount_mode='credit')
            db.add(user_set)
        
        await db.commit()
        await db.refresh(sub)
        await db.refresh(user_set)
        
        is_linked = bool(sub.linked_account)
        discount_mode = user_set.discount_mode

    # تخزين الحالة في سياق البوت (Memory)
    context.user_data["discount_mode"] = discount_mode
    context.user_data["search_mode"] = "medicines"
    
    msg = "👋 أهلاً بك في منظومة شركة ابن النفيس !\n\nاختر طريقة الدفع:\n💵 كاش = خصم 10%\n🏦 تحويل = خصم 5%\n🕐 أجل = بدون خصم"
    await update.message.reply_text(msg, reply_markup=get_payment_modes_keyboard())
    
    if not is_admin and not is_linked:
        await update.message.reply_text(
            "💡 يرجى ربط حسابك في المنظومة للتمكن من الاستعلام عن ديونك.\nاضغط على '🔗 ربط حسابي' من القائمة.", 
            reply_markup=get_main_reply_keyboard(is_admin, "medicines", is_linked)
        )
    else:
        await update.message.reply_text(
            "اختر من القائمة في الأسفل:",
            reply_markup=get_main_reply_keyboard(is_admin, "medicines", is_linked)
        )
