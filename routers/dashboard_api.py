from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.session import get_db
from app.auth.dependencies import get_current_admin_user
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    admin = Depends(get_current_admin_user)
):
    """إحصائيات عامة سريعة للوحة التحكم"""
    return await DashboardService.get_general_stats(db)

@router.get("/profits")
async def get_profits(
    db: AsyncSession = Depends(get_db),
    admin = Depends(get_current_admin_user)
):
    """تقارير الأرباح وتكلفة المخزون"""
    return await DashboardService.get_expected_profits(db)

@router.get("/sales/daily")
async def get_daily_sales(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    admin = Depends(get_current_admin_user)
):
    """مبيعات آخر X أيام مجمعة"""
    return await DashboardService.get_daily_sales(db, days)

@router.get("/logs")
async def get_activity_logs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    admin = Depends(get_current_admin_user)
):
    """سجل أنشطة النظام"""
    logs = await DashboardService.get_activity_logs(db, limit)
    return [
        {
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "description": log.description,
            "created_at": log.created_at
        } for log in logs
    ]

@router.get("/low-stock")
async def get_low_stock(
    db: AsyncSession = Depends(get_db),
    admin = Depends(get_current_admin_user)
):
    """جلب الأدوية التي تجاوزت الحد الأدنى للمخزون"""
    meds = await DashboardService.get_low_stock_medicines(db)
    return [
        {
            "item_code": med.item_code,
            "name": med.name,
            "quantity": med.quantity,
            "min_stock_level": med.min_stock_level
        } for med in meds
    ]
