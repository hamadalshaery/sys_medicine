from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # حماية ضد Clickjacking (يمنع عرض الموقع داخل iframe)
        response.headers["X-Frame-Options"] = "DENY"
        
        # حماية ضد استنشاق محتوى الملفات (MIME Sniffing)
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # تفعيل حماية المتصفح ضد ثغرات XSS
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # إجبار التصفح عبر HTTPS (مفيد عند النشر على الاستضافة)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # الحد من المعلومات المرسلة في الـ Referer
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # منع الوصول لميزات الجهاز غیر الضروریة
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        
        return response
