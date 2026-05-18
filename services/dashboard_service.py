from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, cast, Date
from datetime import datetime, timedelta
from app.models.models import Customer, Medicine, Invoice, User, ActivityLog

class DashboardService:
    
    @staticmethod
    async def get_general_stats(db: AsyncSession) -> dict:
        # 1. إجمالي الديون (لنا وعلينا)
        total_debt_res = await db.execute(select(func.sum(Customer.debt)))
        total_debt = total_debt_res.scalar() or 0.0
        
        total_credit_res = await db.execute(select(func.sum(Customer.credit)))
        total_credit = total_credit_res.scalar() or 0.0
        
        # 2. الأدوية قريبة الانتهاء (خلال 45 يوم)
        threshold_date = (datetime.now() + timedelta(days=45)).strftime("%Y-%m-%d")
        expiring_res = await db.execute(
            select(func.count(Medicine.id)).where(
                Medicine.expiry_date != "", 
                Medicine.expiry_date <= threshold_date,
                Medicine.quantity > 0
            )
        )
        expiring_count = expiring_res.scalar() or 0

        # 3. الأصناف الجديدة
        new_arrivals_res = await db.execute(
            select(func.count(Medicine.id)).where(Medicine.is_new_arrival == True)
        )
        new_arrivals = new_arrivals_res.scalar() or 0
        
        # 4. نواقص المخزون (أقل من الحد الأدنى)
        low_stock_res = await db.execute(
            select(func.count(Medicine.id)).where(
                Medicine.quantity <= Medicine.min_stock_level
            )
        )
        low_stock = low_stock_res.scalar() or 0

        return {
            "total_debt": total_debt,
            "total_credit": total_credit,
            "expiring_count": expiring_count,
            "new_arrivals": new_arrivals,
            "low_stock": low_stock
        }

    @staticmethod
    async def get_expected_profits(db: AsyncSession) -> dict:
        """حساب إجمالي الأرباح المتوقعة من المخزون الحالي (سعر البيع - التكلفة)"""
        # نستخدم SQL Expression لحساب الفرق وضربة في الكمية
        profit_expr = (Medicine.price - Medicine.cost_price) * Medicine.quantity
        result = await db.execute(select(func.sum(profit_expr)).where(Medicine.quantity > 0))
        expected_profit = result.scalar() or 0.0
        
        # التكلفة الإجمالية للمخزون
        cost_expr = Medicine.cost_price * Medicine.quantity
        result_cost = await db.execute(select(func.sum(cost_expr)).where(Medicine.quantity > 0))
        total_cost = result_cost.scalar() or 0.0

        return {
            "total_cost": total_cost,
            "expected_profit": expected_profit
        }

    @staticmethod
    async def get_daily_sales(db: AsyncSession, days: int = 7) -> list:
        """جلب مبيعات الأيام الأخيرة"""
        start_date = datetime.now() - timedelta(days=days)
        
        # Group by Date
        stmt = select(
            cast(Invoice.created_at, Date).label("date"),
            func.sum(Invoice.final_amount).label("total_sales"),
            func.count(Invoice.id).label("invoices_count")
        ).where(
            Invoice.created_at >= start_date
        ).group_by(
            cast(Invoice.created_at, Date)
        ).order_by(
            cast(Invoice.created_at, Date).desc()
        )
        
        result = await db.execute(stmt)
        records = result.all()
        
        return [
            {
                "date": str(record.date), 
                "total_sales": record.total_sales, 
                "invoices_count": record.invoices_count
            } 
            for record in records
        ]

    @staticmethod
    async def get_activity_logs(db: AsyncSession, limit: int = 50) -> list:
        stmt = select(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_low_stock_medicines(db: AsyncSession) -> list:
        stmt = select(Medicine).where(Medicine.quantity <= Medicine.min_stock_level).order_by(Medicine.quantity.asc())
        result = await db.execute(stmt)
        return result.scalars().all()
