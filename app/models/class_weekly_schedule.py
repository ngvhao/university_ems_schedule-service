from sqlalchemy import Column, ForeignKey, Integer, Date, String
from sqlalchemy.orm import relationship

from app.database import Base


class ClassWeeklySchedule(Base):
    __tablename__ = 'class_weekly_schedules'
    
    id = Column(Integer, primary_key=True)
    class_group_id = Column('classGroupId', Integer, ForeignKey('class_groups.id')) 
    start_date = Column('startDate', Date)
    end_date = Column('endDate', Date)
    day_of_week = Column('dayOfWeek', String)
    room_id = Column('roomId', Integer)
    lecturer_id = Column('lecturerId', Integer)
    time_slot_id  = Column('timeSlotId', Integer)

    
    class_group = relationship("ClassGroup", back_populates="schedules")
