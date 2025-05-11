import logging
from fastapi import APIRouter, Depends, HTTPException
from databases import Database
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from app.database import get_db
from app.enums.user import EUserRole
from app.services.schedule import ScheduleInputDTO, ScheduleResultDTO, ScheduleService
from app.services.user import UserService
from app.utils.role_checker import check_role

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules")

# @check_role(allowed_roles=[EUserRole.ADMINISTRATOR, EUserRole.HEAD_OF_DEPARTMENT, EUserRole.ACADEMIC_MANAGER])
# Endpoint GET để test nhanh với dữ liệu cố định
@router.get("/calculating_test", 
            response_model=ScheduleResultDTO,
            summary="Calculate schedule with test data (GET)",
            description="Uses a fixed internal dataset to test the scheduling algorithm.") 
async def calculating_schedule_test():
    input_data_dict = {
    "semesterStartDate": "2024-09-02", 
    "semesterEndDate": "2025-01-19", 
    "courseSemesters": [
        { "courseSemesterId": 101, "credits": 3, "totalRequiredSessions": 15, "registeredStudents": 120, "desiredNumberOfGroups": 3 },
        { "courseSemesterId": 102, "credits": 2, "totalRequiredSessions": 10, "registeredStudents": 70, "desiredNumberOfGroups": 2 },
        { "courseSemesterId": 103, "credits": 4, "totalRequiredSessions": 30, "registeredStudents": 150, "desiredNumberOfGroups": 3 },
        { "courseSemesterId": 104, "credits": 1, "totalRequiredSessions": 5, "registeredStudents": 90, "desiredNumberOfGroups": 2 },
        { "courseSemesterId": 105, "credits": 3, "totalRequiredSessions": 15, "registeredStudents": 40, "desiredNumberOfGroups": None },
        { "courseSemesterId": 201, "credits": 3, "totalRequiredSessions": 15, "registeredStudents": 180, "desiredNumberOfGroups": 4 },
        { "courseSemesterId": 202, "credits": 2, "totalRequiredSessions": 10, "registeredStudents": 55, "desiredNumberOfGroups": 2 },
        { "courseSemesterId": 203, "credits": 4, "totalRequiredSessions": 30, "registeredStudents": 100, "desiredNumberOfGroups": 2 },
        { "courseSemesterId": 204, "credits": 1, "totalRequiredSessions": 8, "registeredStudents": 60, "desiredNumberOfGroups": 2 }, 
        { "courseSemesterId": 205, "credits": 3, "totalRequiredSessions": 12, "registeredStudents": 30, "desiredNumberOfGroups": 1 },
        { "courseSemesterId": 301, "credits": 2, "totalRequiredSessions": 15, "registeredStudents": 200, "desiredNumberOfGroups": 5 },
        { "courseSemesterId": 302, "credits": 4, "totalRequiredSessions": 28, "registeredStudents": 130, "desiredNumberOfGroups": 3 },
        { "courseSemesterId": 303, "credits": 3, "totalRequiredSessions": 10, "registeredStudents": 75, "desiredNumberOfGroups": 2 },
        { "courseSemesterId": 304, "credits": 1, "totalRequiredSessions": 7, "registeredStudents": 45, "desiredNumberOfGroups": None },
        { "courseSemesterId": 305, "credits": 2, "totalRequiredSessions": 14, "registeredStudents": 95, "desiredNumberOfGroups": 3 }
    ],
    "lecturers": [
        { "userId": 1, "departmentId": 10, "teachingCourses": [101, 102, 205] },
        { "userId": 2, "departmentId": 10, "teachingCourses": [101, 103, 201, 301] },
        { "userId": 3, "departmentId": 20, "teachingCourses": [102, 104, 202, 203, 303] },
        { "userId": 4, "departmentId": 20, "teachingCourses": [104, 204, 302, 304, 305] },
        { "userId": 5, "departmentId": 10, "teachingCourses": [103, 201, 202, 305] },
        { "userId": 6, "departmentId": 30, "teachingCourses": [105, 203, 204, 301, 302] },
        { "userId": 7, "departmentId": 30, "teachingCourses": [101, 303, 304, 305] },
        { "userId": 8, "departmentId": 10, "teachingCourses": [102, 104, 201, 205, 302]},
        { "userId": 9, "departmentId": 20, "teachingCourses": [103, 202, 203, 301, 304]},
        { "userId": 10, "departmentId": 30, "teachingCourses": [105, 204, 303, 305]}
    ],
    "rooms": [
        { "roomNumber": "A1-101", "buildingName": "A1", "floor": "1", "capacity": 60 },
        { "roomNumber": "A1-102", "buildingName": "A1", "floor": "1", "capacity": 40 },
        { "roomNumber": "A1-201", "buildingName": "A1", "floor": "2", "capacity": 50 },
        { "roomNumber": "A1-202", "buildingName": "A1", "floor": "2", "capacity": 30, "roomType": "LAB" },
        { "roomNumber": "B2-101", "buildingName": "B2", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL" },
        { "roomNumber": "B2-102", "buildingName": "B2", "floor": "1", "capacity": 80 },
        { "roomNumber": "B2-201", "buildingName": "B2", "floor": "2", "capacity": 45 },
        { "roomNumber": "C1-301", "buildingName": "C1", "floor": "3", "capacity": 70 },
        { "roomNumber": "C1-302", "buildingName": "C1", "floor": "3", "capacity": 35, "roomType": "LAB"},
        { "roomNumber": "D3-401", "buildingName": "D3", "floor": "4", "capacity": 100, "roomType": "LECTURE_HALL" },
        { "roomNumber": "D3-402", "buildingName": "D3", "floor": "4", "capacity": 50 },
        { "roomNumber": "E1-105", "buildingName": "E1", "floor": "1", "capacity": 25, "roomType": "LAB"}
    ],
    "timeSlots": [
        {"startTime": "07:00", "endTime": "08:50", "shift": 1}, 
        {"startTime": "09:00", "endTime": "10:50", "shift": 2},
        {"startTime": "11:00", "endTime": "12:50", "shift": 3},
        {"startTime": "13:30", "endTime": "15:20", "shift": 4},
        {"startTime": "15:30", "endTime": "17:20", "shift": 5}
    ],
    "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"], 
    "maxSessionsPerLecturerConstraint": None
    }
    try:
        input_dto_obj = ScheduleInputDTO(**input_data_dict)
        logger.info("Input DTO created successfully for test endpoint.")
        cp_schedule_result = await ScheduleService.calculate_with_cp(input_dto_obj)
        logger.info("Schedule calculation completed for test endpoint.")
        return cp_schedule_result
    except ValidationError as ve: 
        logger.error(f"Input data validation error: {ve.errors()}", exc_info=False)
        raise HTTPException(status_code=422, detail=ve.errors())
    except HTTPException as he: 
        logger.error(f"HTTPException from service: Status {he.status_code}, Detail: {he.detail}", exc_info=False)
        raise he
    except Exception as e: 
        logger.critical(f"CRITICAL UNHANDLED EXCEPTION in /calculating_test: {type(e).__name__} - {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"A critical server error occurred: {str(e)}")
    
@router.post("/calculating", response_model=ScheduleResultDTO)
async def calculate_schedule_endpoint_post(input_data_dict: ScheduleInputDTO):
    try:
        input_dto_obj = input_data_dict
        logger.info("Input DTO created successfully for test endpoint.")
        cp_schedule_result = await ScheduleService.calculate_with_cp(input_dto_obj)
        logger.info("Schedule calculation completed for test endpoint.")
        return cp_schedule_result
    except ValidationError as ve: 
        logger.error(f"Input data validation error: {ve.errors()}", exc_info=False)
        raise HTTPException(status_code=422, detail=ve.errors())
    except HTTPException as he: 
        logger.error(f"HTTPException from service: Status {he.status_code}, Detail: {he.detail}", exc_info=False)
        raise he
    except Exception as e: 
        logger.critical(f"CRITICAL UNHANDLED EXCEPTION in /calculating_test: {type(e).__name__} - {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"A critical server error occurred: {str(e)}")


