from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base


class ClassWeeklySchedule(Base):
    __tablename__ = 'class_weekly_schedules'
    
    id = Column(Integer, primary_key=True)
    class_group_id = Column('classGroupId', Integer, ForeignKey('class_groups.id')) 
    
    class_group = relationship("ClassGroup", back_populates="schedules")
