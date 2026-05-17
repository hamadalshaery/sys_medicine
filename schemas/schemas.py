"""
وظيفة هذا الملف: تعريف نماذج البيانات (Pydantic) للتحقق من المدخلات (Input Validation).
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional, List

class MedicineBase(BaseModel):
    item_code: str
    name: str
    category: Optional[str] = None
    quantity: int = 0
    expiry_date: Optional[str] = None
    price: float = 0.0
    cost_price: float = 0.0
    barcode: Optional[str] = None
    min_stock_level: int = 5

class MedicineCreate(MedicineBase):
    pass

class MedicineResponse(MedicineBase):
    id: int
    is_new_arrival: bool
    image_file_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class CustomerBase(BaseModel):
    customer_id: str
    customer_name: str
    main_account: Optional[str] = None
    debt: float = 0.0
    credit: float = 0.0
    phone: Optional[str] = None
    address: Optional[str] = None

class CustomerResponse(CustomerBase):
    model_config = ConfigDict(from_attributes=True)

class UserBase(BaseModel):
    username: str

class UserCreate(UserBase):
    password: str

class UserResponse(UserBase):
    id: int
    role: str
    linked_customer_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
