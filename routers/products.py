from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_
from typing import List
from app.database.session import get_db
from app.models.models import Medicine
from app.schemas.schemas import MedicineResponse

router = APIRouter(prefix="/products", tags=["Products"])

@router.get("/", response_model=List[MedicineResponse])
async def search_products(
    q: str = "", 
    new: bool = False, 
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Medicine)
    
    if new:
        stmt = stmt.where(Medicine.is_new_arrival == True)
        
    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                Medicine.name.ilike(term),
                Medicine.item_code.ilike(term),
                Medicine.barcode.ilike(term)
            )
        )
        
    stmt = stmt.order_by(Medicine.name).limit(100)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.get("/barcode", response_model=MedicineResponse)
async def barcode_search(
    code: str = Query(..., description="رقم الباركود للبحث"), 
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Medicine).where(
        or_(
            Medicine.barcode == code,
            Medicine.item_code == code
        )
    )
    result = await db.execute(stmt)
    item = result.scalars().first()
    
    if not item:
        raise HTTPException(status_code=404, detail="المنتج غير موجود")
        
    return item
