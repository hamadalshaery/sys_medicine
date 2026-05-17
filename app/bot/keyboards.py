from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton

def get_main_reply_keyboard(is_admin: bool = False, search_mode: str = "medicines", is_linked: bool = False) -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton("🛒 السلة"), KeyboardButton("🏥 تغيير الصيدلية")],
        [KeyboardButton("💵 كاش"), KeyboardButton("🏦 تحويل"), KeyboardButton("🕐 أجل")],
        [KeyboardButton("📦 تصفح الأصناف"), KeyboardButton("🆕 الأصناف الجديدة")],
        [KeyboardButton("🔍 بحث بالباركود")]
    ]
    
    if not is_admin:
        if not is_linked: 
            kb.append([KeyboardButton("🔗 ربط حسابي")])
        else: 
            kb.append([KeyboardButton("📄 استعلام عن ديني")])

    if is_admin:
        kb.append([KeyboardButton("👥 عرض المستخدمين"), KeyboardButton("📊 تقرير الصلاحية")])
        toggle_text = "👤 بحث زبائن" if search_mode == "medicines" else "🔍 بحث أدوية"
        kb.append([KeyboardButton(toggle_text), KeyboardButton("🚚 بحث موردين")])
        kb.append([KeyboardButton("📢 إشعار عام")])
        kb.append([KeyboardButton("🗑️ حذف البيانات")])
        
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def get_payment_modes_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("💵 كاش (خصم 10%)", callback_data="mode_cash")],
        [InlineKeyboardButton("🏦 تحويل (خصم 5%)", callback_data="mode_transfer")],
        [InlineKeyboardButton("🕐 أجل (بدون خصم)", callback_data="mode_credit")],
    ]
    return InlineKeyboardMarkup(kb)
