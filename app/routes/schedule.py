from datetime import date, timedelta
import logging
import math
import time
from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException
from databases import Database
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from app.database import get_db
from app.enums.user import EUserRole
from app.services.schedule import CourseSchedulingInfoDTO, FinalScheduleResultDTO,  LecturerInputDTO, LecturerLoadDTO, OccupiedResourceSlotDTO,  RoomInputDTO, ScheduleInputDTO, ScheduleService, TimeSlotInputDTO
from app.services.user import UserService
from app.utils.role_checker import check_role
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules")

def get_sessions_per_week(credits):
    if credits <= 2:
        return 1
    elif credits == 3:
        return 1 # Hoặc 1.5 nếu có ca 1.5 tiết, ở đây giả định là 1 buổi chuẩn
    elif credits == 4:
        return 2
    elif credits >= 5: # Xử lý các trường hợp tín chỉ cao hơn nếu cần
        return 2 # Hoặc 3 tùy theo quy định
    return 1 # Mặc định

@router.get("/calculating")
async def test():
    # 1. Time Slots (Giữ nguyên)
    sample_time_slots = [
        TimeSlotInputDTO(timeSlotId=1, shift=1), # Ca 1
        TimeSlotInputDTO(timeSlotId=2, shift=2), # Ca 2
        TimeSlotInputDTO(timeSlotId=3, shift=3), # Ca 3
        TimeSlotInputDTO(timeSlotId=4, shift=4), # Ca 4
    ]
    time_slot_ids = [ts.timeSlotId for ts in sample_time_slots]

    # 2. Days of Week (Giữ nguyên)
    sample_days_of_week = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"]

    # 3. Lecturers (Mở rộng lên 20)
    num_lecturers = 20
    sample_lecturers = []
    lecturer_ids = []
    for i in range(num_lecturers):
        lecturer_id = 201 + i # Bắt đầu ID từ 201 để không trùng với ví dụ cũ
        sample_lecturers.append(LecturerInputDTO(lecturerId=lecturer_id))
        lecturer_ids.append(lecturer_id)

    # 4. Rooms (Mở rộng lên 30)
    num_rooms = 30
    sample_rooms = []
    room_ids = []
    room_capacities = {} # Lưu capacity để tham khảo
    common_capacities = [30, 40, 50, 60, 70, 80, 100, 120]
    for i in range(num_rooms):
        room_id = 11 + i # Bắt đầu ID từ 11
        building_prefix = random.choice(["A", "B", "C", "D"])
        floor = random.randint(1, 5)
        room_num_on_floor = random.randint(1, 10)
        room_number = f"{building_prefix}{floor}0{room_num_on_floor}"
        capacity = random.choice(common_capacities)
        sample_rooms.append(RoomInputDTO(roomId=room_id, roomNumber=room_number, capacity=capacity))
        room_ids.append(room_id)
        room_capacities[room_id] = capacity

    # 5. Courses to Schedule (Mở rộng lên 100)
    num_courses = 75
    sample_courses_to_schedule = []
    course_ids = []
    for i in range(num_courses):
        course_id = 3001 + i # Bắt đầu ID từ 3001
        credits = random.choice([2, 3, 4]) # Số tín chỉ phổ biến
        sessions_per_week = get_sessions_per_week(credits)
        total_semester_sessions = sessions_per_week * 15
        
        # Số sinh viên đăng ký, có thể nhiều hơn sức chứa phòng lớn nhất
        # để thử nghiệm tính năng chia nhóm
        registered_students = random.randint(20, 150) 
        
        # Chọn ngẫu nhiên 1-3 giảng viên có thể dạy môn này
        num_potential_lecturers = random.randint(1, min(3, len(lecturer_ids)))
        potential_lecturer_ids = random.sample(lecturer_ids, num_potential_lecturers)
        
        sample_courses_to_schedule.append(
            CourseSchedulingInfoDTO(
                courseId=course_id,
                credits=credits,
                totalSemesterSessions=total_semester_sessions,
                registeredStudents=registered_students,
                potentialLecturerIds=potential_lecturer_ids
            )
        )
        course_ids.append(course_id)

    # 6. Semester Info (Giữ nguyên)
    sample_semester_id = 1
    sample_semester_start_date_str = "2024-09-02" # Thứ Hai
    sample_semester_end_date_str = "2024-12-20"   # Thứ Sáu (khoảng 16 tuần, 15 tuần học)

    # Chuyển đổi sang đối tượng date để dễ thao tác
    semester_start_date_obj = date.fromisoformat(sample_semester_start_date_str)
    semester_end_date_obj = date.fromisoformat(sample_semester_end_date_str)

    # 7. Exception Dates (Ngày nghỉ - thêm một vài ngày ngẫu nhiên)
    sample_exception_dates = [
        "2024-09-03", # Một ngày nghỉ lẻ
        "2024-10-14", # Một ngày nghỉ khác
        "2024-11-20", # Ngày nhà giáo Việt Nam (ví dụ)
    ]
    # Thêm một vài ngày nghỉ ngẫu nhiên trong kỳ
    num_random_holidays = 3
    current_date_check = semester_start_date_obj
    while len(sample_exception_dates) < 3 + num_random_holidays and current_date_check <= semester_end_date_obj:
        # Chọn ngày ngẫu nhiên trong 2 tuần đầu hoặc 2 tuần cuối (ví dụ)
        if random.random() < 0.1: # 10% chance to add a holiday
            # Đảm bảo là ngày làm việc (Thứ 2 - Thứ 6)
            if current_date_check.weekday() < 5: # 0=Monday, 4=Friday
                date_str = current_date_check.isoformat()
                if date_str not in sample_exception_dates:
                    sample_exception_dates.append(date_str)
        current_date_check += timedelta(days=1)
    sample_exception_dates = sorted(list(set(sample_exception_dates))) # Loại bỏ trùng lặp và sắp xếp


    # 8. Occupied Slots (Lịch đã có từ khoa khác - tạo ngẫu nhiên)
    sample_occupied_slots = []
    num_occupied_slots = 50 # Tạo khoảng 50 slot bận ngẫu nhiên

    # Tạo danh sách các ngày làm việc hợp lệ trong kỳ (không phải ngày nghỉ)
    valid_working_dates_in_semester = []
    current_date = semester_start_date_obj
    while current_date <= semester_end_date_obj:
        if current_date.weekday() < 5 and current_date.isoformat() not in sample_exception_dates: # Thứ 2 - Thứ 6 và không phải ngày nghỉ
            valid_working_dates_in_semester.append(current_date.isoformat())
        current_date += timedelta(days=1)

    if not valid_working_dates_in_semester:
        print("CẢNH BÁO: Không có ngày làm việc hợp lệ nào trong kỳ để tạo occupied_slots!")
    else:
        for _ in range(num_occupied_slots):
            resource_type = random.choice(['room', 'lecturer'])
            
            if resource_type == 'room':
                resource_id = random.choice(room_ids)
            else: # lecturer
                resource_id = random.choice(lecturer_ids)
                
            # Chọn ngày ngẫu nhiên từ danh sách ngày làm việc hợp lệ
            occupied_date_str = random.choice(valid_working_dates_in_semester)
            time_slot_id = random.choice(time_slot_ids)
            
            # Kiểm tra để tránh thêm slot trùng lặp (đơn giản hóa, có thể không hoàn toàn chính xác nếu có nhiều ràng buộc hơn)
            is_duplicate = False
            for slot in sample_occupied_slots:
                if slot.resourceType == resource_type and \
                slot.resourceId == resource_id and \
                slot.date == occupied_date_str and \
                slot.timeSlotId == time_slot_id:
                    is_duplicate = True
                    break
            if not is_duplicate:
                sample_occupied_slots.append(
                    OccupiedResourceSlotDTO(
                        resourceType=resource_type,
                        resourceId=resource_id,
                        date=occupied_date_str,
                        timeSlotId=time_slot_id
                    )
                )

    # --- Tạo đối tượng ScheduleInputDTO ---
    expanded_schedule_input = ScheduleInputDTO(
        semesterId=sample_semester_id,
        semesterStartDate=sample_semester_start_date_str,
        semesterEndDate=sample_semester_end_date_str,
        coursesToSchedule=sample_courses_to_schedule,
        lecturers=sample_lecturers,
        rooms=sample_rooms,
        timeSlots=sample_time_slots,
        daysOfWeek=sample_days_of_week,
        exceptionDates=[],
        occupiedSlots=[],
        groupSizeTarget=60,
        maxSessionsPerWeekAllowed=3,
        solverTimeLimitSeconds=600.0, # Tăng thời gian giải cho bộ dữ liệu lớn hơn
        objectiveStrategy="BALANCE_LOAD_AND_EARLY_START"
    )

    service = ScheduleService()
    # sample_schedule_input được tạo như trước
    try:
        result: FinalScheduleResultDTO = await service.calculate_with_cp(expanded_schedule_input) 

        print("Scheduling finished.")
        print(f"Solver Status: {result.solverStatus}")
        print(f"Solver Message: {result.solverMessage}")
        print(f"Duration: {result.solverDurationSeconds:.2f}s")
        print(f"Semester ID: {result.semesterId}, From: {result.semesterStartDate}, To: {result.semesterEndDate}")
        print(f"Total Original Sessions to Schedule: {result.totalOriginalSessionsToSchedule}")
        
        print("\n--- Scheduled Courses ---")
        if not result.scheduledCourses:
            print("No courses were scheduled.")
        else:
            for course_dto in result.scheduledCourses: # course_dto là CourseScheduledDTO
                print(f"\nCourse ID: {course_dto.courseId}")
                print(f"  Total Registered Students for Course: {course_dto.totalRegisteredStudents}") # MỚI
                print(f"  Total Sessions for Course: {course_dto.totalSessionsForCourse}")          # MỚI
                
                if not course_dto.scheduledClassGroups:
                    print("  No class groups scheduled for this course.")
                else:
                    for group_dto in course_dto.scheduledClassGroups: # group_dto là ClassGroupScheduledDTO
                        print(f"  Group Number: {group_dto.groupNumber}")
                        # print(f"    Registered Students: {group_dto.registeredStudents} (Max: {group_dto.maxStudents})") # BỎ DÒNG NÀY
                        print(f"    Max Students per Group: {group_dto.maxStudents}") # SỬA LẠI
                        print(f"    Lecturer ID: {group_dto.lecturerId}")
                        print(f"    Group Study Period: {group_dto.groupStartDate} to {group_dto.groupEndDate}")
                        print(f"    Teaching Weeks: {group_dto.totalTeachingWeeksForGroup}, Sessions/Week: {group_dto.sessionsPerWeekForGroup}")
                        print(f"    Weekly Schedule Details ({len(group_dto.weeklyScheduleDetails)} entries):")
                        if not group_dto.weeklyScheduleDetails:
                            print("      No weekly schedule details found for this group.")
                        else:
                            for detail in group_dto.weeklyScheduleDetails:
                                print(f"      - Day: {detail.dayOfWeek}, TimeSlotID: {detail.timeSlotId}, RoomID: {detail.roomId}")
        
        print("\n--- Lecturer Load ---")
        if not result.lecturerLoad:
            print("No lecturer load information available.")
        else:
            for load_info in result.lecturerLoad:
                print(f"  Lecturer {load_info.lecturerId}: {load_info.sessionsAssigned} sessions assigned")
        
        if result.loadDifference is not None:
          print(f"Load Difference (max - min): {result.loadDifference}")
        
        return result 

    except HTTPException as he:
        print(f"HTTP Error {he.status_code}: {he.detail}")
        # return JSONResponse(status_code=he.status_code, content={"detail": he.detail}) # Ví dụ trong FastAPI
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()
        # return JSONResponse(status_code=500, content={"detail": "Internal Server Error"}) # Ví dụ

# # @check_role(allowed_roles=[EUserRole.ADMINISTRATOR, EUserRole.HEAD_OF_DEPARTMENT, EUserRole.ACADEMIC_MANAGER])
# # Endpoint GET để test nhanh với dữ liệu cố định
# @router.get("/calculating_test", 
#             response_model=ScheduleResultDTO,
#             summary="Calculate schedule with test data (GET)",
#             description="Uses a fixed internal dataset to test the scheduling algorithm.") 
# async def calculating_schedule_test():
#     input_data_dict = {
#         "semesterStartDate": "2024-09-02",
#         "semesterEndDate": "2025-01-19",
#         "courseSemesters": [
#             {"courseSemesterId": 101, "totalSemesterSessions": 15, "registeredStudents": 120},
#             {"courseSemesterId": 102, "totalSemesterSessions": 15, "registeredStudents": 70},
#             {"courseSemesterId": 103, "totalSemesterSessions": 15, "registeredStudents": 150},
#             {"courseSemesterId": 104, "totalSemesterSessions": 5, "registeredStudents": 90},
#             {"courseSemesterId": 105, "totalSemesterSessions": 15, "registeredStudents": 40},
#             {"courseSemesterId": 201, "totalSemesterSessions": 15, "registeredStudents": 180},
#             {"courseSemesterId": 202, "totalSemesterSessions": 10, "registeredStudents": 55},
#             {"courseSemesterId": 203, "totalSemesterSessions": 15, "registeredStudents": 100},
#             {"courseSemesterId": 204, "totalSemesterSessions": 8, "registeredStudents": 60},
#             {"courseSemesterId": 205, "totalSemesterSessions": 12, "registeredStudents": 30},
#             {"courseSemesterId": 301, "totalSemesterSessions": 15, "registeredStudents": 200},
#             {"courseSemesterId": 302, "totalSemesterSessions": 15, "registeredStudents": 130},
#             {"courseSemesterId": 303, "totalSemesterSessions": 15, "registeredStudents": 75},
#             {"courseSemesterId": 304, "totalSemesterSessions": 7, "registeredStudents": 45},
#             {"courseSemesterId": 305, "totalSemesterSessions": 14, "registeredStudents": 95}
#         ],
#         "lecturers": [
#             {"userId": 1, "departmentId": 10, "teachingCourses": [101, 102, 205]},
#             {"userId": 2, "departmentId": 10, "teachingCourses": [101, 103, 201, 301]},
#             {"userId": 3, "departmentId": 20, "teachingCourses": [102, 104, 202, 203, 303]},
#             {"userId": 4, "departmentId": 20, "teachingCourses": [104, 204, 302, 304, 305]},
#             {"userId": 5, "departmentId": 10, "teachingCourses": [103, 201, 202, 305]},
#             {"userId": 6, "departmentId": 30, "teachingCourses": [105, 203, 204, 301, 302]},
#             {"userId": 7, "departmentId": 30, "teachingCourses": [101, 303, 304, 305]},
#             {"userId": 8, "departmentId": 10, "teachingCourses": [102, 104, 201, 205, 302]},
#             {"userId": 9, "departmentId": 20, "teachingCourses": [103, 202, 203, 301, 304]},
#             {"userId": 10, "departmentId": 30, "teachingCourses": [105, 304, 303, 305]},
#             {"userId": 11, "departmentId": 30, "teachingCourses": [301, 103, 303, 305]},
#             {"userId": 12, "departmentId": 30, "teachingCourses": [105, 301, 204, 305]}
#         ],
#         "rooms": [
#             {"roomNumber": "A1-101", "buildingName": "A1", "floor": "1", "capacity": 60},
#             {"roomNumber": "A1-102", "buildingName": "A1", "floor": "1", "capacity": 40},
#             {"roomNumber": "A1-201", "buildingName": "A1", "floor": "2", "capacity": 50},
#             {"roomNumber": "A1-202", "buildingName": "A1", "floor": "2", "capacity": 50},
#             {"roomNumber": "A1-203", "buildingName": "A1", "floor": "2", "capacity": 50},
#             {"roomNumber": "A1-204", "buildingName": "A1", "floor": "2", "capacity": 50},
#             {"roomNumber": "A1-205", "buildingName": "A1", "floor": "2", "capacity": 50},
#             {"roomNumber": "A1-202", "buildingName": "A1", "floor": "2", "capacity": 30, "roomType": "LAB"},
#             {"roomNumber": "B2-101", "buildingName": "B2", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL"},
#             {"roomNumber": "B2-102", "buildingName": "B2", "floor": "1", "capacity": 80},
#             {"roomNumber": "B2-201", "buildingName": "B2", "floor": "2", "capacity": 45},
#             {"roomNumber": "C1-301", "buildingName": "C1", "floor": "3", "capacity": 70},
#             {"roomNumber": "C1-302", "buildingName": "C1", "floor": "3", "capacity": 35, "roomType": "LAB"},
#             {"roomNumber": "D3-401", "buildingName": "D3", "floor": "4", "capacity": 100, "roomType": "LECTURE_HALL"},
#             {"roomNumber": "D3-402", "buildingName": "D3", "floor": "4", "capacity": 50},
#             {"roomNumber": "E1-105", "buildingName": "E1", "floor": "1", "capacity": 25, "roomType": "LAB"}
#         ],
#         "timeSlots": [
#             {"startTime": "07:00", "endTime": "08:50", "shift": 1},
#             {"startTime": "09:00", "endTime": "10:50", "shift": 2},
#             {"startTime": "11:00", "endTime": "12:50", "shift": 3},
#             {"startTime": "13:30", "endTime": "15:20", "shift": 4},
#         ],
#         "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
#         "maxSessionsPerLecturerConstraint": None
#     }
#     try:
#         input_dto_obj = ScheduleInputDTO(**input_data_dict)
#         logger.info("Input DTO created successfully for test endpoint.")
#         cp_schedule_result = await ScheduleService.calculate_with_cp(input_dto_obj)
#         logger.info("Schedule calculation completed for test endpoint.")
#         return cp_schedule_result
#     except ValidationError as ve: 
#         logger.error(f"Input data validation error: {ve.errors()}", exc_info=False)
#         raise HTTPException(status_code=422, detail=ve.errors())
#     except HTTPException as he: 
#         logger.error(f"HTTPException from service: Status {he.status_code}, Detail: {he.detail}", exc_info=False)
#         raise he
#     except Exception as e: 
#         logger.critical(f"CRITICAL UNHANDLED EXCEPTION in /calculating_test: {type(e).__name__} - {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"A critical server error occurred: {str(e)}")
    
# @router.get("/calculating_test_large", 
#             response_model=ScheduleResultDTO,
#             summary="Calculate schedule with FIXED LARGE test data",
#             description="Uses a fixed internal larger dataset to test the scheduling algorithm with more courses.") 
# async def calculating_schedule_fixed_test_large():
#     # --- DỮ LIỆU FIX CỨNG LỚN HƠN ---
#     course_semesters_data = [
#         # Khoa Công nghệ Thông tin
#         {"courseSemesterId": 1001, "totalSemesterSessions": 15, "registeredStudents": 120, "name": "Nhập môn Lập trình"},
#         {"courseSemesterId": 1002, "totalSemesterSessions": 15, "registeredStudents": 110, "name": "Cấu trúc Dữ liệu & Giải thuật"},
#         {"courseSemesterId": 1003, "totalSemesterSessions": 15, "registeredStudents": 100, "name": "Lập trình Hướng đối tượng"},
#         {"courseSemesterId": 1004, "totalSemesterSessions": 10, "registeredStudents": 90, "name": "Cơ sở Dữ liệu"},
#         {"courseSemesterId": 1005, "totalSemesterSessions": 10, "registeredStudents": 80, "name": "Mạng Máy tính"},
#         {"courseSemesterId": 1006, "totalSemesterSessions": 15, "registeredStudents": 70, "name": "Phát triển Web"}, # Cần 2 buổi/tuần nếu muốn xong sớm
#         {"courseSemesterId": 1007, "totalSemesterSessions": 12, "registeredStudents": 60, "name": "An toàn Thông tin"},
#         {"courseSemesterId": 1008, "totalSemesterSessions": 15, "registeredStudents": 50, "name": "Trí tuệ Nhân tạo"},
#         {"courseSemesterId": 1009, "totalSemesterSessions": 8, "registeredStudents": 40, "name": "Kiểm thử Phần mềm"},
#         {"courseSemesterId": 1010, "totalSemesterSessions": 15, "registeredStudents": 130, "name": "Đồ án Cơ sở ngành CNTT"},

#         # Khoa Kinh tế
#         {"courseSemesterId": 2001, "totalSemesterSessions": 15, "registeredStudents": 150, "name": "Kinh tế Vi mô"},
#         {"courseSemesterId": 2002, "totalSemesterSessions": 15, "registeredStudents": 140, "name": "Kinh tế Vĩ mô"},
#         {"courseSemesterId": 2003, "totalSemesterSessions": 10, "registeredStudents": 100, "name": "Nguyên lý Kế toán"},
#         {"courseSemesterId": 2004, "totalSemesterSessions": 12, "registeredStudents": 90, "name": "Marketing Căn bản"},
#         {"courseSemesterId": 2005, "totalSemesterSessions": 15, "registeredStudents": 80, "name": "Quản trị Học"},
#         {"courseSemesterId": 2006, "totalSemesterSessions": 10, "registeredStudents": 70, "name": "Tài chính Doanh nghiệp"},
#         {"courseSemesterId": 2007, "totalSemesterSessions": 15, "registeredStudents": 160, "name": "Luật Kinh tế"},
#         {"courseSemesterId": 2008, "totalSemesterSessions": 8, "registeredStudents": 50, "name": "Kinh tế Lượng"},
#         {"courseSemesterId": 2009, "totalSemesterSessions": 15, "registeredStudents": 60, "name": "Thương mại Điện tử"},
#         {"courseSemesterId": 2010, "totalSemesterSessions": 15, "registeredStudents": 100, "name": "Đồ án chuyên ngành Kinh tế"},

#         # Khoa Ngoại ngữ
#         {"courseSemesterId": 3001, "totalSemesterSessions": 15, "registeredStudents": 50, "name": "Tiếng Anh Cơ bản 1"},
#         {"courseSemesterId": 3002, "totalSemesterSessions": 15, "registeredStudents": 50, "name": "Tiếng Anh Cơ bản 2"},
#         {"courseSemesterId": 3003, "totalSemesterSessions": 15, "registeredStudents": 40, "name": "Ngữ âm Thực hành"},
#         {"courseSemesterId": 3004, "totalSemesterSessions": 10, "registeredStudents": 35, "name": "Văn hóa Anh-Mỹ"},
#         {"courseSemesterId": 3005, "totalSemesterSessions": 15, "registeredStudents": 30, "name": "Dịch Thuật Tổng quát"},
#         {"courseSemesterId": 3006, "totalSemesterSessions": 12, "registeredStudents": 25, "name": "Tiếng Anh Thương mại"},
#         {"courseSemesterId": 3007, "totalSemesterSessions": 15, "registeredStudents": 45, "name": "Tiếng Nhật Sơ cấp 1"},
#         {"courseSemesterId": 3008, "totalSemesterSessions": 15, "registeredStudents": 40, "name": "Tiếng Nhật Sơ cấp 2"},
#         {"courseSemesterId": 3009, "totalSemesterSessions": 10, "registeredStudents": 30, "name": "Văn hóa Nhật Bản"},
#         {"courseSemesterId": 3010, "totalSemesterSessions": 15, "registeredStudents": 20, "name": "Phiên dịch Anh-Việt"},
#         # Thêm khoảng 70 môn nữa để đủ 100
#     ]
#     # Tạo thêm môn học giả định để đủ 100
#     current_max_course_id = 3010
#     num_existing_courses = len(course_semesters_data)
#     num_to_generate_more = 100 - num_existing_courses

#     for i in range(num_to_generate_more):
#         current_max_course_id +=1
#         dept_prefix = random.choice([4,5,6]) # Các khoa giả định
#         course_semesters_data.append({
#             "courseSemesterId": int(f"{dept_prefix}0{i:02d}"), # Tạo ID có vẻ thực tế
#             "totalSemesterSessions": random.choice([8, 10, 12, 15]),
#             "registeredStudents": random.randint(20, 150)
#         })


#     lecturers_data = [
#         # Giảng viên Khoa CNTT
#         {"userId": 1, "departmentId": 1, "teachingCourses": [1001, 1002, 1005]},
#         {"userId": 2, "departmentId": 1, "teachingCourses": [1001, 1003, 1004, 1006]},
#         {"userId": 3, "departmentId": 1, "teachingCourses": [1002, 1007, 1008, 1009]},
#         {"userId": 4, "departmentId": 1, "teachingCourses": [1004, 1005, 1006, 1010]},
#         {"userId": 13, "departmentId": 1, "teachingCourses": [1001, 1008, 1009, 1003]},


#         # Giảng viên Khoa Kinh tế
#         {"userId": 5, "departmentId": 2, "teachingCourses": [2001, 2002, 2005]},
#         {"userId": 6, "departmentId": 2, "teachingCourses": [2001, 2003, 2004, 2006]},
#         {"userId": 7, "departmentId": 2, "teachingCourses": [2002, 2007, 2008, 2009]},
#         {"userId": 8, "departmentId": 2, "teachingCourses": [2004, 2005, 2006, 2010]},
#         {"userId": 14, "departmentId": 2, "teachingCourses": [2001, 2008, 2009, 2003]},

#         # Giảng viên Khoa Ngoại ngữ
#         {"userId": 9, "departmentId": 3, "teachingCourses": [3001, 3002, 3003, 3005]},
#         {"userId": 10, "departmentId": 3, "teachingCourses": [3001, 3004, 3006, 3010]},
#         {"userId": 11, "departmentId": 3, "teachingCourses": [3007, 3008, 3009]},
#         {"userId": 12, "departmentId": 3, "teachingCourses": [3002, 3005, 3007, 3010]},
#         {"userId": 15, "departmentId": 3, "teachingCourses": [3001, 3008, 3003, 3004]},

#         # Thêm giảng viên cho các khoa giả định (4, 5, 6)
#         {"userId": 16, "departmentId": 4, "teachingCourses": []},
#         {"userId": 17, "departmentId": 4, "teachingCourses": []},
#         {"userId": 18, "departmentId": 5, "teachingCourses": []},
#         {"userId": 19, "departmentId": 5, "teachingCourses": []},
#         {"userId": 20, "departmentId": 6, "teachingCourses": []},
#         {"userId": 21, "departmentId": 6, "teachingCourses": []},
#     ]

#     # Phân công các môn học mới cho giảng viên (đảm bảo mỗi môn có GV và phân bổ thêm)
#     all_course_ids = [cs["courseSemesterId"] for cs in course_semesters_data]
#     num_lecturers = len(lecturers_data)
#     for course_id in all_course_ids:
#         is_assigned = any(course_id in lecturer["teachingCourses"] for lecturer in lecturers_data)
#         if not is_assigned:
#             # Gán cho giảng viên thuộc khoa tương ứng nếu có thể, hoặc ngẫu nhiên
#             dept_prefix_course = int(str(course_id)[0])
#             potential_lecturers_for_course = [
#                 idx for idx, lect in enumerate(lecturers_data) 
#                 if lect["departmentId"] == dept_prefix_course or random.random() < 0.3 # 30% chance gán cho GV khoa khác
#             ]
#             if not potential_lecturers_for_course: # Nếu không có GV khoa đó, gán ngẫu nhiên
#                 potential_lecturers_for_course = list(range(num_lecturers))
            
#             lecturer_idx_to_assign = random.choice(potential_lecturers_for_course)
#             if course_id not in lecturers_data[lecturer_idx_to_assign]["teachingCourses"]:
#                  lecturers_data[lecturer_idx_to_assign]["teachingCourses"].append(course_id)
    
#     # Đảm bảo mỗi giảng viên có ít nhất một vài môn để dạy (nếu họ chưa có)
#     for i in range(num_lecturers):
#         if not lecturers_data[i]["teachingCourses"]:
#             num_courses_to_assign_gv = random.randint(2,5)
#             for _ in range(num_courses_to_assign_gv):
#                 course_to_assign = random.choice(all_course_ids)
#                 # Chỉ gán nếu GV đó thuộc khoa của môn học đó, hoặc với một xác suất nhỏ
#                 course_dept_prefix = int(str(course_to_assign)[0])
#                 if lecturers_data[i]["departmentId"] == course_dept_prefix or random.random() < 0.1:
#                     if course_to_assign not in lecturers_data[i]["teachingCourses"]:
#                          lecturers_data[i]["teachingCourses"].append(course_to_assign)


#     rooms_data = [
#         # Phòng học thường
#         {"roomNumber": "A101", "buildingName": "A", "floor": "1", "capacity": 60},
#         {"roomNumber": "A102", "buildingName": "A", "floor": "1", "capacity": 40},
#         {"roomNumber": "A201", "buildingName": "A", "floor": "2", "capacity": 50},
#         {"roomNumber": "A202", "buildingName": "A", "floor": "2", "capacity": 50},
#         {"roomNumber": "A203", "buildingName": "A", "floor": "2", "capacity": 50},
#         {"roomNumber": "A301", "buildingName": "A", "floor": "3", "capacity": 60},
#         {"roomNumber": "A302", "buildingName": "A", "floor": "3", "capacity": 40},

#         # Giảng đường
#         {"roomNumber": "B101-GH", "buildingName": "B", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL"},
#         {"roomNumber": "B102-GH", "buildingName": "B", "floor": "1", "capacity": 150, "roomType": "LECTURE_HALL"},
#         {"roomNumber": "B201-GH", "buildingName": "B", "floor": "2", "capacity": 180, "roomType": "LECTURE_HALL"},


#         # Phòng thường tòa C
#         {"roomNumber": "C101", "buildingName": "C", "floor": "1", "capacity": 70},
#         {"roomNumber": "C102", "buildingName": "C", "floor": "1", "capacity": 70},
#         {"roomNumber": "C201", "buildingName": "C", "floor": "2", "capacity": 80},
#         {"roomNumber": "C202", "buildingName": "C", "floor": "2", "capacity": 80},
#         {"roomNumber": "C301", "buildingName": "C", "floor": "3", "capacity": 50},

#         # Giảng đường lớn tòa D
#         {"roomNumber": "D401-GH", "buildingName": "D", "floor": "4", "capacity": 200, "roomType": "LECTURE_HALL"},
#         {"roomNumber": "D402-GH", "buildingName": "D", "floor": "4", "capacity": 100, "roomType": "LECTURE_HALL"},

#         # Phòng Lab
#         {"roomNumber": "Lab-IT1", "buildingName": "L", "floor": "1", "capacity": 40, "roomType": "LAB"},
#         {"roomNumber": "Lab-IT2", "buildingName": "L", "floor": "1", "capacity": 40, "roomType": "LAB"},
#         {"roomNumber": "Lab-IT3", "buildingName": "L", "floor": "2", "capacity": 30, "roomType": "LAB"},
#         {"roomNumber": "Lab-Eng1", "buildingName": "L", "floor": "2", "capacity": 25, "roomType": "LAB"}, # Phòng lab ngoại ngữ
#         {"roomNumber": "Lab-Eco1", "buildingName": "L", "floor": "3", "capacity": 35, "roomType": "LAB"}, # Phòng lab kinh tế
#     ]
#     # Thêm 10 phòng học thường nữa
#     for i in range(1, 11):
#         rooms_data.append(
#             {"roomNumber": f"TC-{i:02d}", "buildingName": "TC", "floor": str(random.randint(1,4)), 
#              "capacity": random.choice([40, 50, 60, 70]), "roomType": "CLASSROOM"}
#         )
#     # Thêm 2 giảng đường nữa
#     rooms_data.append({"roomNumber": "GH-X1", "buildingName": "X", "floor": "1", "capacity": 100, "roomType": "LECTURE_HALL"})
#     rooms_data.append({"roomNumber": "GH-X2", "buildingName": "X", "floor": "1", "capacity": 120, "roomType": "LECTURE_HALL"})


#     input_data_dict = {
#         "semesterStartDate": "2024-09-02",
#         "semesterEndDate": "2025-01-19", # 20 tuần
#         "courseSemesters": course_semesters_data,
#         "lecturers": lecturers_data,
#         "rooms": rooms_data,
#         "timeSlots": [ 
#             {"startTime": "07:00", "endTime": "08:50", "shift": 1}, # Ca 1
#             {"startTime": "09:00", "endTime": "10:50", "shift": 2}, # Ca 2
#             {"startTime": "13:30", "endTime": "15:20", "shift": 3}, # Ca 3
#             {"startTime": "15:30", "endTime": "17:20", "shift": 4}, # Ca 4
#         ],
#         "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
#         "maxSessionsPerLecturerConstraint": None, # Để thuật toán tự do hơn
#         "solverTimeLimitSeconds": 180.0,  # Tăng thời gian cho dữ liệu lớn
#         "objectiveStrategy": "BALANCE_LOAD_AND_EARLY_START", 
#         "penaltyWeightFixedDayShiftViolation": 100000, # Phạt rất nặng nếu vi phạm ngày/ca cố định
#         "maxSessionsPerWeekAllowed": 2 # Cho phép tối đa 2 buổi/tuần nếu cần để giãn lịch
#     }
#     try:
#         input_dto_obj = ScheduleInputDTO(**input_data_dict)
#         logger.info(f"Input DTO created for LARGE test endpoint with {len(input_dto_obj.courseSemesters)} courses, {len(input_dto_obj.lecturers)} lecturers, {len(input_dto_obj.rooms)} rooms.")
#         cp_schedule_result = await ScheduleService.calculate_with_cp(input_dto_obj)
#         logger.info("Schedule calculation completed for LARGE test endpoint.")
#         return cp_schedule_result
#     except ValidationError as ve: 
#         logger.error(f"Input data validation error (LARGE TEST): {ve.errors()}", exc_info=False)
#         raise HTTPException(status_code=422, detail=ve.errors())
#     except HTTPException as he: 
#         logger.error(f"HTTPException from service (LARGE TEST): Status {he.status_code}, Detail: {he.detail}", exc_info=False)
#         raise he
#     except Exception as e: 
#         logger.critical(f"CRITICAL UNHANDLED EXCEPTION in /calculating_test_large: {type(e).__name__} - {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"A critical server error occurred: {str(e)}")
    
# @router.post("/calculating", response_model=ScheduleResultDTO)
# async def calculate_schedule_endpoint_post(input_data_dict: ScheduleInputDTO):
#     try:
#         input_dto_obj = input_data_dict
#         logger.info("Input DTO created successfully for test endpoint.")
#         cp_schedule_result = await ScheduleService.calculate_with_cp(input_dto_obj)
#         logger.info("Schedule calculation completed for test endpoint.")
#         return cp_schedule_result
#     except ValidationError as ve: 
#         logger.error(f"Input data validation error: {ve.errors()}", exc_info=False)
#         raise HTTPException(status_code=422, detail=ve.errors())
#     except HTTPException as he: 
#         logger.error(f"HTTPException from service: Status {he.status_code}, Detail: {he.detail}", exc_info=False)
#         raise he
#     except Exception as e: 
#         logger.critical(f"CRITICAL UNHANDLED EXCEPTION in /calculating_test: {type(e).__name__} - {str(e)}", exc_info=True)
#         raise HTTPException(status_code=500, detail=f"A critical server error occurred: {str(e)}")
    


# @router.get("/calculating_test_sequential", response_model=ScheduleResultDTO)
# async def calculating_schedule_test_sequential_endpoint():
#     endpoint_logger = logging.getLogger(f"{__name__}.calculating_schedule_test_sequential_endpoint")
#     endpoint_logger.info("Starting sequential scheduling test from main app...")
#     start_overall_time = time.time()

#     # Trong hàm calculating_schedule_test_sequential_endpoint():

#     full_input_data_dict = {
#       "semesterStartDate": "2024-09-02", 
#       "semesterEndDate": "2025-01-26", # Kéo dài học kỳ ra 21 tuần
#       "courseSemesters": [
#         # Khoa 10 (Giả định csId từ 1000-1049)
#         {"courseSemesterId": 1001, "credits": 3, "totalSemesterSessions": 15, "registeredStudents": 120},
#         {"courseSemesterId": 1002, "credits": 2, "totalSemesterSessions": 20, "registeredStudents": 70}, # nhiều buổi hơn
#         {"courseSemesterId": 1003, "credits": 4, "totalSemesterSessions": 30, "registeredStudents": 150},
#         {"courseSemesterId": 1004, "credits": 1, "totalSemesterSessions": 10, "registeredStudents": 90}, # nhiều buổi hơn
#         {"courseSemesterId": 1005, "credits": 3, "totalSemesterSessions": 15, "registeredStudents": 40},
#         {"courseSemesterId": 1006, "credits": 2, "totalSemesterSessions": 10, "registeredStudents": 80},
#         {"courseSemesterId": 1007, "credits": 3, "totalSemesterSessions": 12, "registeredStudents": 60},
#         {"courseSemesterId": 1008, "credits": 4, "totalSemesterSessions": 28, "registeredStudents": 130},
#         {"courseSemesterId": 1009, "credits": 1, "totalSemesterSessions": 7, "registeredStudents": 50},
#         {"courseSemesterId": 1010, "credits": 3, "totalSemesterSessions": 14, "registeredStudents": 100},
#         {"courseSemesterId": 1011, "credits": 2, "totalSemesterSessions": 15, "registeredStudents": 65},
#         {"courseSemesterId": 1012, "credits": 3, "totalSemesterSessions": 10, "registeredStudents": 30},
#         {"courseSemesterId": 1013, "credits": 4, "totalSemesterSessions": 20, "registeredStudents": 110},
#         {"courseSemesterId": 1014, "credits": 1, "totalSemesterSessions": 6, "registeredStudents": 40},
#         {"courseSemesterId": 1015, "credits": 3, "totalSemesterSessions": 18, "registeredStudents": 95},
#         {"courseSemesterId": 1016, "credits": 2, "totalSemesterSessions": 12, "registeredStudents": 50},
#         {"courseSemesterId": 1017, "credits": 3, "totalSemesterSessions": 15, "registeredStudents": 140},
#         {"courseSemesterId": 1018, "credits": 4, "totalSemesterSessions": 25, "registeredStudents": 100},
#         {"courseSemesterId": 1019, "credits": 1, "totalSemesterSessions": 8, "registeredStudents": 70},
#         {"courseSemesterId": 1020, "credits": 3, "totalSemesterSessions": 10, "registeredStudents": 25},
#         {"courseSemesterId": 1021, "credits": 2, "totalSemesterSessions": 16, "registeredStudents": 85},
#         {"courseSemesterId": 1022, "credits": 3, "totalSemesterSessions": 12, "registeredStudents": 45},
#         {"courseSemesterId": 1023, "credits": 4, "totalSemesterSessions": 22, "registeredStudents": 125},
#         {"courseSemesterId": 1024, "credits": 1, "totalSemesterSessions": 9, "registeredStudents": 55},
#         {"courseSemesterId": 1025, "credits": 3, "totalSemesterSessions": 13, "registeredStudents": 35},

#         # Khoa 20 (Giả định csId từ 2000-2049)
#         {"courseSemesterId": 2001, "credits": 3, "totalSemesterSessions": 15, "registeredStudents": 110},
#         {"courseSemesterId": 2002, "credits": 2, "totalSemesterSessions": 18, "registeredStudents": 60},
#         {"courseSemesterId": 2003, "credits": 4, "totalSemesterSessions": 30, "registeredStudents": 160},
#         {"courseSemesterId": 2004, "credits": 1, "totalSemesterSessions": 11, "registeredStudents": 80},
#         {"courseSemesterId": 2005, "credits": 3, "totalSemesterSessions": 15, "registeredStudents": 50},
#         {"courseSemesterId": 2006, "credits": 2, "totalSemesterSessions": 10, "registeredStudents": 90},
#         {"courseSemesterId": 2007, "credits": 3, "totalSemesterSessions": 13, "registeredStudents": 70},
#         {"courseSemesterId": 2008, "credits": 4, "totalSemesterSessions": 26, "registeredStudents": 140},
#         {"courseSemesterId": 2009, "credits": 1, "totalSemesterSessions": 6, "registeredStudents": 60},
#         {"courseSemesterId": 2010, "credits": 3, "totalSemesterSessions": 16, "registeredStudents": 110},
#         {"courseSemesterId": 2011, "credits": 2, "totalSemesterSessions": 14, "registeredStudents": 75},
#         {"courseSemesterId": 2012, "credits": 3, "totalSemesterSessions": 11, "registeredStudents": 35},
#         {"courseSemesterId": 2013, "credits": 4, "totalSemesterSessions": 24, "registeredStudents": 100},
#         {"courseSemesterId": 2014, "credits": 1, "totalSemesterSessions": 7, "registeredStudents": 40},
#         {"courseSemesterId": 2015, "credits": 3, "totalSemesterSessions": 17, "registeredStudents": 85},
#         {"courseSemesterId": 2016, "credits": 2, "totalSemesterSessions": 13, "registeredStudents": 55},
#         {"courseSemesterId": 2017, "credits": 3, "totalSemesterSessions": 15, "registeredStudents": 150},
#         {"courseSemesterId": 2018, "credits": 4, "totalSemesterSessions": 27, "registeredStudents": 120},
#         {"courseSemesterId": 2019, "credits": 1, "totalSemesterSessions": 9, "registeredStudents": 75},
#         {"courseSemesterId": 2020, "credits": 3, "totalSemesterSessions": 11, "registeredStudents": 30},
#         {"courseSemesterId": 2021, "credits": 2, "totalSemesterSessions": 17, "registeredStudents": 95},
#         {"courseSemesterId": 2022, "credits": 3, "totalSemesterSessions": 13, "registeredStudents": 50},
#         {"courseSemesterId": 2023, "credits": 4, "totalSemesterSessions": 23, "registeredStudents": 135},
#         {"courseSemesterId": 2024, "credits": 1, "totalSemesterSessions": 10, "registeredStudents": 65},
#         {"courseSemesterId": 2025, "credits": 3, "totalSemesterSessions": 14, "registeredStudents": 40}
#       ],
#       "lecturers": [ # Tăng số lượng GV và phân bổ lại môn
#             {"userId": 1, "departmentId": 10, "teachingCourses": [1001, 1002, 1005, 2007]},
#             {"userId": 2, "departmentId": 10, "teachingCourses": [1001, 1003, 1006, 1010, 2011]},
#             {"userId": 3, "departmentId": 10, "teachingCourses": [1002, 1004, 1007, 1011, 2015]},
#             {"userId": 4, "departmentId": 10, "teachingCourses": [1003, 1008, 1012, 1016, 2020]},
#             {"userId": 5, "departmentId": 10, "teachingCourses": [1004, 1009, 1013, 1017, 1021, 2001]}, # GV liên khoa
#             {"userId": 6, "departmentId": 10, "teachingCourses": [1014, 1018, 1022, 1023, 1024, 2005]}, # GV liên khoa
#             {"userId": 7, "departmentId": 10, "teachingCourses": [1015, 1019, 1020, 1025, 2010]},

#             {"userId": 11, "departmentId": 20, "teachingCourses": [2001, 2002, 2005, 1007]}, # GV liên khoa
#             {"userId": 12, "departmentId": 20, "teachingCourses": [2001, 2003, 2006, 2010, 1011]}, # GV liên khoa
#             {"userId": 13, "departmentId": 20, "teachingCourses": [2002, 2004, 2007, 2011, 1015]}, # GV liên khoa
#             {"userId": 14, "departmentId": 20, "teachingCourses": [2003, 2008, 2012, 2016, 1020]},
#             {"userId": 15, "departmentId": 20, "teachingCourses": [2004, 2009, 2013, 2017, 2021]},
#             {"userId": 16, "departmentId": 20, "teachingCourses": [2014, 2018, 2022, 2023, 2024]},
#             {"userId": 17, "departmentId": 20, "teachingCourses": [2015, 2019, 2020, 2025, 1004]}, # GV liên khoa

#             {"userId": 20, "departmentId": 10, "teachingCourses": [1025]},
#             {"userId": 21, "departmentId": 20, "teachingCourses": [2024]}
#       ],
#       "rooms": [  
#             {"roomNumber": "A1-101", "buildingName": "A1", "floor": "1", "capacity": 60, "isShared": False, "owningDepartmentId": 10},
#             {"roomNumber": "A1-102", "buildingName": "A1", "floor": "1", "capacity": 40, "isShared": False, "owningDepartmentId": 10},
#             {"roomNumber": "A1-201", "buildingName": "A1", "floor": "2", "capacity": 50, "isShared": True}, # Phòng chung
#             {"roomNumber": "A1-202", "buildingName": "A1", "floor": "2", "capacity": 30, "roomType": "LAB", "isShared": True},
#             {"roomNumber": "B2-101", "buildingName": "B2", "floor": "1", "capacity": 150, "roomType": "LECTURE_HALL", "isShared": True}, # Tăng sức chứa
#             {"roomNumber": "B2-102", "buildingName": "B2", "floor": "1", "capacity": 90, "isShared": True}, # Phòng chung
#             {"roomNumber": "B2-201", "buildingName": "B2", "floor": "2", "capacity": 45, "isShared": False, "owningDepartmentId": 20},
#             {"roomNumber": "C1-301", "buildingName": "C1", "floor": "3", "capacity": 70, "isShared": True},
#             {"roomNumber": "C1-302", "buildingName": "C1", "floor": "3", "capacity": 35, "roomType": "LAB", "isShared": True},
#             {"roomNumber": "D3-401", "buildingName": "D3", "floor": "4", "capacity": 100, "roomType": "LECTURE_HALL", "isShared": True },
#             {"roomNumber": "D3-402", "buildingName": "D3", "floor": "4", "capacity": 50, "isShared": False, "owningDepartmentId": 10 },
#             {"roomNumber": "E1-105", "buildingName": "E1", "floor": "1", "capacity": 25, "roomType": "LAB", "isShared": True},
#             {"roomNumber": "F1-101", "buildingName": "F1", "floor": "1", "capacity": 70, "isShared": False, "owningDepartmentId": 20},
#             {"roomNumber": "F1-102", "buildingName": "F1", "floor": "1", "capacity": 50, "isShared": True}
#       ],
#       "timeSlots": [
#         {"startTime": "07:00", "endTime": "08:50", "shift": 1},
#         {"startTime": "09:00", "endTime": "10:50", "shift": 2},
#         {"startTime": "11:00", "endTime": "12:50", "shift": 3},
#         {"startTime": "13:30", "endTime": "15:20", "shift": 4},
#       ],
#       "days": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"],
#       "maxSessionsPerLecturerConstraint": 25, 
#       "solverTimeLimitSeconds": 120.0, # Tăng thời gian cho mỗi khoa
#       "objectiveStrategy": "BALANCE_LOAD_AND_EARLY_START", 
#       "maxSessionsPerWeekAllowed": 3,
#       "penaltyWeightFixedDayShiftViolation": 1000 # Giảm nhẹ penalty để linh hoạt hơn
#     }

#     # --- Phân chia khoa và GV (ví dụ) ---
#     # Key là departmentId, value là list các courseSemesterId chỉ thuộc khoa đó (không tính liên khoa ở đây)
#     department_exclusive_courses_map = {
#         10: [cs["courseSemesterId"] for cs in full_input_data_dict["courseSemesters"] if 1000 <= cs["courseSemesterId"] <= 1025],
#         20: [cs["courseSemesterId"] for cs in full_input_data_dict["courseSemesters"] if 2000 <= cs["courseSemesterId"] <= 2025],
#     }
    
#     # Xác định các môn liên khoa dựa trên GV (nếu GV dạy môn của nhiều khoa)
#     # Hoặc bạn có thể định nghĩa rõ các môn nào là liên khoa
#     # Tạm thời, chúng ta sẽ gán môn cho khoa dựa trên department_exclusive_courses_map
#     # và GV sẽ được lọc dựa trên khoa của GV và các môn họ dạy trong danh sách môn của khoa đó.

#     all_rooms_data = full_input_data_dict["rooms"]
#     department_order = [10, 20] # Chỉ test 2 khoa trước

#     final_combined_schedule: List[ScheduleEntryDTO] = []
#     final_combined_class_groups: List[ClassGroupOutputDTO] = []
#     final_combined_lecturer_loads_map: Dict[int, int] = {}
#     final_combined_violations: List[str] = []
#     final_combined_detailed_suggestions: List[ViolationDetailDTO] = []
#     master_occupied_slots: List[OccupiedSlotInfoDTO] = []

#     total_overall_duration = 0.0

#     for dept_id_to_schedule in department_order:
#         endpoint_logger.info(f"--- Preparing to schedule for Department ID: {dept_id_to_schedule} ---")
        
#         # Lọc courseSemesters cho khoa hiện tại
#         current_dept_course_ids = department_exclusive_courses_map.get(dept_id_to_schedule, [])
#         current_dept_courses_data = [
#             cs_data for cs_data in full_input_data_dict["courseSemesters"] 
#             if cs_data["courseSemesterId"] in current_dept_course_ids
#         ]

#         if not current_dept_courses_data:
#             endpoint_logger.info(f"No exclusive courses for Department ID {dept_id_to_schedule}. Skipping.")
#             continue

#         # Lọc lecturers: bao gồm GV của khoa đó VÀ GV có thể dạy các môn của khoa đó
#         relevant_lecturer_ids = set()
#         for lect_data in full_input_data_dict["lecturers"]:
#             if lect_data["departmentId"] == dept_id_to_schedule:
#                 relevant_lecturer_ids.add(lect_data["userId"])
#             for taught_cs_id in lect_data["teachingCourses"]:
#                 if taught_cs_id in current_dept_course_ids:
#                     relevant_lecturer_ids.add(lect_data["userId"])
#                     break # Chỉ cần một môn khớp là đủ để đưa GV vào
        
#         current_dept_lecturers_data = [
#             lect_data for lect_data in full_input_data_dict["lecturers"]
#             if lect_data["userId"] in relevant_lecturer_ids
#         ]
        
#         if not current_dept_lecturers_data:
#             endpoint_logger.warning(f"No relevant lecturers found for Department ID {dept_id_to_schedule}. Skipping.")
#             final_combined_violations.append(f"Skipped Dept {dept_id_to_schedule}: No relevant lecturers found.")
#             continue
        
#         # Lấy phòng của khoa (owningDepartmentId) + tất cả các phòng shared
#         current_dept_rooms_data = [
#             room_data for room_data in all_rooms_data
#             if room_data["isShared"] or room_data.get("owningDepartmentId") == dept_id_to_schedule
#         ]
#         if not current_dept_rooms_data:
#             endpoint_logger.warning(f"No specific or shared rooms for Dept {dept_id_to_schedule}. Using all rooms for this run (or skip).")
#             # Hoặc nếu không có phòng nào, không thể xếp lịch
#             final_combined_violations.append(f"Skipped Dept {dept_id_to_schedule}: No rooms available (specific or shared).")
#             continue


#         dept_input_payload = {
#             "semesterStartDate": full_input_data_dict["semesterStartDate"],
#             "semesterEndDate": full_input_data_dict["semesterEndDate"],
#             "courseSemesters": [CourseSemesterDTO(**cs).model_dump(exclude_none=True) for cs in current_dept_courses_data],
#             "lecturers": [LecturerDTO(**l).model_dump(exclude_none=True) for l in current_dept_lecturers_data],
#             "rooms": [RoomDTO(**r).model_dump(exclude_none=True) for r in current_dept_rooms_data], # Chỉ truyền phòng của khoa + shared
#             "timeSlots": [TimeSlotDTO(**ts).model_dump(exclude_none=True) for ts in full_input_data_dict["timeSlots"]],
#             "days": full_input_data_dict["days"],
#             "maxSessionsPerLecturerConstraint": full_input_data_dict["maxSessionsPerLecturerConstraint"],
#             "solverTimeLimitSeconds": full_input_data_dict["solverTimeLimitSeconds"],
#             "objectiveStrategy": full_input_data_dict["objectiveStrategy"],
#             "maxSessionsPerWeekAllowed": full_input_data_dict["maxSessionsPerWeekAllowed"],
#             "penaltyWeightFixedDayShiftViolation": full_input_data_dict["penaltyWeightFixedDayShiftViolation"],
#             "occupiedSlots": [s.model_dump() for s in master_occupied_slots]
#         }

#         try:
#             dept_input_dto = ScheduleInputDTO(**dept_input_payload)
#             endpoint_logger.info(f"Scheduling for Dept {dept_id_to_schedule} with {len(dept_input_dto.courseSemesters)} courses, "
#                                  f"{len(dept_input_dto.lecturers)} lecturers, {len(dept_input_dto.rooms)} rooms, "
#                                  f"{len(master_occupied_slots)} occupied slots.")
            
#             dept_result = await ScheduleService.calculate_with_cp(dept_input_dto)
#             total_overall_duration += dept_result.duration # Cộng dồn thời gian của từng service call
            
#             final_combined_schedule.extend(dept_result.schedule)
#             existing_cg_keys = {(cg.courseSemesterId, cg.groupNumber) for cg in final_combined_class_groups}
#             for cg_new in dept_result.classGroups:
#                 if (cg_new.courseSemesterId, cg_new.groupNumber) not in existing_cg_keys:
#                     final_combined_class_groups.append(cg_new)
#                     existing_cg_keys.add((cg_new.courseSemesterId, cg_new.groupNumber))
            
#             final_combined_violations.extend([f"[Dept {dept_id_to_schedule}] {v}" for v in dept_result.violations])
#             final_combined_detailed_suggestions.extend(dept_result.detailedSuggestions)

#             for ll_new in dept_result.lecturerLoad:
#                 final_combined_lecturer_loads_map[ll_new.lecturerId] = \
#                     final_combined_lecturer_loads_map.get(ll_new.lecturerId, 0) + ll_new.sessionsAssigned
            
#             for entry in dept_result.schedule:
#                 shift_val_occ = None
#                 try: shift_val_occ = int(entry.shift.replace("Ca", ""))
#                 except: endpoint_logger.warning(f"Could not parse shift value from schedule entry: {entry.shift}")
                
#                 if shift_val_occ is not None:
#                     # Chỉ thêm vào occupiedSlots nếu phòng đó là phòng dùng chung (isShared: True)
#                     # hoặc nếu phòng đó không thuộc sở hữu của khoa hiện tại (trường hợp hy hữu, nên kiểm tra)
#                     room_info = next((r for r in all_rooms_data if r["roomNumber"] == entry.room), None)
#                     if room_info and room_info["isShared"]:
#                         master_occupied_slots.append(OccupiedSlotInfoDTO(
#                             roomNumber=entry.room, semesterWeek=entry.semesterWeek,
#                             day=entry.day, shift=shift_val_occ
#                         ))
#             endpoint_logger.info(f"Dept {dept_id_to_schedule} done. Total sessions scheduled for dept: {len(dept_result.schedule)}. Total occupied slots now: {len(master_occupied_slots)}")

#         except Exception as dept_e:
#             endpoint_logger.error(f"Error scheduling Dept {dept_id_to_schedule}: {type(dept_e).__name__} - {str(dept_e)}", exc_info=True)
#             final_combined_violations.append(f"Failed to schedule Dept {dept_id_to_schedule}: {str(dept_e)}")
    
#     # --- Tính toán lại các giá trị tổng hợp cuối cùng ---
#     # ... (Giữ nguyên logic tính final_lect_load_list, final_load_diff)
#     final_lect_load_list = [LecturerLoadDTO(lecturerId=uid, sessionsAssigned=count) for uid, count in final_combined_lecturer_loads_map.items()]
#     final_load_diff = None
#     if final_lect_load_list:
#         loads = [l.sessionsAssigned for l in final_lect_load_list]
#         if loads: final_load_diff = max(loads) - min(loads) if loads else 0 # Thêm kiểm tra if loads else 0

#     # Tính các giá trị tổng của ScheduleResultDTO
#     # totalSemesterWeekSlots và totalAvailableRoomSlotsInSemester nên được tính từ input gốc
#     temp_start_date = date.fromisoformat(full_input_data_dict["semesterStartDate"])
#     temp_end_date = date.fromisoformat(full_input_data_dict["semesterEndDate"])
#     temp_total_semester_weeks = math.ceil(((temp_end_date - temp_start_date).days + 1) / 7)
#     temp_num_days = len(full_input_data_dict["days"])
#     temp_num_shifts = len(full_input_data_dict["timeSlots"])
#     temp_num_rooms = len(full_input_data_dict["rooms"]) # Tổng số phòng trong hệ thống
    
#     calculated_totalSemesterWeekSlots = temp_total_semester_weeks * temp_num_days * temp_num_shifts
#     calculated_totalAvailableRoomSlotsInSemester = calculated_totalSemesterWeekSlots * temp_num_rooms


#     # Tính lại lecturerPotentialLoad cho tất cả giảng viên dựa trên tất cả môn học
#     final_overall_lect_potential_load: Dict[int, int] = {}
#     # Tạo lại processed_courses cho toàn bộ input để tính potential load
#     all_processed_courses_for_potential_load: Dict[int, ProcessedCourseProps] = {}
#     max_room_capacity_for_potential_load = max(r["capacity"] for r in full_input_data_dict["rooms"]) if full_input_data_dict["rooms"] else 50


#     for cs_dto_data_pot in full_input_data_dict["courseSemesters"]:
#         # Tạo đối tượng DTO từ dict để dùng lại logic _get_sessions_per_week
#         cs_dto_obj_pot = CourseSemesterDTO(**cs_dto_data_pot)
#         sessions_p_week_pot, calc_total_wks_pot = ScheduleService._get_sessions_per_week(
#             cs_dto_obj_pot.totalSemesterSessions, 
#             temp_total_semester_weeks, # Sử dụng temp_total_semester_weeks
#             full_input_data_dict["maxSessionsPerWeekAllowed"],
#             cs_dto_obj_pot.courseSemesterId,
#             cs_dto_obj_pot.credits
#         )
#         all_processed_courses_for_potential_load[cs_dto_obj_pot.courseSemesterId] = ProcessedCourseProps(
#             cs_dto_obj_pot, 
#             sessions_p_week_pot, 
#             calc_total_wks_pot
#         )
    
#     for l_data_stat in full_input_data_dict["lecturers"]:
#         l_user_id_stat = l_data_stat["userId"]
#         load_stat = 0
#         for cs_id_teach_stat in l_data_stat["teachingCourses"]:
#             if cs_id_teach_stat in all_processed_courses_for_potential_load:
#                 course_p_stat = all_processed_courses_for_potential_load[cs_id_teach_stat]
                
#                 # Đếm số nhóm thực tế được tạo cho môn này từ final_combined_class_groups
#                 # Hoặc ước tính dựa trên desiredNumberOfGroups / max_room_capacity_overall nếu chưa có trong final_combined_class_groups
#                 num_grps_stat = sum(1 for cg_stat in final_combined_class_groups if cg_stat.courseSemesterId == cs_id_teach_stat)
                
#                 if num_grps_stat == 0 and course_p_stat.registered_students > 0 :
#                     original_cs_stat = next((cs for cs in full_input_data_dict["courseSemesters"] if cs["courseSemesterId"] == cs_id_teach_stat), None)
#                     desired_grps_stat = original_cs_stat.get("desiredNumberOfGroups") if original_cs_stat else None
                    
#                     if desired_grps_stat is not None:
#                         num_grps_stat = desired_grps_stat
#                     elif max_room_capacity_for_potential_load > 0 :
#                         num_grps_stat = math.ceil(course_p_stat.registered_students / max_room_capacity_for_potential_load)
#                     else:
#                         num_grps_stat = 1
#                     if num_grps_stat <=0 : num_grps_stat =1
                
#                 load_stat += course_p_stat.total_semester_sessions * num_grps_stat
#         final_overall_lect_potential_load[l_user_id_stat] = load_stat
        

#     overall_duration = time.time() - start_overall_time
#     endpoint_logger.info(f"Sequential scheduling test finished. Overall duration: {overall_duration:.2f}s")

#     return ScheduleResultDTO(
#         classGroups=final_combined_class_groups,
#         schedule=final_combined_schedule,
#         violations=final_combined_violations,
#         detailedSuggestions=final_combined_detailed_suggestions,
#         lecturerLoad=final_lect_load_list,
#         loadDifference=final_load_diff,
#         totalCourseSessionsToSchedule=len(final_combined_schedule), 
#         totalSemesterWeekSlots=calculated_totalSemesterWeekSlots,
#         totalAvailableRoomSlotsInSemester=calculated_totalAvailableRoomSlotsInSemester,
#         lecturerPotentialLoad=final_overall_lect_potential_load,
#         duration=overall_duration
#     )



