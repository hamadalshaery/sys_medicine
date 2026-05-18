from pydantic import BaseModel, ConfigDict
from typing import Optional

class UserCreate(BaseModel):
    username: str
    password: str
    role: str = "employee"

class UserUpdate(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    is_totp_enabled: bool

    model_config = ConfigDict(from_attributes=True)

class VerifyTOTP(BaseModel):
    code: str

class LoginRequest(BaseModel):
    username: str
    password: str
    totp_code: Optional[str] = None
