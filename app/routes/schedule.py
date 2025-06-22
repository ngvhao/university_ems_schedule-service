from datetime import date, timedelta
import logging
from typing import Annotated 
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from app.database import get_db
from app.services.class_weekly_schedule import ClassWeeklyScheduleService
from app.services.schedule import CourseSchedulingInfoDTO, ExistingScheduleRecord, FinalScheduleResultDTO,  LecturerInputDTO, OccupiedResourceSlotDTO,  RoomInputDTO, ScheduleInputDTO, ScheduleService, TimeSlotInputDTO
from app.utils.role_checker import check_role
from sqlalchemy.ext.asyncio import AsyncSession
import random

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedules")

def get_sessions_per_week(credits):
    if credits <= 2:
        return 1
    elif credits == 3:
        return 1 
    elif credits == 4:
        return 2
    elif credits >= 5:  
        return 2  
    return 1  

@router.get("/calculating")
async def test():
    sample_time_slots = [
        TimeSlotInputDTO(timeSlotId=1, shift=1),
        TimeSlotInputDTO(timeSlotId=2, shift=2),  
        TimeSlotInputDTO(timeSlotId=3, shift=3), 
        TimeSlotInputDTO(timeSlotId=4, shift=4),  
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
    sample_existing_schedules = [ExistingScheduleRecord(endDate="2024-12-20", startDate='2024-09-02', lecturerId=1, dayOfWeek="MONDAY", roomId=1, timeSlotId=1)]

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
        existingSchedules=sample_existing_schedules,
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

@router.post("/calculating")
async def make_schedule(body: Annotated[ScheduleInputDTO, Body(...)],  
    service: Annotated[ScheduleService, Depends(ScheduleService)],
    class_weekly_service: Annotated[ClassWeeklyScheduleService, Depends(ClassWeeklyScheduleService)],
    db: AsyncSession = Depends(get_db)
    ):
    service = ScheduleService()
    try:
        day_name_map_from_iso = {
            1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY", 4: "THURSDAY",
            5: "FRIDAY", 6: "SATURDAY", 7: "SUNDAY"
        }
        schedules = await class_weekly_service.get_class_weekly_schedules(body.semesterId, db)
        processed_schedules = []

        for schedule_obj in schedules:
            day_number = int(schedule_obj.day_of_week)
            dto = ExistingScheduleRecord(
                startDate=str(schedule_obj.start_date),
                endDate=str(schedule_obj.end_date),
                dayOfWeek=day_name_map_from_iso.get(day_number), 
                roomId=schedule_obj.room_id,
                lecturerId=schedule_obj.lecturer_id,
                timeSlotId=schedule_obj.time_slot_id
            )
            processed_schedules.append(dto)

            logging.info(f"[DEBUG-STEP-1] Processed DTO for existing schedule: {dto}")

        body.existingSchedules = processed_schedules
        result: FinalScheduleResultDTO = await service.calculate_with_cp(body) 

        logger.info("Scheduling finished.")
        logger.info(f"Solver Status: {result.solverStatus}")
        logger.info(f"Solver Message: {result.solverMessage}")
        logger.info(f"Duration: {result.solverDurationSeconds:.2f}s")
        logger.info(f"Semester ID: {result.semesterId}, From: {result.semesterStartDate}, To: {result.semesterEndDate}")
        logger.info(f"Total Original Sessions to Schedule: {result.totalOriginalSessionsToSchedule}")
        
        logger.info("\n--- Scheduled Courses ---")
        if not result.scheduledCourses:
            logger.info("No courses were scheduled.")
        else:
            for course_dto in result.scheduledCourses: 
                logger.info(f"\nCourse ID: {course_dto.courseId}")
                logger.info(f"  Total Registered Students for Course: {course_dto.totalRegisteredStudents}")
                logger.info(f"  Total Sessions for Course: {course_dto.totalSessionsForCourse}")         
                
                if not course_dto.scheduledClassGroups:
                    logger.info("  No class groups scheduled for this course.")
                else:
                    for group_dto in course_dto.scheduledClassGroups: # group_dto là ClassGroupScheduledDTO
                        logger.info(f"  Group Number: {group_dto.groupNumber}")
                        # logger.info(f"    Registered Students: {group_dto.registeredStudents} (Max: {group_dto.maxStudents})") # BỎ DÒNG NÀY
                        logger.info(f"    Max Students per Group: {group_dto.maxStudents}") # SỬA LẠI
                        logger.info(f"    Lecturer ID: {group_dto.lecturerId}")
                        logger.info(f"    Group Study Period: {group_dto.groupStartDate} to {group_dto.groupEndDate}")
                        logger.info(f"    Teaching Weeks: {group_dto.totalTeachingWeeksForGroup}, Sessions/Week: {group_dto.sessionsPerWeekForGroup}")
                        logger.info(f"    Weekly Schedule Details ({len(group_dto.weeklyScheduleDetails)} entries):")
                        if not group_dto.weeklyScheduleDetails:
                            logger.info("      No weekly schedule details found for this group.")
                        else:
                            for detail in group_dto.weeklyScheduleDetails:
                                logger.info(f"      - Day: {detail.dayOfWeek}, TimeSlotID: {detail.timeSlotId}, RoomID: {detail.roomId}")
        
        logger.info("\n--- Lecturer Load ---")
        if not result.lecturerLoad:
            logger.info("No lecturer load information available.")
        else:
            for load_info in result.lecturerLoad:
                logger.info(f"  Lecturer {load_info.lecturerId}: {load_info.sessionsAssigned} sessions assigned")
        
        if result.loadDifference is not None:
          logger.info(f"Load Difference (max - min): {result.loadDifference}")
        
        return result 

    except HTTPException as he:
        logger.error(f"HTTP Error {he.status_code}: {he.detail}")
        return JSONResponse(
            status_code=he.status_code,
            content={"detail": he.detail}
        )
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": "An unexpected error occurred while processing the schedule. Please try again later."}
        )