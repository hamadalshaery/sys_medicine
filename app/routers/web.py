from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
import os

from app.database.session import get_db
from app.models.models import User
from app.auth.security import verify_password
from app.auth.jwt_handler import create_access_token, decode_access_token

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))


async def _get_current_user_from_cookie(request: Request, db: AsyncSession):
    """قراءة التوكن من الكوكيز واستخراج بيانات المستخدم"""
    token = request.cookies.get("access_token")
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    if not username:
        return None
    result = await db.execute(select(User).where(User.username == username))
    return result.scalars().first()


@router.get("/", response_class=HTMLResponse)
async def home(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    return templates.TemplateResponse("store.html", {"request": request, "user": user})

@router.get("/store", response_class=HTMLResponse)
async def store(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    return templates.TemplateResponse("store.html", {"request": request, "user": user})

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalars().first()
    
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {
            "request": request, 
            "error": "اسم المستخدم أو كلمة المرور غير صحيحة."
        })
    
    token = create_access_token(data={"sub": user.username, "role": user.role})
    redirect_url = "/dashboard" if user.role == "admin" else "/store"
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True, max_age=28800)
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("access_token")
    return response

@router.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    user = await _get_current_user_from_cookie(request, db)
    if not user or user.role != "admin":
        return RedirectResponse(url="/login", status_code=302)
    
    from app.services.dashboard_service import DashboardService
    stats = await DashboardService.get_general_stats(db)
    
    # عدد المستخدمين
    user_count_res = await db.execute(select(func.count(User.id)))
    total_users = user_count_res.scalar() or 0
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "total_debt": stats["total_debt"],
        "total_credit": stats["total_credit"],
        "expiring_count": stats["expiring_count"],
        "new_arrivals": stats["new_arrivals"],
        "total_users": total_users
    })

