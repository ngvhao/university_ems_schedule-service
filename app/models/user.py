from sqlalchemy import Column, Integer, String, Enum, Date, Text
from sqlalchemy.orm import relationship
from app.database import Base
from app.enums.user import EAccountStatus, EUserRole
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import backref

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    universityEmail = Column(String, unique=True, nullable=False)
    personalEmail = Column(String, nullable=False)
    password = Column(String, nullable=False)
    firstName = Column(String, nullable=False)
    lastName = Column(String, nullable=False)
    avatarUrl = Column(String, nullable=True)
    role = Column(Enum(EUserRole), nullable=False)
    phoneNumber = Column(String, nullable=True)
    identityCardNumber = Column(String, nullable=True)
    dateOfBirth = Column(Date, nullable=True)
    gender = Column(String, nullable=True)
    hometown = Column(String, nullable=True)
    permanentAddress = Column(Text, nullable=True)
    temporaryAddress = Column(Text, nullable=True)
    nationality = Column(String, nullable=True)
    ethnicity = Column(String, nullable=True)
    isActive = Column(Enum(EAccountStatus), default=EAccountStatus.ACTIVE, nullable=False)
