"""
نقطة الإدخال الرئيسية (Entry Point) للتطبيق.
تجمع بين FastAPI وبوت تيليجرام (عبر Webhooks).
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from telegram import Update
from telegram.ext import Application
import os

from app.core.config import settings
from app.core.security_middleware import SecurityHeadersMiddleware
from app.routers import api, web
from app.bot.telegram_bot import setup_bot
from app.database.session import engine, Base

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

# إعداد محدد الطلبات (Rate Limiter) لتجنب هجمات الـ DDoS
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# إعداد تطبيق تيليجرام
ptb_app = Application.builder().token(settings.BOT_TOKEN).build()
setup_bot(ptb_app)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # لا داعي لإنشاء الجداول هنا، Alembic سيقوم بذلك
    # await conn.run_sync(Base.metadata.create_all)
        
        
    await ptb_app.bot.set_webhook(url=settings.WEBHOOK_URL)
    await ptb_app.initialize()
    await ptb_app.start()
    logger.info("Bot started via Webhook")
    
    yield
    
    # عند الإغلاق (Shutdown)
    await ptb_app.stop()
    await ptb_app.shutdown()
    logger.info("Bot stopped")

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# ربط الـ Rate Limiter بالتطبيق
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# إضافة الهيدرز الأمنية القوية
app.add_middleware(SecurityHeadersMiddleware)

# ربط الملفات الثابتة (Static Files)
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# دمج الروترات
app.include_router(api.router, prefix="/api", tags=["API"])
app.include_router(web.router, tags=["Web"])

@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    """استقبال تحديثات تيليجرام من خلال Webhook وإرسالها لبوت تيليجرام الداخلي"""
    update_data = await request.json()
    update = Update.de_json(data=update_data, bot=ptb_app.bot)
    await ptb_app.process_update(update)
    return {"ok": True}
