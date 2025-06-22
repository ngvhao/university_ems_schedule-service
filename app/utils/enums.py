from enum import Enum

class EObjectStrategy(Enum):
    FEASIBLE_ONLY = 'FEASIBLE_ONLY'
    BALANCE_LOAD = 'BALANCE_LOAD'
    EARLY_START = 'EARLY_START'
    BALANCE_LOAD_AND_EARLY_START = 'BALANCE_LOAD_AND_EARLY_START'
    COMPACT_SCHEDULE = 'COMPACT_SCHEDULE'


class ERoomType(Enum):
  CLASSROOM = 'CLASSROOM',
  LAB = 'LAB',
  OFFICE = 'OFFICE'

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

