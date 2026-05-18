"""
وظيفة هذا الملف: إعداد الاتصال بقاعدة البيانات PostgreSQL بطريقة Async.
يستخدم asyncpg و SQLAlchemy 2.0 AsyncSession.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

import ssl

# إعداد SSL مخصص للعمل مع Supabase Pooler بـ asyncpg
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

connect_args = {}
if "supabase.com" in settings.DATABASE_URL:
    connect_args = {"ssl": ssl_context}

# إنشاء المحرك بصيغة Async
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_pre_ping=True,
    connect_args=connect_args
)

# مصنع الجلسات
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)

Base = declarative_base()

async def get_db():
    """Dependency لجلب جلسة قاعدة البيانات في كل Request"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
