import asyncio
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.database.session import AsyncSessionLocal
from sqlalchemy.future import select
from app.models.models import User
from app.auth.security import verify_password

async def test():
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == "admin"))
        user = result.scalars().first()
        if not user:
            print("ERROR: No admin user found!")
            return
        print(f"Found user: {user.username}, role: {user.role}")
        ok = verify_password("Admin@123", user.hashed_password)
        print(f"Password verify: {ok}")

asyncio.run(test())
