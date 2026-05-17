import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler, InlineQueryHandler
from app.bot.handlers.start_handler import start_cmd
from app.bot.handlers.text_handler import handle_text
from app.bot.handlers.media_handler import handle_photo, handle_document
from app.bot.handlers.callback_handler import handle_callback

logger = logging.getLogger(__name__)

def setup_bot(app: Application):
    """إعداد مسارات البوت (Handlers)"""
    
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(MessageHandler(filters.Document.FileExtension("xlsx"), handle_document))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # ربط ضغطات الأزرار (السلة والتصفح والتعديل)
    app.add_handler(CallbackQueryHandler(handle_callback))
    
    return app
