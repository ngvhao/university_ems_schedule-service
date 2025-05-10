from enum import Enum

class EAccountStatus(Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"

class EUserRole(Enum):
    GUEST = 0,
    STUDENT = 1,
    LECTURER = 2,
    ACADEMIC_MANAGER = 3,
    HEAD_OF_DEPARTMENT = 4,
    ADMINISTRATOR = 5
