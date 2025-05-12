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
import random

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
            {"courseSemesterId": 101, "totalSemesterSessions": 15, "registeredStudents": 120},
            {"courseSemesterId": 102, "totalSemesterSessions": 15, "registeredStudents": 70},
            {"courseSemesterId": 103, "totalSemesterSessions": 15, "registeredStudents": 150},
            {"courseSemesterId": 104, "totalSemesterSessions": 5, "registeredStudents": 90},
            {"courseSemesterId": 105, "totalSemesterSessions": 15, "registeredStudents": 40},
            {"courseSemesterId": 201, "totalSemesterSessions": 15, "registeredStudents": 180},
            {"courseSemesterId": 202, "totalSemesterSessions": 10, "registeredStudents": 55},
            {"courseSemesterId": 203, "totalSemesterSessions": 15, "registeredStudents": 100},
            {"courseSemesterId": 204, "totalSemesterSessions": 8, "registeredStudents": 60},
            {"courseSemesterId": 205, "totalSemesterSessions": 12, "registeredStudents": 30},
            {"courseSemesterId": 301, "totalSemesterSessions": 15, "registeredStudents": 200},
            {"courseSemesterId": 302, "totalSemesterSessions": 15, "registeredStudents": 130},
            {"courseSemesterId": 303, "totalSemesterSessions": 15, "registeredStudents": 75},
            {"courseSemesterId": 304, "totalSemesterSessions": 7, "registeredStudents": 45},
            {"courseSemesterId": 305, "totalSemesterSessions": 14, "registeredStudents": 95}
        ],
        "lecturers": [
            {"userId": 1, "departmentId": 10, "teachingCourses": [101, 102, 205]},
            {"userId": 2, "departmentId": 10, "teachingCourses": [101, 103, 201, 301]},
            {"userId": 3, "departmentId": 20, "teachingCourses": [102, 104, 202, 203, 303]},
            {"userId": 4, "departmentId": 20, "teachingCourses": [104, 204, 302, 304, 305]},
            {"userId": 5, "departmentId": 10, "teachingCourses": [103, 201, 202, 305]},
            {"userId": 6, "departmentId": 30, "teachingCourses": [105, 203, 204, 301, 302]},
            {"userId": 7, "departmentId": 30, "teachingCourses": [101, 303, 304, 305]},
            {"userId": 8, "departmentId": 10, "teachingCourses": [102, 104, 201, 205, 302]},
            {"userId": 9, "departmentId": 20, "teachingCourses": [103, 202, 203, 301, 304]},
            {"userId": 10, "departmentId": 30, "teachingCourses": [105, 304, 303, 305]},
            {"userId": 11, "departmentId": 30, "teachingCourses": [301, 103, 303, 305]},
            {"userId": 12, "departmentId": 30, "teachingCourses": [105, 301, 204, 305]}
        ],
        "rooms": [
            {"roomNumber": "A1-101", "buildingName": "A1", "floor": "1", "capacity": 60},
            {"roomNumber": "A1-102", "buildingName": "A1", "floor": "1", "capacity": 40},
            {"roomNumber": "A1-201", "buildingName": "A1", "floor": "2", "capacity": 50},
            {"roomNumber": "A1-202", "buildingName": "A1", "floor": "2", "capacity": 50},
            {"roomNumber": "A1-203", "buildingName": "A1", "floor": "2", "capacity": 50},
            {"roomNumber": "A1-204", "buildingName": "A1", "floor": "2", "capacity": 50},
            {"roomNumber": "A1-205", "buildingName": "A1", "floor": "2", "capacity": 50},
            {"roomNumber": "A1-202", "buildingName": "A1", "floor": "2", "capacity": 30, "roomType": "LAB"},
            {"roomNumber": "B2-101", "buildingName": "B2", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL"},
            {"roomNumber": "B2-102", "buildingName": "B2", "floor": "1", "capacity": 80},
            {"roomNumber": "B2-201", "buildingName": "B2", "floor": "2", "capacity": 45},
            {"roomNumber": "C1-301", "buildingName": "C1", "floor": "3", "capacity": 70},
            {"roomNumber": "C1-302", "buildingName": "C1", "floor": "3", "capacity": 35, "roomType": "LAB"},
            {"roomNumber": "D3-401", "buildingName": "D3", "floor": "4", "capacity": 100, "roomType": "LECTURE_HALL"},
            {"roomNumber": "D3-402", "buildingName": "D3", "floor": "4", "capacity": 50},
            {"roomNumber": "E1-105", "buildingName": "E1", "floor": "1", "capacity": 25, "roomType": "LAB"}
        ],
        "timeSlots": [
            {"startTime": "07:00", "endTime": "08:50", "shift": 1},
            {"startTime": "09:00", "endTime": "10:50", "shift": 2},
            {"startTime": "11:00", "endTime": "12:50", "shift": 3},
            {"startTime": "13:30", "endTime": "15:20", "shift": 4},
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
    
@router.get("/calculating_test_large", 
            response_model=ScheduleResultDTO,
            summary="Calculate schedule with FIXED LARGE test data",
            description="Uses a fixed internal larger dataset to test the scheduling algorithm with more courses.") 
async def calculating_schedule_fixed_test_large():
    # --- DỮ LIỆU FIX CỨNG LỚN HƠN ---
    course_semesters_data = [
        # Khoa Công nghệ Thông tin
        {"courseSemesterId": 1001, "totalSemesterSessions": 15, "registeredStudents": 120, "name": "Nhập môn Lập trình"},
        {"courseSemesterId": 1002, "totalSemesterSessions": 15, "registeredStudents": 110, "name": "Cấu trúc Dữ liệu & Giải thuật"},
        {"courseSemesterId": 1003, "totalSemesterSessions": 15, "registeredStudents": 100, "name": "Lập trình Hướng đối tượng"},
        {"courseSemesterId": 1004, "totalSemesterSessions": 10, "registeredStudents": 90, "name": "Cơ sở Dữ liệu"},
        {"courseSemesterId": 1005, "totalSemesterSessions": 10, "registeredStudents": 80, "name": "Mạng Máy tính"},
        {"courseSemesterId": 1006, "totalSemesterSessions": 15, "registeredStudents": 70, "name": "Phát triển Web"}, # Cần 2 buổi/tuần nếu muốn xong sớm
        {"courseSemesterId": 1007, "totalSemesterSessions": 12, "registeredStudents": 60, "name": "An toàn Thông tin"},
        {"courseSemesterId": 1008, "totalSemesterSessions": 15, "registeredStudents": 50, "name": "Trí tuệ Nhân tạo"},
        {"courseSemesterId": 1009, "totalSemesterSessions": 8, "registeredStudents": 40, "name": "Kiểm thử Phần mềm"},
        {"courseSemesterId": 1010, "totalSemesterSessions": 15, "registeredStudents": 130, "name": "Đồ án Cơ sở ngành CNTT"},

        # Khoa Kinh tế
        {"courseSemesterId": 2001, "totalSemesterSessions": 15, "registeredStudents": 150, "name": "Kinh tế Vi mô"},
        {"courseSemesterId": 2002, "totalSemesterSessions": 15, "registeredStudents": 140, "name": "Kinh tế Vĩ mô"},
        {"courseSemesterId": 2003, "totalSemesterSessions": 10, "registeredStudents": 100, "name": "Nguyên lý Kế toán"},
        {"courseSemesterId": 2004, "totalSemesterSessions": 12, "registeredStudents": 90, "name": "Marketing Căn bản"},
        {"courseSemesterId": 2005, "totalSemesterSessions": 15, "registeredStudents": 80, "name": "Quản trị Học"},
        {"courseSemesterId": 2006, "totalSemesterSessions": 10, "registeredStudents": 70, "name": "Tài chính Doanh nghiệp"},
        {"courseSemesterId": 2007, "totalSemesterSessions": 15, "registeredStudents": 160, "name": "Luật Kinh tế"},
        {"courseSemesterId": 2008, "totalSemesterSessions": 8, "registeredStudents": 50, "name": "Kinh tế Lượng"},
        {"courseSemesterId": 2009, "totalSemesterSessions": 15, "registeredStudents": 60, "name": "Thương mại Điện tử"},
        {"courseSemesterId": 2010, "totalSemesterSessions": 15, "registeredStudents": 100, "name": "Đồ án chuyên ngành Kinh tế"},

        # Khoa Ngoại ngữ
        {"courseSemesterId": 3001, "totalSemesterSessions": 15, "registeredStudents": 50, "name": "Tiếng Anh Cơ bản 1"},
        {"courseSemesterId": 3002, "totalSemesterSessions": 15, "registeredStudents": 50, "name": "Tiếng Anh Cơ bản 2"},
        {"courseSemesterId": 3003, "totalSemesterSessions": 15, "registeredStudents": 40, "name": "Ngữ âm Thực hành"},
        {"courseSemesterId": 3004, "totalSemesterSessions": 10, "registeredStudents": 35, "name": "Văn hóa Anh-Mỹ"},
        {"courseSemesterId": 3005, "totalSemesterSessions": 15, "registeredStudents": 30, "name": "Dịch Thuật Tổng quát"},
        {"courseSemesterId": 3006, "totalSemesterSessions": 12, "registeredStudents": 25, "name": "Tiếng Anh Thương mại"},
        {"courseSemesterId": 3007, "totalSemesterSessions": 15, "registeredStudents": 45, "name": "Tiếng Nhật Sơ cấp 1"},
        {"courseSemesterId": 3008, "totalSemesterSessions": 15, "registeredStudents": 40, "name": "Tiếng Nhật Sơ cấp 2"},
        {"courseSemesterId": 3009, "totalSemesterSessions": 10, "registeredStudents": 30, "name": "Văn hóa Nhật Bản"},
        {"courseSemesterId": 3010, "totalSemesterSessions": 15, "registeredStudents": 20, "name": "Phiên dịch Anh-Việt"},
        # Thêm khoảng 70 môn nữa để đủ 100
    ]
    # Tạo thêm môn học giả định để đủ 100
    current_max_course_id = 3010
    num_existing_courses = len(course_semesters_data)
    num_to_generate_more = 100 - num_existing_courses

    for i in range(num_to_generate_more):
        current_max_course_id +=1
        dept_prefix = random.choice([4,5,6]) # Các khoa giả định
        course_semesters_data.append({
            "courseSemesterId": int(f"{dept_prefix}0{i:02d}"), # Tạo ID có vẻ thực tế
            "totalSemesterSessions": random.choice([8, 10, 12, 15]),
            "registeredStudents": random.randint(20, 150)
        })


    lecturers_data = [
        # Giảng viên Khoa CNTT
        {"userId": 1, "departmentId": 1, "teachingCourses": [1001, 1002, 1005]},
        {"userId": 2, "departmentId": 1, "teachingCourses": [1001, 1003, 1004, 1006]},
        {"userId": 3, "departmentId": 1, "teachingCourses": [1002, 1007, 1008, 1009]},
        {"userId": 4, "departmentId": 1, "teachingCourses": [1004, 1005, 1006, 1010]},
        {"userId": 13, "departmentId": 1, "teachingCourses": [1001, 1008, 1009, 1003]},


        # Giảng viên Khoa Kinh tế
        {"userId": 5, "departmentId": 2, "teachingCourses": [2001, 2002, 2005]},
        {"userId": 6, "departmentId": 2, "teachingCourses": [2001, 2003, 2004, 2006]},
        {"userId": 7, "departmentId": 2, "teachingCourses": [2002, 2007, 2008, 2009]},
        {"userId": 8, "departmentId": 2, "teachingCourses": [2004, 2005, 2006, 2010]},
        {"userId": 14, "departmentId": 2, "teachingCourses": [2001, 2008, 2009, 2003]},

        # Giảng viên Khoa Ngoại ngữ
        {"userId": 9, "departmentId": 3, "teachingCourses": [3001, 3002, 3003, 3005]},
        {"userId": 10, "departmentId": 3, "teachingCourses": [3001, 3004, 3006, 3010]},
        {"userId": 11, "departmentId": 3, "teachingCourses": [3007, 3008, 3009]},
        {"userId": 12, "departmentId": 3, "teachingCourses": [3002, 3005, 3007, 3010]},
        {"userId": 15, "departmentId": 3, "teachingCourses": [3001, 3008, 3003, 3004]},

        # Thêm giảng viên cho các khoa giả định (4, 5, 6)
        {"userId": 16, "departmentId": 4, "teachingCourses": []},
        {"userId": 17, "departmentId": 4, "teachingCourses": []},
        {"userId": 18, "departmentId": 5, "teachingCourses": []},
        {"userId": 19, "departmentId": 5, "teachingCourses": []},
        {"userId": 20, "departmentId": 6, "teachingCourses": []},
        {"userId": 21, "departmentId": 6, "teachingCourses": []},
    ]

    # Phân công các môn học mới cho giảng viên (đảm bảo mỗi môn có GV và phân bổ thêm)
    all_course_ids = [cs["courseSemesterId"] for cs in course_semesters_data]
    num_lecturers = len(lecturers_data)
    for course_id in all_course_ids:
        is_assigned = any(course_id in lecturer["teachingCourses"] for lecturer in lecturers_data)
        if not is_assigned:
            # Gán cho giảng viên thuộc khoa tương ứng nếu có thể, hoặc ngẫu nhiên
            dept_prefix_course = int(str(course_id)[0])
            potential_lecturers_for_course = [
                idx for idx, lect in enumerate(lecturers_data) 
                if lect["departmentId"] == dept_prefix_course or random.random() < 0.3 # 30% chance gán cho GV khoa khác
            ]
            if not potential_lecturers_for_course: # Nếu không có GV khoa đó, gán ngẫu nhiên
                potential_lecturers_for_course = list(range(num_lecturers))
            
            lecturer_idx_to_assign = random.choice(potential_lecturers_for_course)
            if course_id not in lecturers_data[lecturer_idx_to_assign]["teachingCourses"]:
                 lecturers_data[lecturer_idx_to_assign]["teachingCourses"].append(course_id)
    
    # Đảm bảo mỗi giảng viên có ít nhất một vài môn để dạy (nếu họ chưa có)
    for i in range(num_lecturers):
        if not lecturers_data[i]["teachingCourses"]:
            num_courses_to_assign_gv = random.randint(2,5)
            for _ in range(num_courses_to_assign_gv):
                course_to_assign = random.choice(all_course_ids)
                # Chỉ gán nếu GV đó thuộc khoa của môn học đó, hoặc với một xác suất nhỏ
                course_dept_prefix = int(str(course_to_assign)[0])
                if lecturers_data[i]["departmentId"] == course_dept_prefix or random.random() < 0.1:
                    if course_to_assign not in lecturers_data[i]["teachingCourses"]:
                         lecturers_data[i]["teachingCourses"].append(course_to_assign)


    rooms_data = [
        # Phòng học thường
        {"roomNumber": "A101", "buildingName": "A", "floor": "1", "capacity": 60},
        {"roomNumber": "A102", "buildingName": "A", "floor": "1", "capacity": 40},
        {"roomNumber": "A201", "buildingName": "A", "floor": "2", "capacity": 50},
        {"roomNumber": "A202", "buildingName": "A", "floor": "2", "capacity": 50},
        {"roomNumber": "A203", "buildingName": "A", "floor": "2", "capacity": 50},
        {"roomNumber": "A301", "buildingName": "A", "floor": "3", "capacity": 60},
        {"roomNumber": "A302", "buildingName": "A", "floor": "3", "capacity": 40},

        # Giảng đường
        {"roomNumber": "B101-GH", "buildingName": "B", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL"},
        {"roomNumber": "B102-GH", "buildingName": "B", "floor": "1", "capacity": 150, "roomType": "LECTURE_HALL"},
        {"roomNumber": "B201-GH", "buildingName": "B", "floor": "2", "capacity": 180, "roomType": "LECTURE_HALL"},


        # Phòng thường tòa C
        {"roomNumber": "C101", "buildingName": "C", "floor": "1", "capacity": 70},
        {"roomNumber": "C102", "buildingName": "C", "floor": "1", "capacity": 70},
        {"roomNumber": "C201", "buildingName": "C", "floor": "2", "capacity": 80},
        {"roomNumber": "C202", "buildingName": "C", "floor": "2", "capacity": 80},
        {"roomNumber": "C301", "buildingName": "C", "floor": "3", "capacity": 50},

        # Giảng đường lớn tòa D
        {"roomNumber": "D401-GH", "buildingName": "D", "floor": "4", "capacity": 200, "roomType": "LECTURE_HALL"},
        {"roomNumber": "D402-GH", "buildingName": "D", "floor": "4", "capacity": 100, "roomType": "LECTURE_HALL"},

        # Phòng Lab
        {"roomNumber": "Lab-IT1", "buildingName": "L", "floor": "1", "capacity": 40, "roomType": "LAB"},
        {"roomNumber": "Lab-IT2", "buildingName": "L", "floor": "1", "capacity": 40, "roomType": "LAB"},
        {"roomNumber": "Lab-IT3", "buildingName": "L", "floor": "2", "capacity": 30, "roomType": "LAB"},
        {"roomNumber": "Lab-Eng1", "buildingName": "L", "floor": "2", "capacity": 25, "roomType": "LAB"}, # Phòng lab ngoại ngữ
        {"roomNumber": "Lab-Eco1", "buildingName": "L", "floor": "3", "capacity": 35, "roomType": "LAB"}, # Phòng lab kinh tế
    ]
    # Thêm 10 phòng học thường nữa
    for i in range(1, 11):
        rooms_data.append(
            {"roomNumber": f"TC-{i:02d}", "buildingName": "TC", "floor": str(random.randint(1,4)), 
             "capacity": random.choice([40, 50, 60, 70]), "roomType": "CLASSROOM"}
        )
    # Thêm 2 giảng đường nữa
    rooms_data.append({"roomNumber": "GH-X1", "buildingName": "X", "floor": "1", "capacity": 100, "roomType": "LECTURE_HALL"})
    rooms_data.append({"roomNumber": "GH-X2", "buildingName": "X", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL"})


    input_data_dict = {
        "semesterStartDate": "2024-09-02",
        "semesterEndDate": "2025-01-19", # 20 tuần
        "courseSemesters": course_semesters_data,
        "lecturers": lecturers_data,
        "rooms": rooms_data,
        "timeSlots": [ 
            {"startTime": "07:00", "endTime": "08:50", "shift": 1}, # Ca 1
            {"startTime": "09:00", "endTime": "10:50", "shift": 2}, # Ca 2
            {"startTime": "13:30", "endTime": "15:20", "shift": 3}, # Ca 3
            {"startTime": "15:30", "endTime": "17:20", "shift": 4}, # Ca 4
        ],
        "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
        "maxSessionsPerLecturerConstraint": None, # Để thuật toán tự do hơn
        "solverTimeLimitSeconds": 180.0,  # Tăng thời gian cho dữ liệu lớn
        "objectiveStrategy": "BALANCE_LOAD_AND_EARLY_START", 
        "penaltyWeightFixedDayShiftViolation": 100000, # Phạt rất nặng nếu vi phạm ngày/ca cố định
        "maxSessionsPerWeekAllowed": 2 # Cho phép tối đa 2 buổi/tuần nếu cần để giãn lịch
    }
    try:
        input_dto_obj = ScheduleInputDTO(**input_data_dict)
        logger.info(f"Input DTO created for LARGE test endpoint with {len(input_dto_obj.courseSemesters)} courses, {len(input_dto_obj.lecturers)} lecturers, {len(input_dto_obj.rooms)} rooms.")
        cp_schedule_result = await ScheduleService.calculate_with_cp(input_dto_obj)
        logger.info("Schedule calculation completed for LARGE test endpoint.")
        return cp_schedule_result
    except ValidationError as ve: 
        logger.error(f"Input data validation error (LARGE TEST): {ve.errors()}", exc_info=False)
        raise HTTPException(status_code=422, detail=ve.errors())
    except HTTPException as he: 
        logger.error(f"HTTPException from service (LARGE TEST): Status {he.status_code}, Detail: {he.detail}", exc_info=False)
        raise he
    except Exception as e: 
        logger.critical(f"CRITICAL UNHANDLED EXCEPTION in /calculating_test_large: {type(e).__name__} - {str(e)}", exc_info=True)
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


