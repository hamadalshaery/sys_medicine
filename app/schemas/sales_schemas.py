from pydantic import BaseModel
from typing import List, Optional

class CartItem(BaseModel):
    item_code: str
    name: str
    category: Optional[str] = ""
    quantity: int
    unit_price: float
    original_price: Optional[float] = None

class CheckoutRequest(BaseModel):
    customer_id: str
    pharmacy: str
    payment_method: str = "credit"
    cart_items: List[CartItem]

class CheckoutResponse(BaseModel):
    invoice_id: int
    pdf_url: str
