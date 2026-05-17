import os
from fpdf import FPDF
from datetime import datetime

INVOICE_DIR = os.path.join(os.getcwd(), "invoices")
os.makedirs(INVOICE_DIR, exist_ok=True)


def format_currency(value: float) -> str:
    return f"{round(value,2)} د"


def create_invoice_pdf(invoice_no: int, pharmacy_name: str, customer_name: str, payment_method: str, items: list, subtotal: float, discount: float, total: float) -> str:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    pdf.cell(0, 10, f"فاتورة رقم {invoice_no}", ln=True, align="R")
    pdf.cell(0, 10, f"صيدلية: {pharmacy_name}", ln=True, align="R")
    pdf.cell(0, 10, f"الزبون: {customer_name}", ln=True, align="R")
    pdf.cell(0, 10, f"طريقة الدفع: {payment_method}", ln=True, align="R")
    pdf.ln(5)

    pdf.set_fill_color(230, 230, 250)
    pdf.cell(30, 8, "الكود", 1, 0, "C", True)
    pdf.cell(60, 8, "الصنف", 1, 0, "C", True)
    pdf.cell(30, 8, "الكمية", 1, 0, "C", True)
    pdf.cell(30, 8, "السعر", 1, 0, "C", True)
    pdf.cell(40, 8, "الإجمالي", 1, 1, "C", True)

    for item in items:
        line_total = item["quantity"] * item["unit_price"]
        pdf.cell(30, 8, str(item["item_code"]), 1, 0, "C")
        pdf.cell(60, 8, str(item["name"])[:20], 1, 0, "C")
        pdf.cell(30, 8, str(item["quantity"]), 1, 0, "C")
        pdf.cell(30, 8, format_currency(item["unit_price"]), 1, 0, "C")
        pdf.cell(40, 8, format_currency(line_total), 1, 1, "C")

    pdf.ln(5)
    pdf.cell(0, 10, f"الإجمالي قبل الخصم: {format_currency(subtotal)}", ln=True, align="R")
    pdf.cell(0, 10, f"قيمة الخصم: {format_currency(discount)}", ln=True, align="R")
    pdf.cell(0, 10, f"الإجمالي النهائي: {format_currency(total)}", ln=True, align="R")

    file_name = f"invoice_{invoice_no}.pdf"
    path = os.path.join(INVOICE_DIR, file_name)
    pdf.output(path)
    return path
