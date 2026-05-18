"""
وظيفة هذا الملف: إعداد الاتصال بقاعدة البيانات PostgreSQL بطريقة Async.
يستخدم asyncpg و SQLAlchemy 2.0 AsyncSession.
"""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.core.config import settings

# إنشاء المحرك بصيغة Async
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    pool_pre_ping=True
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
