from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.class_group import ClassGroup
from app.models.class_weekly_schedule import ClassWeeklySchedule
from app.services.schedule import ExistingScheduleRecord 

class ClassWeeklyScheduleService:
   @staticmethod
   async def get_class_weekly_schedules(semester_id: int, db: AsyncSession) -> list[ExistingScheduleRecord]:
    stmt = (
        select(ClassWeeklySchedule)
        .options(selectinload(ClassWeeklySchedule.class_group))   
        .join(ClassWeeklySchedule.class_group) 
        .where(ClassGroup.semester_id == semester_id)
    )
    result = await db.execute(stmt)
    schedules = result.scalars().all()
    return schedules
  

    