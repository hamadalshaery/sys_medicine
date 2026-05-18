import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database.session import AsyncSessionLocal
from app.models.models import User
from app.auth.security import get_password_hash
from app.core.config import settings
from sqlalchemy.future import select

async def create_admin():
    async with AsyncSessionLocal() as db:
        # Check if admin already exists
        result = await db.execute(select(User).where(User.username == settings.ADMIN_USERNAME))
        existing = result.scalars().first()
        if existing:
            print("Admin user already exists, skipping.")
            return
        
        new_user = User(
            username=settings.ADMIN_USERNAME,
            hashed_password=get_password_hash(settings.ADMIN_PASSWORD),
            role="admin"
        )
        db.add(new_user)
        await db.commit()
        print("Admin user created successfully!")

if __name__ == "__main__":
    asyncio.run(create_admin())
