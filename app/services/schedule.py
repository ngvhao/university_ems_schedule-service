from datetime import date, timedelta 
from typing import Any, Dict, List, Optional, Tuple, Union, Literal 
from fastapi import HTTPException
from ortools.sat.python import cp_model
from pydantic import BaseModel, Field, field_validator, ValidationInfo  
import logging
import math
import time
from app.utils.constants import SOLVERTIMELIMITSECONDS
from app.utils.enums import EObjectStrategy, ERoomType

# --- Helper Functions  ---
def get_semester_week_and_day_indices(
    target_date: date, semester_start_date: date, days_of_week_map: Dict[str, int]
) -> Tuple[Optional[int], Optional[int]]:
    """
    Tính toán semester_week_index (0-based) và day_index (0-based theo days_of_week_map)
    cho một target_date dựa trên semester_start_date.
    Trả về (None, None) nếu target_date nằm ngoài học kỳ hoặc không khớp ngày trong tuần.
    """
    if target_date < semester_start_date:
        return None, None
    
    delta_days = (target_date - semester_start_date).days
    semester_week_index = delta_days // 7
    day_in_week_iso = target_date.isoweekday()  
    day_name_map_from_iso = {
        1: "MONDAY", 2: "TUESDAY", 3: "WEDNESDAY", 4: "THURSDAY",
        5: "FRIDAY", 6: "SATURDAY", 7: "SUNDAY"
    }
    target_day_name = day_name_map_from_iso.get(day_in_week_iso)
    
    if target_day_name and target_day_name in days_of_week_map:
        day_index = days_of_week_map[target_day_name]
        return semester_week_index, day_index
    return semester_week_index, None 

# --- DTOs for Input ---
class CourseSchedulingInfoDTO(BaseModel):
    courseId: int
    credits: int = Field(gt=0)
    totalSemesterSessions: int = Field(gt=0)  
    registeredStudents: int = Field(ge=0)    
    potentialLecturerIds: List[int]

class LecturerInputDTO(BaseModel):  
    lecturerId: int 
class RoomInputDTO(BaseModel):  
    id: int 
    roomNumber: str  
    capacity: int
    roomType: str = ERoomType.CLASSROOM

class TimeSlotInputDTO(BaseModel): 
    id: int  
    shift: int  

class ExistingScheduleRecord(BaseModel):
    roomId: int
    lecturerId: int
    timeSlotId: int  
    dayOfWeek: str   
    startDate: str  
    endDate: str

class OccupiedResourceSlotDTO(BaseModel):
    resourceType: Literal['room', 'lecturer']
    resourceId: Union[int, str]  
    date: str
    timeSlotId: int 

class ScheduleInputDTO(BaseModel):
    semesterId: int  
    semesterStartDate: str
    semesterEndDate: str
    coursesToSchedule: List[CourseSchedulingInfoDTO]
    lecturers: List[LecturerInputDTO]
    rooms: List[RoomInputDTO]
    timeSlots: List[TimeSlotInputDTO] 
    daysOfWeek: List[str] = Field(default_factory=lambda: ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"])  
    exceptionDates: List[str] = Field(default_factory=list)  
    occupiedSlots: List[OccupiedResourceSlotDTO] = Field(default_factory=list)
    existingSchedules: Optional[List[ExistingScheduleRecord]] = Field(default_factory=list)
    groupSizeTarget: int = Field(default=60, gt=0) 
    maxSessionsPerWeekAllowed: int = Field(default=3, gt=0)
    solverTimeLimitSeconds: Optional[float] = Field(default=SOLVERTIMELIMITSECONDS, gt=0)
    objectiveStrategy: Optional[str] = EObjectStrategy.BALANCE_LOAD_AND_EARLY_START  
    

    @field_validator('semesterStartDate', 'semesterEndDate', 'exceptionDates', mode='before')
    def validate_date_format_fields(cls, v: Any, info: ValidationInfo) -> Any:
        field_name = info.field_name if info else "Date field"
        if info.field_name == 'exceptionDates':
            if not isinstance(v, list):
                raise ValueError(f"Incorrect type for {field_name}, expected list of strings.")
            validated_dates = []
            for date_str in v:
                if not isinstance(date_str, str):
                    raise ValueError(f"Incorrect type in {field_name} list, expected string for date.")
                try:
                    date.fromisoformat(date_str)
                    validated_dates.append(date_str)
                except ValueError:
                    raise ValueError(f"Incorrect date format for an item in {field_name}, should be YYYY-MM-DD")
            return validated_dates
        else: 
            if not isinstance(v, str):
                raise ValueError(f"Incorrect type for {field_name}, expected string for date.")
            try:
                date.fromisoformat(v)
            except ValueError:
                raise ValueError(f"Incorrect date format for {field_name}, should be YYYY-MM-DD")
            return v
    
    @field_validator('semesterEndDate', mode='after')
    def end_date_after_start_date(cls, v_end_date: str, info: ValidationInfo) -> str:
        if info.data and 'semesterStartDate' in info.data:
            start_str = info.data.get('semesterStartDate')
            if start_str: 
                start_date_obj = date.fromisoformat(start_str)
                end_date_obj = date.fromisoformat(v_end_date) 
                if end_date_obj <= start_date_obj:
                    raise ValueError("semesterEndDate must be after semesterStartDate")
        return v_end_date
    
class LecturerLoadDTO(BaseModel):
    lecturerId: int
    sessionsAssigned: int


# --- DTOs for Output ---

class WeeklyScheduleDetailDTO(BaseModel):  
    dayOfWeek: str 
    timeSlotId: int 
    roomId: int  

class ClassGroupScheduledDTO(BaseModel): 
    groupNumber: int
    maxStudents: int 
    lecturerId: int
    groupStartDate: str 
    groupEndDate: str   
    totalTeachingWeeksForGroup: int
    sessionsPerWeekForGroup: int 
    weeklyScheduleDetails: List[WeeklyScheduleDetailDTO]

class CourseScheduledDTO(BaseModel): 
    courseId: int
    totalRegisteredStudents: int 
    totalSessionsForCourse: int 
    scheduledClassGroups: List[ClassGroupScheduledDTO]


class FinalScheduleResultDTO(BaseModel): 
    semesterId: int
    semesterStartDate: str  
    semesterEndDate: str
    scheduledCourses: List[CourseScheduledDTO] 
    lecturerLoad: List[LecturerLoadDTO]
    loadDifference: Optional[int] = None
    totalOriginalSessionsToSchedule: int  
    solverDurationSeconds: float
    solverStatus: str 
    solverMessage: Optional[str] = None

# --- Internal Helper Structures ---
class CoursePropertiesInternal: 
    def __init__(self, course_dto: CourseSchedulingInfoDTO, sessions_p_week: int, total_course_weeks: int):
        self.courseId = course_dto.courseId
        self.credits = course_dto.credits
        self.totalSemesterSessions = course_dto.totalSemesterSessions
        self.registeredStudents = course_dto.registeredStudents
        self.potentialLecturerIds = course_dto.potentialLecturerIds
        self.sessionsPerWeek = sessions_p_week
        self.totalCourseWeeks = total_course_weeks  

class SchedulingGroupInternal: 
    def __init__(self, group_id_tuple: Tuple[int, int, int], # (courseId, semesterId, groupNumber)
                 course_props: CoursePropertiesInternal, 
                 actual_students_in_group: int):
        self.id_tuple = group_id_tuple # (courseId, semesterId, groupNumber)
        self.course_props = course_props
        self.actual_students_in_group = actual_students_in_group
        
        self.sessions_to_schedule: List[SessionInternal] = []  
        self.start_semester_week_var: Optional[cp_model.IntVar] = None 
        self.fixed_weekly_day_vars: List[Optional[cp_model.IntVar]] = []
        self.fixed_weekly_shift_vars: List[Optional[cp_model.IntVar]] = []
        self.fixed_weekly_room_vars: List[Optional[cp_model.IntVar]] = []
        self.assigned_lecturer_var: Optional[cp_model.IntVar] = None


    def __repr__(self):
        return (f"SchedGrp(C{self.id_tuple[0]}, S{self.id_tuple[1]}, G{self.id_tuple[2]}, Stud={self.actual_students_in_group})")

class SessionInternal: 
    def __init__(self, 
                 group: SchedulingGroupInternal, 
                 course_week_num: int, 
                 session_in_course_week_num: int,  
                 overall_session_seq_num: int): 
        
        self.group = group
        self.course_week_number = course_week_num
        self.session_in_course_week_number = session_in_course_week_num
        self.overall_session_sequence_number = overall_session_seq_num
        
        self.id_str = (f"s_c{group.id_tuple[0]}_g{group.id_tuple[2]}"
                       f"_cw{course_week_num}_siw{session_in_course_week_num}")
        
        self.assigned_global_slot_var: Optional[cp_model.IntVar] = None  

        self.assigned_semester_week_idx_var: Optional[cp_model.IntVar] = None 
        self.assigned_day_idx_var: Optional[cp_model.IntVar] = None          
        self.assigned_shift_idx_var: Optional[cp_model.IntVar] = None     
        self.assigned_room_idx_var: Optional[cp_model.IntVar] = None 

    def __repr__(self): return self.id_str

class ScheduleService:
    @staticmethod
    def _get_sessions_per_week(
        total_semester_sessions: int, 
        total_semester_weeks_available: int,  
        max_sessions_per_week_allowed: int, 
        course_id_for_log: int,
        credits: Optional[int] 
    ) -> Tuple[int, int]:
        logger = logging.getLogger(f"{ScheduleService.__module__}.{ScheduleService.__name__}._get_sessions_per_week")

        if total_semester_sessions <= 0:
            return 0, 0
        if total_semester_weeks_available <= 0:
            logger.error(f"C{course_id_for_log}: total_semester_weeks_available is 0 or negative. Cannot schedule.")
            raise ValueError(f"Course C{course_id_for_log}: Not enough semester weeks available (0 or less).")

        current_sessions_per_week = 1  
        
        while current_sessions_per_week <= max_sessions_per_week_allowed:
            calculated_total_weeks_for_course = math.ceil(total_semester_sessions / current_sessions_per_week)
            
            if calculated_total_weeks_for_course <= total_semester_weeks_available:
                logger.info(f"C{course_id_for_log}: TotalSessions={total_semester_sessions}, Credits={credits}, "
                            f"Selected Sessions/Week={current_sessions_per_week} (to spread out), "
                            f"Calculated TotalWeeks={calculated_total_weeks_for_course} (within {total_semester_weeks_available} available weeks)")
                return current_sessions_per_week, calculated_total_weeks_for_course
            
            if current_sessions_per_week == max_sessions_per_week_allowed:
                break 
            
            current_sessions_per_week += 1

        # Nếu vòng lặp kết thúc mà không return, nghĩa là không thể xếp lịch được
        # (calculated_total_weeks_for_course vẫn > total_semester_weeks_available ngay cả với max_sessions_per_week_allowed)
        final_calculated_weeks_needed = math.ceil(total_semester_sessions / max_sessions_per_week_allowed)
        error_msg = (f"Course C{course_id_for_log} ({total_semester_sessions} sessions, {credits} credits) "
                     f"cannot be scheduled within {total_semester_weeks_available} semester weeks, "
                     f"even with {max_sessions_per_week_allowed} sessions/week. "
                     f"It would need {final_calculated_weeks_needed} weeks at {max_sessions_per_week_allowed} sessions/week.")
        logger.error(error_msg)
        raise ValueError(error_msg)

    @staticmethod
    async def calculate_with_cp(input_dto: ScheduleInputDTO) -> FinalScheduleResultDTO:
        start_time_measurement = time.time()
        logger = logging.getLogger(f"{ScheduleService.__module__}.{ScheduleService.__name__}.calculate_with_cp")
        logger.info(f"Scheduling request for Semester ID: {input_dto.semesterId}")
        
        try:
            # --- 1. Basic Date & Time Setup ---
            semester_start_date_obj = date.fromisoformat(input_dto.semesterStartDate)
            semester_end_date_obj = date.fromisoformat(input_dto.semesterEndDate)
            
            # Tổng số ngày trong học kỳ (bao gồm cả ngày nghỉ tiềm năng)
            num_calendar_days_in_semester = (semester_end_date_obj - semester_start_date_obj).days + 1
            # Tổng số tuần lịch trong học kỳ
            total_calendar_weeks = math.ceil(num_calendar_days_in_semester / 7) 
            logger.info(f"Semester runs from {input_dto.semesterStartDate} to {input_dto.semesterEndDate} ({total_calendar_weeks} calendar weeks).")

            # Ánh xạ: lecturerId -> index, roomId -> index, timeSlotId -> index
            lecturer_id_to_idx = {l.lecturerId: i for i, l in enumerate(input_dto.lecturers)}
            lecturer_idx_to_id = {i: l.lecturerId for i, l in enumerate(input_dto.lecturers)}
            num_lecturers = len(input_dto.lecturers)

            room_id_to_idx = {r.id: i for i, r in enumerate(input_dto.rooms)}
            room_idx_to_id = {i: r.id for i, r in enumerate(input_dto.rooms)}
            room_capacities_by_idx = [r.capacity for r in input_dto.rooms] # Theo index
            num_rooms = len(input_dto.rooms)
            if num_rooms == 0:
                raise ValueError("No rooms provided for scheduling.")

            # Sử dụng TimeSlotInputDTO.shift để làm key nếu nó là duy nhất, hoặc TimeSlotInputDTO.timeSlotId
            # Giả sử timeSlotId là duy nhất và dùng nó
            timeslot_id_to_idx = {ts.id: i for i, ts in enumerate(input_dto.timeSlots)}
            timeslot_idx_to_id = {i: ts.id for i, ts in enumerate(input_dto.timeSlots)}
            num_shifts_per_day = len(input_dto.timeSlots)
            if num_shifts_per_day == 0:
                raise ValueError("No time slots provided.")

            day_name_to_idx = {day_name: i for i, day_name in enumerate(input_dto.daysOfWeek)}
            day_idx_to_name = {i: day_name for i, day_name in enumerate(input_dto.daysOfWeek)}
            num_days_per_week = len(input_dto.daysOfWeek)
            if num_days_per_week == 0:
                raise ValueError("No days of week provided for scheduling.")

            # --- 2. Pre-process Course Information & Create Scheduling Groups ---
            # (total_semester_weeks sẽ là total_calendar_weeks ở đây,
            #  vì _get_sessions_per_week cần biết giới hạn tuần tối đa)
            
            all_scheduling_groups: List[SchedulingGroupInternal] = []
            all_sessions_to_schedule: List[SessionInternal] = []

            course_properties_map: Dict[int, CoursePropertiesInternal] = {}
            for cs_info_dto in input_dto.coursesToSchedule: # Đã đổi tên biến ở DTO input
                try:
                    sessions_p_week, calc_total_course_wks = ScheduleService._get_sessions_per_week(
                        cs_info_dto.totalSemesterSessions,
                        total_calendar_weeks, # Tổng số tuần lịch của học kỳ
                        input_dto.maxSessionsPerWeekAllowed,
                        cs_info_dto.courseId,
                        cs_info_dto.credits
                    )
                except ValueError as e: 
                    raise HTTPException(status_code=400, detail=f"Course C{cs_info_dto.courseId}: {str(e)}")
                
                # Cập nhật course_properties_map với thông tin mới nhất
                course_properties_map[cs_info_dto.courseId] = CoursePropertiesInternal(
                    cs_info_dto, sessions_p_week, calc_total_course_wks
                )
                
                course_props = course_properties_map[cs_info_dto.courseId] # Lấy lại props đã cập nhật

                if course_props.registeredStudents <= 0 or course_props.totalSemesterSessions <= 0 or course_props.totalCourseWeeks <=0:
                    logger.info(f"C{cs_info_dto.courseId} has {course_props.registeredStudents} students, {course_props.totalSemesterSessions} required sessions, or {course_props.totalCourseWeeks} calculated weeks. Skipping group creation.")
                    continue

                num_groups_for_course = math.ceil(course_props.registeredStudents / input_dto.groupSizeTarget)
                if num_groups_for_course == 0 and course_props.registeredStudents > 0 :
                     num_groups_for_course = 1
                elif num_groups_for_course == 0 and course_props.registeredStudents == 0:
                    logger.info(f"C{cs_info_dto.courseId} has 0 registered students. No groups created.")
                    continue

                base_students_per_group, remaining_students = divmod(course_props.registeredStudents, num_groups_for_course)

                for grp_idx in range(num_groups_for_course):
                    group_num = grp_idx + 1
                    students_in_this_group = base_students_per_group + (1 if grp_idx < remaining_students else 0)
                    
                    if students_in_this_group == 0: 
                        continue

                    sched_group = SchedulingGroupInternal(
                        group_id_tuple=(cs_info_dto.courseId, input_dto.semesterId, group_num),
                        course_props=course_props, # Dùng course_props đã được cập nhật
                        actual_students_in_group=students_in_this_group 
                    )
                    all_scheduling_groups.append(sched_group)

                    # Tạo SessionInternal (logic này giữ nguyên)
                    sessions_created_for_group = 0
                    current_course_week = 1
                    while sessions_created_for_group < course_props.totalSemesterSessions:
                        for session_in_week in range(1, course_props.sessionsPerWeek + 1): # Dùng sessionsPerWeek từ course_props
                            if sessions_created_for_group < course_props.totalSemesterSessions:
                                sessions_created_for_group += 1
                                session_obj = SessionInternal(
                                    group=sched_group,
                                    course_week_num=current_course_week,
                                    session_in_course_week_num=session_in_week,
                                    overall_session_seq_num=sessions_created_for_group
                                )
                                sched_group.sessions_to_schedule.append(session_obj)
                                all_sessions_to_schedule.append(session_obj)
                            else:
                                break
                        current_course_week += 1
                        if current_course_week > course_props.totalCourseWeeks + 2 and sessions_created_for_group < course_props.totalSemesterSessions :
                            logger.error(f"Logic error for C{cs_info_dto.courseId}G{group_num}: Exceeded expected course weeks but not all sessions created.")
                            break
            
            if not all_sessions_to_schedule:
                logger.info("No sessions to schedule after processing courses and groups.")
                # Trả về kết quả rỗng
                duration_s = time.time() - start_time_measurement
                return FinalScheduleResultDTO(
                    generatedWeeklySchedules=[], lecturerLoad=[],
                    totalCourseSessionsToSchedule=0, 
                    totalSemesterWeekSlotsAvailable=num_days_per_week * num_shifts_per_day,
                    totalActiveSemesterWeeks=total_calendar_weeks, # Sẽ cập nhật sau nếu có ngày nghỉ
                    duration=duration_s, status="NO_SESSIONS", message="No sessions to schedule."
                )
            
            total_sessions_count = len(all_sessions_to_schedule)
            logger.info(f"Total {len(all_scheduling_groups)} groups created, with {total_sessions_count} total sessions to schedule.")

            # --- 3. Define Global Slot Mappings & Handle Exclusions (Holidays, Occupied) ---
            # Global slot: một (semester_week_idx, day_idx, shift_idx) duy nhất trong toàn học kỳ
            
            # Tạo map: global_slot_idx -> (semester_week_idx, day_idx, shift_idx)
            # Và ngược lại: (semester_week_idx, day_idx, shift_idx) -> global_slot_idx
            global_slot_to_details: Dict[int, Tuple[int, int, int]] = {}
            details_to_global_slot: Dict[Tuple[int, int, int], int] = {}
            valid_global_slot_indices: List[int] = [] # Chỉ các slot không phải ngày nghỉ

            current_global_slot_idx = 0
            for smw_idx in range(total_calendar_weeks): # 0-based semester week index
                current_week_start_date = semester_start_date_obj + timedelta(weeks=smw_idx)
                for d_idx, day_name in day_idx_to_name.items(): # 0-based day index
                    # Cần kiểm tra ngày hiện tại có nằm trong khoảng [semester_start_date_obj, semester_end_date_obj] không
                    # Và ngày đó có phải là ngày trong input_dto.daysOfWeek không
                    
                    date_for_current_day_slot = current_week_start_date + timedelta(days=d_idx) # Đây là giả định ngày đầu tuần là ngày đầu của d_idx=0
                    
            # Cách tiếp cận tốt hơn để tạo global_slot_map và xử lý ngày nghỉ:
            active_slot_details_list: List[Tuple[int, int, int]] = [] # (smw_idx, day_idx, shift_idx)
            date_to_swk_day_map: Dict[date, Tuple[int,int]] = {} # Ánh xạ ngày cụ thể sang (tuần, ngày index)

            for day_offset in range(num_calendar_days_in_semester):
                current_iter_date = semester_start_date_obj + timedelta(days=day_offset)
                if current_iter_date.strftime("%Y-%m-%d") in input_dto.exceptionDates:
                    continue # Bỏ qua ngày nghỉ

                # Xác định (semester_week_idx, day_idx) cho current_iter_date
                smw_idx_for_date, d_idx_for_date = get_semester_week_and_day_indices(
                    current_iter_date, semester_start_date_obj, day_name_to_idx
                )

                if smw_idx_for_date is not None and d_idx_for_date is not None:
                    date_to_swk_day_map[current_iter_date] = (smw_idx_for_date, d_idx_for_date)
                    for sh_idx in range(num_shifts_per_day):
                        active_slot_details_list.append((smw_idx_for_date, d_idx_for_date, sh_idx))
            
            active_slot_details_list.sort() # Sắp xếp để global_slot_idx có thứ tự

            for idx, details in enumerate(active_slot_details_list):
                global_slot_to_details[idx] = details
                details_to_global_slot[details] = idx
                valid_global_slot_indices.append(idx)
            
            num_total_active_slots = len(valid_global_slot_indices)
            if num_total_active_slots == 0:
                raise ValueError("No active scheduling slots available after considering holidays.")
            
            logger.info(f"Total {num_total_active_slots} active global slots available for scheduling (after holidays).")
            
            # Xử lý occupied slots (chuyển thành global_slot_indices bị cấm cho NoOverlap2D)
            occupied_lecturer_intervals_data: List[Tuple[int, int]] = [] # (lecturer_idx, global_slot_idx)
            occupied_room_intervals_data: List[Tuple[int, int]] = []     # (room_idx, global_slot_idx)

            logger.info(f"Processing {len(input_dto.existingSchedules)} existing schedule records for occupied slots...")
            print(input_dto.existingSchedules)
            for existing_record in input_dto.existingSchedules:
                try:
                    record_start_obj = existing_record.start_date
                    record_end_obj = existing_record.end_date
                    
                    occupied_day_name = existing_record.day_of_week # Ví dụ "MONDAY"
                    if occupied_day_name not in day_name_to_idx:
                        logger.warning(f"Day '{occupied_day_name}' from existing schedule not in current semester's daysOfWeek. Skipping record: {existing_record.dict()}")
                        continue

                    occupied_day_idx_in_week = day_name_to_idx[occupied_day_name] # 0-based index for the day of week
                    occupied_timeslot_idx = timeslot_id_to_idx.get(existing_record.time_slot_id)
                    
                    if occupied_timeslot_idx is None:
                        logger.warning(f"TimeSlotId {existing_record.time_slot_id} from existing schedule not found. Skipping record: {existing_record.dict()}")
                        continue

                    current_date_iter = record_start_obj
                    while current_date_iter <= record_end_obj:
                        # Chỉ xử lý nếu ngày này nằm trong khoảng học kỳ hiện tại VÀ là ngày được chỉ định trong tuần
                        # (ví dụ: nếu record.dayOfWeek là MONDAY, chỉ xử lý các ngày Thứ Hai)
                        
                        # get_semester_week_and_day_indices sẽ trả về (None,None) nếu ngày không hợp lệ hoặc ngoài học kỳ
                        iter_smw_idx, iter_day_idx = get_semester_week_and_day_indices(
                            current_date_iter, semester_start_date_obj, day_name_to_idx
                        )

                        if iter_smw_idx is not None and iter_day_idx == occupied_day_idx_in_week:
                            # Ngày này là ngày mục tiêu (ví dụ, Thứ Hai) và nằm trong học kỳ

                            # Kiểm tra xem ngày này có phải ngày nghỉ không
                            if current_date_iter.strftime("%Y-%m-%d") in input_dto.exceptionDates:
                                current_date_iter += timedelta(days=1) # Chuyển sang ngày tiếp theo để tìm ngày dayOfWeek tiếp theo
                                continue

                            # Tìm global_slot_idx cho (iter_smw_idx, iter_day_idx, occupied_timeslot_idx)
                            global_slot_idx_for_occ = details_to_global_slot.get((iter_smw_idx, iter_day_idx, occupied_timeslot_idx))

                            if global_slot_idx_for_occ is not None: # Slot này là một active slot
                                # Phòng bị chiếm
                                r_idx_occ = room_id_to_idx.get(existing_record.room_id)
                                if r_idx_occ is not None:
                                    occupied_room_intervals_data.append((r_idx_occ, global_slot_idx_for_occ))
                                else:
                                    logger.warning(f"RoomId {existing_record.room_id} from existing schedule not found in current room list.")
                                
                                # Giảng viên bị chiếm
                                l_idx_occ = lecturer_id_to_idx.get(existing_record.lecturer_id)
                                if l_idx_occ is not None:
                                    occupied_lecturer_intervals_data.append((l_idx_occ, global_slot_idx_for_occ))
                                else:
                                    logger.warning(f"LecturerId {existing_record.lecturer_id} from existing schedule not found in current lecturer list.")
                        
                        # Chuyển đến ngày tiếp theo để kiểm tra, hoặc nhảy 1 tuần nếu muốn tối ưu hơn
                        # Để đơn giản và chính xác, cứ đi từng ngày rồi kiểm tra ngày trong tuần
                        current_date_iter += timedelta(days=1)

                except ValueError as ve_date:
                    logger.warning(f"Date parsing error for existing schedule record: {ve_date}. Skipping: {existing_record.dict()}")
                except Exception as e_rec:
                    logger.error(f"Unexpected error processing existing schedule record: {e_rec}. Record: {existing_record.dict()}", exc_info=True)

            logger.info(f"After processing existingSchedules: {len(occupied_room_intervals_data)} occupied room slots and "
                        f"{len(occupied_lecturer_intervals_data)} occupied lecturer slots for NoOverlap.")

            logger.info(f"Processing {len(input_dto.occupiedSlots)} specific occupied slots...")
            for occ_slot in input_dto.occupiedSlots:
                try:
                    occ_date_obj = date.fromisoformat(occ_slot.date)
                except ValueError:
                    logger.warning(f"Invalid date format in occupied slot: {occ_slot.dict()}. Skipping.")
                    continue

                if occ_date_obj.strftime("%Y-%m-%d") in input_dto.exceptionDates:
                    logger.info(f"Occupied slot on a holiday {occ_slot.date}, ignoring as holiday takes precedence.")
                    continue

                swk_idx_occ, d_idx_occ = date_to_swk_day_map.get(occ_date_obj, (None, None))
                
                # Lấy shift_idx từ occ_slot.timeSlotId
                # Cần đảm bảo occ_slot.timeSlotId là ID thực, không phải giá trị "shift"
                sh_idx_occ = timeslot_id_to_idx.get(occ_slot.timeSlotId)

                if swk_idx_occ is not None and d_idx_occ is not None and sh_idx_occ is not None:
                    global_slot_idx_for_occ = details_to_global_slot.get((swk_idx_occ, d_idx_occ, sh_idx_occ))
                    if global_slot_idx_for_occ is not None:
                        if occ_slot.resourceType == 'room':
                            room_id_occ = occ_slot.resourceId
                            # Kiểm tra room_id_occ có phải là int (ID) hay str (roomNumber)
                            # Giả sử nó là ID (int)
                            r_idx_occ = room_id_to_idx.get(int(room_id_occ)) if isinstance(room_id_occ, (int,str)) and str(room_id_occ).isdigit() else None
                            if r_idx_occ is None and isinstance(room_id_occ, str): # Nếu là roomNumber
                                 r_obj_occ = next((r for r in input_dto.rooms if r.roomNumber == room_id_occ), None)
                                 if r_obj_occ: r_idx_occ = room_id_to_idx.get(r_obj_occ.roomId)
                                                        
                            if r_idx_occ is not None:
                                occupied_room_intervals_data.append((r_idx_occ, global_slot_idx_for_occ))
                            else:
                                logger.warning(f"Room ID/Number {occ_slot.resourceId} in occupied slot not found.")
                        
                        elif occ_slot.resourceType == 'lecturer':
                            lect_id_occ = occ_slot.resourceId
                            l_idx_occ = lecturer_id_to_idx.get(int(lect_id_occ)) if isinstance(lect_id_occ, (int,str)) and str(lect_id_occ).isdigit() else None
                            if l_idx_occ is not None:
                                occupied_lecturer_intervals_data.append((l_idx_occ, global_slot_idx_for_occ))
                            else:
                                logger.warning(f"Lecturer ID {occ_slot.resourceId} in occupied slot not found.")
                    else:
                        logger.warning(f"Occupied slot on {occ_slot.date} (swk:{swk_idx_occ},d:{d_idx_occ},sh:{sh_idx_occ}) is not an active slot (likely holiday). Skipping.")
                else:
                    logger.warning(f"Could not map occupied slot date/time to indices: {occ_slot.dict()}. Skipping.")
            
            logger.info(f"Processed {len(occupied_room_intervals_data)} occupied room slots and "
                        f"{len(occupied_lecturer_intervals_data)} occupied lecturer slots for NoOverlap.")


            # --- 4. Create CP Model and Variables ---
            model = cp_model.CpModel()

            for group in all_scheduling_groups:
                course_p = group.course_props
                # a. Tuần bắt đầu của nhóm (trong số các tuần LỊCH của học kỳ)
                # totalCourseWeeks là số tuần MÔN HỌC diễn ra.
                # total_calendar_weeks là tổng số tuần của HỌC KỲ.
                max_start_week = total_calendar_weeks - course_p.totalCourseWeeks
                if max_start_week < 0 : # Môn học dài hơn học kỳ
                     raise ValueError(f"Course C{course_p.courseId} ({course_p.totalCourseWeeks} weeks) is longer than semester ({total_calendar_weeks} weeks).")
                group.start_semester_week_var = model.NewIntVar(0, max_start_week, f'grp_start_sw_{group.id_tuple}')

                # b. Giảng viên được gán cho nhóm
                # Lấy danh sách index giảng viên tiềm năng cho môn học của nhóm này
                potential_lect_indices = [lecturer_id_to_idx[l_id] for l_id in course_p.potentialLecturerIds if l_id in lecturer_id_to_idx]
                if not potential_lect_indices:
                    raise ValueError(f"No potential lecturers found or mapped for course with ID: {course_p.courseId}.")
                
                group.assigned_lecturer_var = model.NewIntVar(0, num_lecturers - 1, f'grp_lect_{group.id_tuple}')
                model.AddAllowedAssignments([group.assigned_lecturer_var], [(l_idx,) for l_idx in potential_lect_indices])

                # c. (Thứ, Ca, Phòng) cố định hàng tuần cho mỗi buổi học của nhóm
                group.fixed_weekly_day_vars = [
                    model.NewIntVar(0, num_days_per_week - 1, f'grp_day_{group.id_tuple}_sess{i_sess_wk}') 
                    for i_sess_wk in range(course_p.sessionsPerWeek)
                ]
                group.fixed_weekly_shift_vars = [
                    model.NewIntVar(0, num_shifts_per_day - 1, f'grp_shift_{group.id_tuple}_sess{i_sess_wk}')
                    for i_sess_wk in range(course_p.sessionsPerWeek)
                ]
                group.fixed_weekly_room_vars = [ # Phòng cũng cố định cho mỗi (thứ, ca) hàng tuần
                    model.NewIntVar(0, num_rooms - 1, f'grp_room_{group.id_tuple}_sess{i_sess_wk}')
                    for i_sess_wk in range(course_p.sessionsPerWeek)
                ]

                # Ràng buộc: Các (thứ, ca) cố định hàng tuần của một nhóm phải khác nhau
                if course_p.sessionsPerWeek > 1:
                    temp_weekly_slot_ids = []
                    for i_sess_wk in range(course_p.sessionsPerWeek):
                        # Biến tạm để thể hiện slot trong tuần (0 đến num_days_per_week * num_shifts_per_day - 1)
                        weekly_slot_id_var = model.NewIntVar(0, (num_days_per_week * num_shifts_per_day) -1, f'grp_wkly_slotid_{group.id_tuple}_sess{i_sess_wk}')
                        # weekly_slot_id = day_var * num_shifts_per_day + shift_var
                        model.Add(weekly_slot_id_var == group.fixed_weekly_day_vars[i_sess_wk] * num_shifts_per_day + group.fixed_weekly_shift_vars[i_sess_wk])
                        temp_weekly_slot_ids.append(weekly_slot_id_var)
                    model.AddAllDifferent(temp_weekly_slot_ids)
            
            for session in all_sessions_to_schedule:
                group = session.group
                
                session.assigned_global_slot_var = model.NewIntVarFromDomain(
                    cp_model.Domain.FromValues(valid_global_slot_indices),
                    f'sess_globalslot_{session.id_str}'
                )

                session.assigned_semester_week_idx_var = model.NewIntVar(0, total_calendar_weeks - 1, f'sess_smw_{session.id_str}')
                session.assigned_day_idx_var = model.NewIntVar(0, num_days_per_week - 1, f'sess_day_{session.id_str}')
                session.assigned_shift_idx_var = model.NewIntVar(0, num_shifts_per_day - 1, f'sess_shift_{session.id_str}')
                
                model.AddElement(session.assigned_global_slot_var, 
                                 [global_slot_to_details[gs_idx][0] for gs_idx in valid_global_slot_indices],
                                 session.assigned_semester_week_idx_var)
                model.AddElement(session.assigned_global_slot_var,
                                 [global_slot_to_details[gs_idx][1] for gs_idx in valid_global_slot_indices],
                                 session.assigned_day_idx_var)
                model.AddElement(session.assigned_global_slot_var,
                                 [global_slot_to_details[gs_idx][2] for gs_idx in valid_global_slot_indices],
                                 session.assigned_shift_idx_var)
                
                model.Add(session.assigned_semester_week_idx_var == group.start_semester_week_var + (session.course_week_number - 1))

                session_in_week_0_based = session.session_in_course_week_number - 1
                
                # ---- KIỂM TRA VÀ GÁN session.assigned_room_idx_var ----
                if not (0 <= session_in_week_0_based < len(group.fixed_weekly_room_vars) and \
                        group.fixed_weekly_room_vars[session_in_week_0_based] is not None):
                    logger.error(f"CRITICAL: Problem with fixed_weekly_room_vars for group {group.id_tuple}, session_in_week_idx {session_in_week_0_based}.")
                    # Quyết định xử lý: raise lỗi hoặc bỏ qua session này trong NoOverlap
                    # Nếu bỏ qua, NoOverlap sẽ không đầy đủ. Tốt nhất là raise lỗi để sửa logic tạo biến.
                    raise ValueError(f"fixed_weekly_room_vars not properly initialized for group {group.id_tuple}, session_in_week_idx {session_in_week_0_based}")

                session.assigned_room_idx_var = group.fixed_weekly_room_vars[session_in_week_0_based]
                # -------------------------------------------------------
                
                model.Add(session.assigned_day_idx_var == group.fixed_weekly_day_vars[session_in_week_0_based])
                model.Add(session.assigned_shift_idx_var == group.fixed_weekly_shift_vars[session_in_week_0_based])


            # --- 5. Define Constraints ---
            logger.info("Defining constraints...")
            # RB_RoomCapacity: Sức chứa phòng >= số SV của nhóm
            for group in all_scheduling_groups:
                students_in_group = group.actual_students_in_group
                for room_var_for_weekly_session in group.fixed_weekly_room_vars:
                    # room_var_for_weekly_session là index của phòng được gán cho 1 buổi cố định hàng tuần
                    # Cần lấy capacity của phòng đó
                    room_capacity_for_this_fixed_session_var = model.NewIntVar(0, max(room_capacities_by_idx) if room_capacities_by_idx else 0, f'cap_g{group.id_tuple}_{room_var_for_weekly_session.Name()}')
                    model.AddElement(room_var_for_weekly_session, room_capacities_by_idx, room_capacity_for_this_fixed_session_var)
                    model.Add(room_capacity_for_this_fixed_session_var >= students_in_group)

            # RB_NoOverlap_Lecturers_And_Rooms (using NoOverlap2D)
            lecturer_interval_vars_x = []
            lecturer_interval_vars_y = []
            room_interval_vars_x = []
            room_interval_vars_y = []
            
            size_one_interval = model.NewConstant(1)

            # Thêm các slot đã bị chiếm (từ khoa khác) vào NoOverlap
            for l_idx_occ, glob_slot_idx_occ in occupied_lecturer_intervals_data:
                lecturer_interval_vars_x.append(model.NewIntervalVar(model.NewConstant(l_idx_occ), size_one_interval, model.NewConstant(l_idx_occ + 1), f"occ_L{l_idx_occ}_s{glob_slot_idx_occ}_x"))
                lecturer_interval_vars_y.append(model.NewIntervalVar(model.NewConstant(glob_slot_idx_occ), size_one_interval, model.NewConstant(glob_slot_idx_occ + 1), f"occ_L{l_idx_occ}_s{glob_slot_idx_occ}_y"))

            for r_idx_occ, glob_slot_idx_occ in occupied_room_intervals_data:
                room_interval_vars_x.append(model.NewIntervalVar(model.NewConstant(r_idx_occ), size_one_interval, model.NewConstant(r_idx_occ + 1), f"occ_R{r_idx_occ}_s{glob_slot_idx_occ}_x"))
                room_interval_vars_y.append(model.NewIntervalVar(model.NewConstant(glob_slot_idx_occ), size_one_interval, model.NewConstant(glob_slot_idx_occ + 1), f"occ_R{r_idx_occ}_s{glob_slot_idx_occ}_y"))

            for session in all_sessions_to_schedule:
                group = session.group
                
                # Kiểm tra lại một lần nữa ngay trước khi sử dụng, mặc dù đã kiểm tra ở trên
                if group.assigned_lecturer_var is None or \
                   session.assigned_global_slot_var is None or \
                   session.assigned_room_idx_var is None: # assigned_room_idx_var giờ là một IntVar
                    logger.warning(f"Skipping session {session.id_str} for NoOverlap2D due to missing CP variables.")
                    continue

                # Giảng viên
                lecturer_end_var = model.NewIntVar(0, num_lecturers, f"LEND_{session.id_str}") # num_lecturers là borne sup
                model.Add(lecturer_end_var == group.assigned_lecturer_var + 1) # Hoặc dùng size_one_interval
                lecturer_interval_vars_x.append(model.NewIntervalVar(
                    group.assigned_lecturer_var, size_one_interval, lecturer_end_var, f"LXV_{session.id_str}"
                ))
                
                global_slot_end_var_lect = model.NewIntVar(0, num_total_active_slots, f"GSLEND_L_{session.id_str}")
                model.Add(global_slot_end_var_lect == session.assigned_global_slot_var + 1)
                lecturer_interval_vars_y.append(model.NewIntervalVar(
                    session.assigned_global_slot_var, size_one_interval, global_slot_end_var_lect, f"LYV_{session.id_str}"
                ))

                # Phòng
                room_end_var = model.NewIntVar(0, num_rooms, f"REND_{session.id_str}")
                model.Add(room_end_var == session.assigned_room_idx_var + 1)
                room_interval_vars_x.append(model.NewIntervalVar(
                    session.assigned_room_idx_var, size_one_interval, room_end_var, f"RXV_{session.id_str}"
                ))

                global_slot_end_var_room = model.NewIntVar(0, num_total_active_slots, f"GSLEND_R_{session.id_str}")
                model.Add(global_slot_end_var_room == session.assigned_global_slot_var + 1)
                room_interval_vars_y.append(model.NewIntervalVar(
                    session.assigned_global_slot_var, size_one_interval, global_slot_end_var_room, f"RYV_{session.id_str}"
                ))
            
            if lecturer_interval_vars_x: # Đảm bảo có gì đó để thêm
                model.AddNoOverlap2D(lecturer_interval_vars_x, lecturer_interval_vars_y)
                logger.info(f"Added NoOverlap2D for {len(lecturer_interval_vars_x)} lecturer intervals.")
            if room_interval_vars_x:
                model.AddNoOverlap2D(room_interval_vars_x, room_interval_vars_y)
                logger.info(f"Added NoOverlap2D for {len(room_interval_vars_x)} room intervals.")

            # (RB3 cũ - Max Sessions Per Group Per Semester Week - đã được đảm bảo bằng cách tạo session)
            # (RB4 cũ - Sessions of same group in same course week in different slots - đã được đảm bảo bằng AddAllDifferent trên (day,shift) cố định hàng tuần)

            # --- 6. Define Objective Function ---
            logger.info("Defining objective function...")
            objective_terms = []
            
            # Tải giảng viên thực tế
            actual_lecturer_loads_vars: List[cp_model.IntVar] = []
            if num_lecturers > 0 and total_sessions_count > 0:
                actual_lecturer_loads_vars = [
                    model.NewIntVar(0, total_sessions_count, f'actual_load_lect{l_idx}') 
                    for l_idx in range(num_lecturers)
                ]
                for l_idx in range(num_lecturers):
                    sessions_for_this_lecturer_bools = []
                    for group in all_scheduling_groups: # Chỉ cần xét mỗi nhóm một lần
                        # group.assigned_lecturer_var là giảng viên của cả nhóm
                        is_this_lecturer_for_group_var = model.NewBoolVar(f'is_l{l_idx}_for_g{group.id_tuple}')
                        model.Add(group.assigned_lecturer_var == l_idx).OnlyEnforceIf(is_this_lecturer_for_group_var)
                        model.Add(group.assigned_lecturer_var != l_idx).OnlyEnforceIf(is_this_lecturer_for_group_var.Not())
                        
                        # Đếm số session của nhóm này nếu giảng viên này được gán
                        num_sessions_in_group = len(group.sessions_to_schedule)
                        term_for_this_group = model.NewIntVar(0, num_sessions_in_group, f'term_l{l_idx}_g{group.id_tuple}')
                        model.Add(term_for_this_group == num_sessions_in_group).OnlyEnforceIf(is_this_lecturer_for_group_var)
                        model.Add(term_for_this_group == 0).OnlyEnforceIf(is_this_lecturer_for_group_var.Not())
                        sessions_for_this_lecturer_bools.append(term_for_this_group)
                    
                    if sessions_for_this_lecturer_bools:
                        model.Add(actual_lecturer_loads_vars[l_idx] == sum(sessions_for_this_lecturer_bools))
                    else: # Không có nhóm nào, tải = 0
                        model.Add(actual_lecturer_loads_vars[l_idx] == 0)

            if "BALANCE_LOAD" in input_dto.objectiveStrategy.value and actual_lecturer_loads_vars:
                max_load_var = model.NewIntVar(0, total_sessions_count, 'obj_max_load')
                min_load_var = model.NewIntVar(0, total_sessions_count, 'obj_min_load')
                model.AddMaxEquality(max_load_var, actual_lecturer_loads_vars)
                model.AddMinEquality(min_load_var, actual_lecturer_loads_vars)
                load_difference_var = model.NewIntVar(0, total_sessions_count, 'obj_load_diff')
                model.Add(load_difference_var == max_load_var - min_load_var)
                objective_terms.append(load_difference_var) # Mục tiêu: minimize sự chênh lệch

            if "EARLY_START" in input_dto.objectiveStrategy.value:
                # Tạo danh sách các biến start_semester_week_var hợp lệ (không None)
                # Mặc dù theo logic, tất cả đều nên được khởi tạo.
                # Đây là một bước kiểm tra an toàn.
                valid_start_week_vars = [
                    g.start_semester_week_var 
                    for g in all_scheduling_groups 
                    if g.start_semester_week_var is not None # Kiểm tra is not None thay vì if g.start_semester_week_var
                ]
                
                if valid_start_week_vars: # Chỉ thêm mục tiêu nếu có biến hợp lệ
                    # Tính toán borne supérieure cho sum_of_start_weeks_var
                    # max_start_week_val là giá trị lớn nhất mà một start_semester_week_var có thể nhận
                    # (total_calendar_weeks - course_props.totalCourseWeeks)
                    # Lấy giá trị max_start_week lớn nhất có thể trong tất cả các group
                    max_possible_single_start_week = 0
                    if all_scheduling_groups:
                        max_possible_single_start_week = max(
                            (total_calendar_weeks - g.course_props.totalCourseWeeks) 
                            for g in all_scheduling_groups 
                            if (total_calendar_weeks - g.course_props.totalCourseWeeks) >=0 # Đảm bảo không âm
                        )
                    
                    max_sum_val = max_possible_single_start_week * len(valid_start_week_vars)
                    if max_sum_val == 0 and valid_start_week_vars : max_sum_val = len(valid_start_week_vars) # trường hợp tất cả max_start_week = 0
                    if max_sum_val == 0 and not valid_start_week_vars: max_sum_val = 1 # Tránh borne sup = 0 nếu không có biến


                    sum_of_start_weeks_var = model.NewIntVar(
                        0, 
                        max_sum_val if max_sum_val > 0 else 1, # Đảm bảo borne sup > 0
                        'obj_sum_start_weeks'
                    )
                    model.Add(sum_of_start_weeks_var == sum(valid_start_week_vars))
                    objective_terms.append(sum_of_start_weeks_var) # Mục tiêu: minimize tổng tuần bắt đầu
                    logger.info(f"Added 'EARLY_START' objective term with {len(valid_start_week_vars)} variables.")
                else:
                    logger.info("Skipping 'EARLY_START' objective term as no valid start_semester_week_vars found.")

            if objective_terms:
                # Tính tổng giới hạn trên của các thành phần mục tiêu để giới hạn biến total_objective_var
                max_possible_objective_value = 0
                if "BALANCE_LOAD" in input_dto.objectiveStrategy.value: max_possible_objective_value += total_sessions_count
                if "EARLY_START" in input_dto.objectiveStrategy.value: max_possible_objective_value += total_calendar_weeks * len(all_scheduling_groups)
                if max_possible_objective_value == 0: max_possible_objective_value = 1 # Tránh upper bound là 0

                total_objective_var = model.NewIntVar(0, max_possible_objective_value, 'total_objective')
                model.Add(total_objective_var == sum(objective_terms))
                model.Minimize(total_objective_var)
                logger.info(f"Minimizing objective with terms: {input_dto.objectiveStrategy}")
            else:
                logger.info("No specific objective. Searching for a feasible solution.")


            # --- 7. Solve the Model ---
            logger.info("Starting solver...")
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = input_dto.solverTimeLimitSeconds
            solver.parameters.log_search_progress = True
            # solver.parameters.num_search_workers = 4 # Cân nhắc nếu máy có nhiều CPU
            # solver.parameters.fz_logging_to_stdout = True # Để debug chi tiết flatzinc
            
            solution_status_code = solver.Solve(model)
            solution_status_name = solver.StatusName(solution_status_code)
            logger.info(f"Solver finished with status: {solution_status_name}")

    # ... (Phần code từ đầu đến trước khi xử lý kết quả giữ nguyên) ...

            # --- 8. Process Solution & Create Output DTOs ---
            output_scheduled_courses: List[CourseScheduledDTO] = []
            output_lecturer_loads: List[LecturerLoadDTO] = []
            output_load_difference: Optional[int] = None
            
            # Tạo một dictionary để nhóm các SchedulingGroupInternal theo courseId
            groups_by_course: Dict[int, List[SchedulingGroupInternal]] = {}
            for group_obj in all_scheduling_groups:
                groups_by_course.setdefault(group_obj.course_props.courseId, []).append(group_obj)

            if solution_status_code == cp_model.OPTIMAL or solution_status_code == cp_model.FEASIBLE:
                logger.info("Solution found. Processing results into new DTO structure...")
                if objective_terms: # Chỉ log nếu có mục tiêu
                    try:
                        logger.info(f"Objective value: {solver.ObjectiveValue()}")
                    except RuntimeError: # Có thể xảy ra nếu không có giải pháp tối ưu thực sự cho mục tiêu
                         logger.warning("Could not retrieve objective value despite FEASIBLE/OPTIMAL status.")


                for course_id, list_of_groups_for_course in groups_by_course.items():
                    # Lấy thông tin gốc của môn học từ course_properties_map
                    # để lấy totalRegisteredStudents và totalSessionsForCourse
                    original_course_props = course_properties_map.get(course_id)
                    if not original_course_props:
                        logger.error(f"Could not find original properties for course C{course_id} when processing results.")
                        continue

                    course_scheduled_dto = CourseScheduledDTO(
                        courseId=course_id,
                        totalRegisteredStudents=original_course_props.registeredStudents, # Từ CoursePropertiesInternal
                        totalSessionsForCourse=original_course_props.totalSemesterSessions, # Từ CoursePropertiesInternal
                        scheduledClassGroups=[]
                    )
                    
                    for group in list_of_groups_for_course:
                        try:
                            assigned_lect_idx = solver.Value(group.assigned_lecturer_var)
                            assigned_lect_id = lecturer_idx_to_id[assigned_lect_idx]
                            start_sem_week_val_0based = solver.Value(group.start_semester_week_var)
                            
                            group_actual_start_date_obj = semester_start_date_obj + timedelta(weeks=start_sem_week_val_0based)
                            last_course_week_for_group_0based = start_sem_week_val_0based + group.course_props.totalCourseWeeks - 1
                            temp_end_date_last_week = semester_start_date_obj + timedelta(weeks=last_course_week_for_group_0based)
                            group_actual_end_date_obj = temp_end_date_last_week + timedelta(days=(6 - temp_end_date_last_week.weekday()))

                            weekly_details_for_this_group: List[WeeklyScheduleDetailDTO] = []
                            for i_sess_wk_0based in range(group.course_props.sessionsPerWeek):
                                day_idx_val = solver.Value(group.fixed_weekly_day_vars[i_sess_wk_0based])
                                shift_idx_val = solver.Value(group.fixed_weekly_shift_vars[i_sess_wk_0based])
                                room_idx_val = solver.Value(group.fixed_weekly_room_vars[i_sess_wk_0based])
                                weekly_details_for_this_group.append(WeeklyScheduleDetailDTO(
                                    dayOfWeek=day_idx_to_name[day_idx_val],
                                    timeSlotId=timeslot_idx_to_id[shift_idx_val],
                                    roomId=room_idx_to_id[room_idx_val]
                                ))
                            
                            class_group_dto = ClassGroupScheduledDTO(
                                groupNumber=group.id_tuple[2],
                                maxStudents=input_dto.groupSizeTarget, # Sử dụng groupSizeTarget làm maxStudents
                                lecturerId=assigned_lect_id,
                                groupStartDate=group_actual_start_date_obj.strftime("%Y-%m-%d"),
                                groupEndDate=group_actual_end_date_obj.strftime("%Y-%m-%d"),
                                totalTeachingWeeksForGroup=group.course_props.totalCourseWeeks,
                                sessionsPerWeekForGroup=group.course_props.sessionsPerWeek,
                                weeklyScheduleDetails=weekly_details_for_this_group
                            )
                            course_scheduled_dto.scheduledClassGroups.append(class_group_dto)
                        except Exception as e_grp_proc:
                            logger.error(f"Error processing solution for group {group.id_tuple} of course C{course_id}: {e_grp_proc}", exc_info=True)
                    
                    if course_scheduled_dto.scheduledClassGroups:
                        output_scheduled_courses.append(course_scheduled_dto)

                # Tính toán lecturer load
                if actual_lecturer_loads_vars:
                    try:
                        loads = [solver.Value(lv) for lv in actual_lecturer_loads_vars]
                        for l_idx, load_val in enumerate(loads):
                            output_lecturer_loads.append(LecturerLoadDTO(lecturerId=lecturer_idx_to_id[l_idx], sessionsAssigned=load_val))
                        if loads: # Chỉ tính diff nếu có loads
                            output_load_difference = max(loads) - min(loads) if loads else None # Tránh lỗi nếu loads rỗng
                    except Exception as e_load_proc:
                         logger.error(f"Error processing lecturer loads from solution: {e_load_proc}", exc_info=True)
                
                # Nếu không có actual_lecturer_loads_vars (ví dụ: không có giảng viên hoặc session)
                elif not actual_lecturer_loads_vars and num_lecturers > 0:
                    for l_id_val in lecturer_id_to_idx.keys():
                         output_lecturer_loads.append(LecturerLoadDTO(lecturerId=l_id_val, sessionsAssigned=0))


            elif solution_status_code == cp_model.INFEASIBLE:
                logger.warning("Solver determined the model is INFEASIBLE.")
            else: 
                logger.error(f"Solver finished with unhandled status: {solution_status_name}")
            
            duration_seconds = time.time() - start_time_measurement
            
            final_message = f"Solver finished with status: {solution_status_name}."
            if solution_status_code == cp_model.OPTIMAL or solution_status_code == cp_model.FEASIBLE:
                if output_scheduled_courses:
                    final_message = "Schedule generated successfully."
                else:
                    final_message = "Feasible/Optimal solution found, but no courses were scheduled (check input or constraints)."


            return FinalScheduleResultDTO( 
                semesterId=input_dto.semesterId,
                semesterStartDate=input_dto.semesterStartDate,
                semesterEndDate=input_dto.semesterEndDate,
                scheduledCourses=output_scheduled_courses,
                lecturerLoad=output_lecturer_loads,  
                loadDifference=output_load_difference, 
                totalOriginalSessionsToSchedule=total_sessions_count, 
                solverDurationSeconds=duration_seconds,
                solverStatus=solution_status_name,
                solverMessage=final_message 
            )

        except HTTPException:  
            raise
        except ValueError as ve: 
            logger.error(f"Business logic ValueError: {str(ve)}", exc_info=False) 
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:  
            logger.critical(f"Unexpected error in scheduling service: {type(e).__name__} - {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal Server Error: An unexpected issue occurred.")