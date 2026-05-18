"""
وظيفة هذا الملف: التعامل مع إدارة المخزون وقراءة ملفات Excel بطريقة غير متزامنة باستخدام Pandas.
"""
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.models import Medicine, Customer, Supplier
import io
import math

class InventoryService:
    
    @staticmethod
    def safe_float(val, default=0.0):
        try:
            return float(val) if not math.isnan(float(val)) else default
        except:
            return default

    @staticmethod
    async def import_excel(db: AsyncSession, file_bytes: bytes) -> tuple[bool, str, list]:
        """معالجة ملفات الإكسل بشكل غير متزامن"""
        try:
            df = pd.read_excel(io.BytesIO(file_bytes))
        except Exception as e:
            return False, f"فشل قراءة الملف: {e}", []

        if "رقم الزبون" in df.columns or "رقم الحساب" in df.columns:
            return await InventoryService._import_customers(db, df)
        
        if "رقم الصنف" in df.columns or "اسم الصنف" in df.columns:
            return await InventoryService._import_medicines(db, df)
            
        return False, "الملف لا يحتوي على أعمدة معروفة (أدوية أو زبائن).", []

    @staticmethod
    async def _import_customers(db: AsyncSession, df: pd.DataFrame) -> tuple[bool, str, list]:
        column_map = {
            "رقم الزبون": "customer_id", "اسم الزبون": "customer_name",
            "رقم الحساب": "customer_id", "اسم الحساب": "customer_name",
            "مدين": "debt", "مــدين": "debt",
            "دائن": "credit", "دائـــن": "credit",
            "الحساب الرئيسي": "main_account", "الهاتف": "phone", "العنوان": "address"
        }
        df = df.rename(columns=column_map)
        inserted = 0
        notifications = []

        for _, row in df.iterrows():
            cid = str(row.get("customer_id", "")).strip()
            if cid.endswith(".0"): cid = cid[:-2]
            if not cid or cid == "nan": continue

            c_name = str(row.get("customer_name", ""))
            debt = InventoryService.safe_float(row.get("debt"))
            credit = InventoryService.safe_float(row.get("credit"))
            
            # Check if exists
            result = await db.execute(select(Customer).where(Customer.customer_id == cid))
            existing = result.scalars().first()
            
            if existing:
                if existing.debt != debt or existing.credit != credit:
                    notifications.append({"customer_id": cid, "customer_name": c_name, "debt": debt, "credit": credit})
                existing.customer_name = c_name
                existing.debt = debt
                existing.credit = credit
            else:
                new_cust = Customer(customer_id=cid, customer_name=c_name, debt=debt, credit=credit)
                db.add(new_cust)
            inserted += 1
        
        await db.commit()
        return True, f"تم استيراد {inserted} حساب بنجاح.", notifications

    @staticmethod
    async def _import_medicines(db: AsyncSession, df: pd.DataFrame) -> tuple[bool, str, list]:
        column_map = {
            "رقم الصنف": "item_code", "اسم الصنف": "name", 
            "سعر البيع": "price", "سعر التكلفة": "cost_price", 
            "الرصيد": "quantity", "ت.الصلاحية": "expiry_date", 
            "الرقم الاصلي": "barcode", "فئة الصنف": "category"
        }
        df = df.rename(columns=column_map)
        inserted = 0

        for _, row in df.iterrows():
            code = str(row.get("item_code", "")).strip()
            if code.endswith(".0"): code = code[:-2]
            if not code or code == "nan": continue

            name = str(row.get("name", ""))
            qty = int(InventoryService.safe_float(row.get("quantity")))
            price = InventoryService.safe_float(row.get("price"))
            cost = InventoryService.safe_float(row.get("cost_price"))
            
            result = await db.execute(select(Medicine).where(Medicine.item_code == code))
            existing = result.scalars().first()
            
            is_new = False
            if existing:
                if qty > existing.quantity:
                    is_new = True
                existing.name = name
                existing.quantity = qty
                existing.price = price
                existing.cost_price = cost
                existing.is_new_arrival = is_new
            else:
                new_med = Medicine(item_code=code, name=name, quantity=qty, price=price, cost_price=cost, is_new_arrival=True)
                db.add(new_med)
            inserted += 1
            
        await db.commit()
        return True, f"تم استيراد {inserted} دواء بنجاح.", []
