from fastapi import APIRouter
from app.routers import sales, products, dashboard_api, auth, users

# إنشاء راوتر التجميع الرئيسي للـ API
router = APIRouter()

# مسارات تسجيل الدخول والتحقق
router.include_router(auth.router)

# مسارات إدارة المستخدمين
router.include_router(users.router)

# دمج راوتر المبيعات (Sales)
router.include_router(sales.router)

# دمج راوتر المنتجات (Products)
router.include_router(products.router)

# دمج راوتر لوحة التحكم (Dashboard)
router.include_router(dashboard_api.router)


# يمكن إضافة راوترات أخرى مستقبلاً مثل customers و inventory
