from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import pyotp

from app.database.session import get_db
from app.models.models import User
from app.auth.security import verify_password
from app.auth.jwt_handler import create_access_token
from app.schemas.user_schemas import LoginRequest

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/login")
async def login(
    req: LoginRequest,
    db: AsyncSession = Depends(get_db)
):
    # 1. التحقق من اسم المستخدم
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalars().first()
    
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="اسم المستخدم أو كلمة المرور غير صحيحة.")
        
    # 2. التحقق من كلمة المرور
    if not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="اسم المستخدم أو كلمة المرور غير صحيحة.")
        
    # 3. التحقق الثنائي (2FA) إذا كان مفعلاً
    if user.is_totp_enabled:
        if not req.totp_code:
            # نرسل رد خاص للواجهة لتطلب من المستخدم إدخال الكود
            return {"requires_2fa": True, "message": "يرجى إدخال كود التحقق الثنائي (Google Authenticator)."}
            
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(req.totp_code):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="كود التحقق الثنائي غير صحيح.")
            
    # 4. إصدار الـ JWT Token
    access_token = create_access_token(data={"sub": user.username, "role": user.role})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role
        }
    }
