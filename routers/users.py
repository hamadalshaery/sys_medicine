from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
import pyotp
import qrcode
import io
import base64

from app.database.session import get_db
from app.models.models import User
from app.schemas.user_schemas import UserCreate, UserUpdate, UserResponse, VerifyTOTP
from app.auth.security import get_password_hash
from app.auth.dependencies import get_current_admin_user

router = APIRouter(prefix="/users", tags=["Users Management"])

@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User))
    return result.scalars().all()

@router.post("/", response_model=UserResponse)
async def create_user(
    user_in: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.username == user_in.username))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="اسم المستخدم موجود بالفعل.")
    
    new_user = User(
        username=user_in.username,
        hashed_password=get_password_hash(user_in.password),
        role=user_in.role
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    user_in: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
        
    if user_in.username:
        # Check uniqueness
        check_u = await db.execute(select(User).where(User.username == user_in.username, User.id != user_id))
        if check_u.scalars().first():
            raise HTTPException(status_code=400, detail="اسم المستخدم موجود بالفعل.")
        user.username = user_in.username
        
    if user_in.password:
        user.hashed_password = get_password_hash(user_in.password)
        
    if user_in.role:
        user.role = user_in.role
        
    await db.commit()
    await db.refresh(user)
    return user

@router.post("/{user_id}/setup-2fa")
async def setup_2fa(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """إنشاء مفتاح 2FA سري وإرجاع QR Code Base64"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
        
    secret = pyotp.random_base32()
    user.totp_secret = secret
    user.is_totp_enabled = False # حتى يتم التحقق لأول مرة
    await db.commit()
    
    # 생성 uri
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="AlNafis Pharmacy")
    
    # Generate QR Image
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    
    buffered = io.BytesIO()
    img.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    
    return {
        "secret": secret,
        "qr_code_base64": f"data:image/png;base64,{img_str}",
        "message": "يرجى مسح الرمز بتطبيق Google Authenticator ثم تأكيد الكود لتفعيل الميزة."
    }

@router.post("/{user_id}/verify-2fa")
async def verify_2fa(
    user_id: int,
    data: VerifyTOTP,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """تفعيل التحقق الثنائي بعد التأكد من صحة الكود لأول مرة"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user or not user.totp_secret:
        raise HTTPException(status_code=400, detail="لم يتم إعداد 2FA لهذا المستخدم.")
        
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(data.code):
        raise HTTPException(status_code=400, detail="الكود غير صحيح.")
        
    user.is_totp_enabled = True
    await db.commit()
    return {"message": "تم تفعيل التحقق الثنائي بنجاح!"}

@router.post("/{user_id}/disable-2fa")
async def disable_2fa(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin_user)
):
    """إلغاء التحقق الثنائي (للمدراء فقط)"""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
        
    user.totp_secret = None
    user.is_totp_enabled = False
    await db.commit()
    return {"message": "تم تعطيل التحقق الثنائي لهذا المستخدم."}
