from fastapi import APIRouter, Depends, HTTPException
from databases import Database
from app.database import get_db
from app.enums.user import EUserRole
from app.services.user import UserService
from app.utils.role_checker import check_role

router = APIRouter(prefix="/schedules")

@check_role(allowed_roles=[EUserRole.ADMINISTRATOR, EUserRole.HEAD_OF_DEPARTMENT, EUserRole.ACADEMIC_MANAGER])
@router.post("/calculating")
async def calculating_schedule():
  pass