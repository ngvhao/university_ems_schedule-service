from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from app.utils.jwt_handler import JWTHandler

class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, public_paths=None):
        super().__init__(app)
        self.public_paths = public_paths or []
        self.jwt_handler = JWTHandler()

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or any(request.url.path.startswith(path) for path in self.public_paths):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or " " not in auth_header:
            return JSONResponse(status_code=401, content={"statusCode": 401, "detail": "Missing or invalid Authorization header"})

        scheme, token = auth_header.split(" ", 1)
        if scheme.lower() != "bearer":
            return JSONResponse(status_code=401, content={"statusCode": 401, "detail": "Invalid authentication scheme"})

        try:
            payload = self.jwt_handler.verify_jwt(token)
            request.state.user_id = payload.get("id")
        except Exception as e:
            return JSONResponse(status_code=401, content={"statusCode": 401, "detail": str(e)})

        return await call_next(request)
