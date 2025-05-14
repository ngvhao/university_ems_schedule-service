from sqlalchemy import Column, ForeignKey, Integer
from sqlalchemy.orm import relationship

from app.database import Base

class ClassGroup(Base):
    __tablename__ = 'class_groups'
    
    id = Column(Integer, primary_key=True)
    group_number = Column(Integer)
    semester_id = Column('semesterId', Integer)
    
    schedules = relationship("ClassWeeklySchedule", back_populates="class_group")