from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from typing import List

from app.database.session import get_db
from app.models.models import Customer
from app.services.inventory_service import InventoryService

router = APIRouter(tags=["Upload & Customers"])

@router.post("/upload-excel")
async def upload_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """رفع ملف Excel (أدوية أو زبائن) وتحديث قاعدة البيانات"""
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="يجب أن يكون الملف بصيغة .xlsx")
    
    contents = await file.read()
    success, message, notifications = await InventoryService.import_excel(db, contents)
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"success": True, "message": message}

@router.get("/customers")
async def search_customers(
    q: str = "",
    db: AsyncSession = Depends(get_db)
):
    """بحث الزبائن"""
    stmt = select(Customer)
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                Customer.customer_name.ilike(term),
                Customer.customer_id.ilike(term),
                Customer.phone.ilike(term)
            )
        )
    stmt = stmt.order_by(Customer.customer_name).limit(100)
    result = await db.execute(stmt)
    customers = result.scalars().all()
    return [
        {
            "customer_id": c.customer_id,
            "customer_name": c.customer_name,
            "main_account": c.main_account,
            "debt": c.debt,
            "credit": c.credit,
            "phone": c.phone
        } for c in customers
    ]
