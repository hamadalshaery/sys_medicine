from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database.session import get_db
from app.models.models import Invoice, Customer
from app.auth.dependencies import get_current_user
from app.services.sales_service import SalesService
from app.schemas.sales_schemas import CheckoutRequest, CheckoutResponse
import os
import asyncio

router = APIRouter(prefix="/sales", tags=["Sales"])

@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(
    request: CheckoutRequest = Body(...), 
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    if not request.cart_items:
        raise HTTPException(status_code=400, detail="السلة فارغة")

    totals = SalesService.calculate_cart_totals(request.cart_items, request.payment_method)
    
    invoice = await SalesService.checkout(
        db, 
        pharmacy=request.pharmacy, 
        customer_id=request.customer_id, 
        payment_method=request.payment_method, 
        items=request.cart_items, 
        totals=totals
    )
    
    # الحصول على اسم الزبون لطباعة الفاتورة
    customer_name = current_user.username
    if request.customer_id:
        result = await db.execute(select(Customer).where(Customer.customer_id == request.customer_id))
        cust = result.scalars().first()
        if cust:
            customer_name = cust.customer_name

    # تشغيل طباعة الـ PDF في Thread منفصل لعدم حجب الـ Event Loop
    subtotal, discount, total = totals
    await asyncio.to_thread(
        SalesService.create_invoice_pdf,
        invoice_no=invoice.invoice_no,
        pharmacy_name=request.pharmacy,
        customer_name=customer_name,
        payment_method=request.payment_method,
        items=request.cart_items,
        subtotal=subtotal,
        discount=discount,
        total=total
    )

    return {"invoice_id": invoice.id, "pdf_url": f"/api/sales/invoices/{invoice.id}"}

@router.get("/invoices/{invoice_id}")
async def get_invoice_pdf(invoice_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Invoice).where(Invoice.id == invoice_id))
    inv = result.scalars().first()
    if not inv:
        raise HTTPException(status_code=404, detail="الفاتورة غير موجودة")
    
    path = os.path.join(os.getcwd(), "invoices", f"invoice_{inv.invoice_no}.pdf")
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="ملف الفاتورة غير موجود")
        
    return FileResponse(path, media_type="application/pdf")
