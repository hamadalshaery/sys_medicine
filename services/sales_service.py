import os
from typing import Tuple, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.models import Invoice, Medicine, Customer
import aiofiles
from fpdf import FPDF
import json

INVOICE_DIR = os.path.join(os.getcwd(), "invoices")
os.makedirs(INVOICE_DIR, exist_ok=True)

def format_currency(value: float) -> str:
    return f"{round(value,2)} د"

class SalesService:
    
    @staticmethod
    def calculate_cart_totals(items: list, payment_method: str) -> Tuple[float, float, float]:
        subtotal = 0.0
        total = 0.0
        for item in items:
            quantity = int(item.quantity)
            unit_price = float(item.unit_price)
            original_price = float(item.original_price if item.original_price is not None else unit_price)
            subtotal += quantity * original_price
            total += quantity * unit_price
        discount = round(subtotal - total, 2)
        return subtotal, discount, total

    @staticmethod
    async def get_next_invoice_number(db: AsyncSession) -> int:
        result = await db.execute(select(func.max(Invoice.invoice_no)))
        max_no = result.scalar()
        if max_no is None:
            return 1
        return max_no + 1

    @staticmethod
    async def checkout(db: AsyncSession, pharmacy: str, customer_id: str, payment_method: str, items: list, totals: Tuple[float, float, float]) -> Invoice:
        subtotal, discount, total = totals
        invoice_no = await SalesService.get_next_invoice_number(db)
        
        # تحويل عناصر السلة إلى JSON string للاحتفاظ بها
        items_json = json.dumps([item.model_dump() for item in items], ensure_ascii=False)
        
        invoice = Invoice(
            invoice_no=invoice_no,
            customer_id=customer_id,
            pharmacy_name=pharmacy,
            payment_method=payment_method,
            total_amount=subtotal,
            discount_amount=discount,
            final_amount=total,
            details=items_json
        )
        db.add(invoice)
        
        # يمكن أيضاً تقليل المخزون (Inventory Reduction)
        for item in items:
            result = await db.execute(select(Medicine).where(Medicine.item_code == item.item_code))
            medicine = result.scalars().first()
            if medicine:
                medicine.quantity -= item.quantity
                
        # تحديث ديون الزبون إذا كان الدفع آجل
        if payment_method == "credit" and customer_id:
            result = await db.execute(select(Customer).where(Customer.customer_id == customer_id))
            customer = result.scalars().first()
            if customer:
                customer.debt += total

        await db.commit()
        await db.refresh(invoice)
        return invoice

    @staticmethod
    def create_invoice_pdf(invoice_no: int, pharmacy_name: str, customer_name: str, payment_method: str, items: list, subtotal: float, discount: float, total: float) -> str:
        pdf = FPDF()
        pdf.add_page()
        # To handle Arabic nicely you need Amiri or standard fpdf workaround
        # For simplicity, maintaining the old structure which used Arial (which doesn't support Arabic natively without specific handling)
        # But as requested by user, keeping the exact functionality.
        pdf.set_font("Arial", size=12)

        pdf.cell(0, 10, f"Invoice No: {invoice_no}", ln=True, align="R")
        pdf.cell(0, 10, f"Pharmacy: {pharmacy_name}", ln=True, align="R")
        pdf.cell(0, 10, f"Customer: {customer_name}", ln=True, align="R")
        pdf.cell(0, 10, f"Payment Method: {payment_method}", ln=True, align="R")
        pdf.ln(5)

        pdf.set_fill_color(230, 230, 250)
        pdf.cell(30, 8, "Code", 1, 0, "C", True)
        pdf.cell(60, 8, "Item", 1, 0, "C", True)
        pdf.cell(30, 8, "Qty", 1, 0, "C", True)
        pdf.cell(30, 8, "Price", 1, 0, "C", True)
        pdf.cell(40, 8, "Total", 1, 1, "C", True)

        for item in items:
            line_total = item.quantity * item.unit_price
            pdf.cell(30, 8, str(item.item_code), 1, 0, "C")
            pdf.cell(60, 8, str(item.name)[:20], 1, 0, "C")
            pdf.cell(30, 8, str(item.quantity), 1, 0, "C")
            pdf.cell(30, 8, format_currency(item.unit_price), 1, 0, "C")
            pdf.cell(40, 8, format_currency(line_total), 1, 1, "C")

        pdf.ln(5)
        pdf.cell(0, 10, f"Subtotal: {format_currency(subtotal)}", ln=True, align="R")
        pdf.cell(0, 10, f"Discount: {format_currency(discount)}", ln=True, align="R")
        pdf.cell(0, 10, f"Total: {format_currency(total)}", ln=True, align="R")

        file_name = f"invoice_{invoice_no}.pdf"
        path = os.path.join(INVOICE_DIR, file_name)
        pdf.output(path)
        return path
