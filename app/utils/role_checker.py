from fastapi import HTTPException, Request
from typing import List
from functools import wraps

def check_role(allowed_roles: List[str]):
    def decorator(func):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            user_role = request.state.user_role
            if user_role not in allowed_roles:
                raise HTTPException(
                    status_code=403,
                    detail=f"Role {user_role} not authorized to perform this action"
                )
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator 