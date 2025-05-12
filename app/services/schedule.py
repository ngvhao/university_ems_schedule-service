import logging
import math
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple, Any

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field, ValidationError, validator
from fastapi import HTTPException

# --- DTOs for Input ---
class CourseSemesterDTO(BaseModel):
    courseSemesterId: int
    # Bỏ credits
    totalSemesterSessions: int = Field(gt=0) # Tổng số buổi của môn này trong học kỳ
    registeredStudents: int
    # Bỏ sessionsPerWeek và calculatedTotalWeeksForCourse khỏi DTO input
    # Chúng sẽ được tính toán ở preprocessing

class LecturerDTO(BaseModel):
    userId: int
    departmentId: int
    academicRank: Optional[str] = None
    specialization: Optional[str] = None
    isHeadDepartment: bool = False
    teachingCourses: List[int] 

class RoomDTO(BaseModel):
    roomNumber: str
    buildingName: str
    floor: str
    capacity: int
    roomType: str = "CLASSROOM"

class TimeSlotDTO(BaseModel):
    startTime: str
    endTime: str
    shift: int 

class ScheduleInputDTO(BaseModel):
    semesterStartDate: str
    semesterEndDate: str
    courseSemesters: List[CourseSemesterDTO] # DTO đã được cập nhật
    lecturers: List[LecturerDTO]
    rooms: List[RoomDTO]
    timeSlots: List[TimeSlotDTO]
    days: List[str] 
    maxSessionsPerLecturerConstraint: Optional[int] = None 
    # totalSemesterWeeks sẽ được tính từ startDate và endDate
    solverTimeLimitSeconds: float = 60.0 
    objectiveStrategy: str = "BALANCE_LOAD_AND_EARLY_START" 
    penaltyWeightFixedDayShiftViolation: int = 10000 
    maxSessionsPerWeekAllowed: int = 3 # Giới hạn trên cho số buổi/tuần khi tính toán


    @validator('semesterStartDate', 'semesterEndDate')
    def validate_date_format(cls, v_str):
        try:
            date.fromisoformat(v_str)
        except ValueError:
            raise ValueError("Incorrect date format, should be YYYY-MM-DD")
        return v_str

    @validator('semesterEndDate')
    def end_date_after_start_date(cls, v_str, values):
        start_str = values.get('semesterStartDate')
        if start_str: 
            try:
                start_date_obj = date.fromisoformat(start_str)
                end_date_obj = date.fromisoformat(v_str)
                if end_date_obj <= start_date_obj:
                    raise ValueError("semesterEndDate must be after semesterStartDate")
            except ValueError: 
                pass
        return v_str

# --- DTOs for Output ---
# (Giữ nguyên như phiên bản trước)
class FixedSlotInfo(BaseModel):
    sessionSequenceInWeek: int 
    day: Optional[str] = None
    shift: Optional[str] = None

class ClassGroupOutputDTO(BaseModel):
    groupNumber: int
    maxStudents: int 
    registeredStudents: int 
    status: str = "OPEN" 
    courseSemesterId: int
    startSemesterWeek: Optional[int] = None
    endSemesterWeek: Optional[int] = None
    totalTeachingWeeks: Optional[int] = None # Số tuần thực tế môn này học
    sessionsPerWeekAssigned: Optional[int] = None # Số buổi/tuần được tính toán
    startDate: Optional[str] = None 
    endDate: Optional[str] = None   
    assignedFixedWeeklySlots: List[FixedSlotInfo] = []
    fixedDayShiftViolations: List[Dict[str, Any]] = [] 

class ScheduleEntryDTO(BaseModel):
    courseSemesterId: int
    groupNumber: int
    semesterWeek: int         
    sessionSequenceInWeek: int 
    overallSessionSequence: int 
    shift: str                
    room: str
    lecturerId: int
    day: str                  

class LecturerLoadDTO(BaseModel):
    lecturerId: int
    sessionsAssigned: int

class ViolationDetailDTO(BaseModel):
    constraintType: str
    description: str
    affectedItems: List[str] = [] 
    suggestedAction: Optional[str] = None

class ScheduleResultDTO(BaseModel):
    classGroups: List[ClassGroupOutputDTO]
    schedule: List[ScheduleEntryDTO]
    violations: List[str] 
    detailedSuggestions: List[ViolationDetailDTO] = [] 
    lecturerLoad: List[LecturerLoadDTO]
    loadDifference: Optional[int] = None
    totalCourseSessionsToSchedule: int
    totalSemesterWeekSlots: int 
    totalAvailableRoomSlotsInSemester: int 
    lecturerPotentialLoad: Dict[int, int] 

# --- Helper Structures ---
class ProcessedCourseProps: # Đổi tên từ CourseProps để rõ ràng hơn
    def __init__(self, course_semester_id: int, total_semester_sessions: int, registered_students: int, 
                 calculated_sessions_per_week: int, calculated_total_weeks_for_course: int):
        self.course_semester_id = course_semester_id
        self.total_semester_sessions = total_semester_sessions
        self.registered_students = registered_students
        self.sessions_per_week = calculated_sessions_per_week # Số buổi/tuần đã được tính toán
        self.calculated_total_weeks_for_course = calculated_total_weeks_for_course # Số tuần học dựa trên sessions_per_week

class ClassGroupInternal:
    def __init__(self, course_props: ProcessedCourseProps, group_number: int, registered_students: int): # Sử dụng ProcessedCourseProps
        self.course_props = course_props
        self.group_number = group_number 
        self.registered_students = registered_students
        self.sessions: List[ClassSessionInternal] = []
        self.start_semester_week_var: Optional[cp_model.IntVar] = None 
        self.fixed_weekly_slot_vars: List[Tuple[Optional[cp_model.IntVar], Optional[cp_model.IntVar]]] = []

    def __repr__(self):
        return (f"CG(csId={self.course_props.course_semester_id}, gN={self.group_number}, stud={self.registered_students})")

class ClassSessionInternal:
    # ... (Giữ nguyên)
    def __init__(self, class_group: ClassGroupInternal, course_week_number: int, session_in_course_week: int, overall_session_sequence_num: int):
        self.class_group = class_group
        self.course_week_number = course_week_number 
        self.session_in_course_week = session_in_course_week 
        self.overall_session_sequence_num = overall_session_sequence_num 
        self.id = (f"s_{class_group.course_props.course_semester_id}_g{class_group.group_number}"
                   f"_cw{course_week_number}_siw{session_in_course_week}") 
        self.slot_var: Optional[cp_model.IntVar] = None         
        self.lecturer_var: Optional[cp_model.IntVar] = None     
        self.room_var: Optional[cp_model.IntVar] = None         
        self.assigned_semester_week_var: Optional[cp_model.IntVar] = None 
        self.is_fixed_day_shift_violated_var: Optional[cp_model.BoolVar] = None

    def __repr__(self): return self.id

# --- Schedule Service ---
class ScheduleService:
    # Bỏ _get_sessions_per_week_from_credits

    @staticmethod
    async def calculate_with_cp(input_dto: ScheduleInputDTO) -> ScheduleResultDTO:
        service_logger = logging.getLogger(f"{__name__}.ScheduleService.calculate_with_cp")
        try:
            service_logger.info("Starting schedule calculation (Auto sessions/week, Soft Fixed Day/Shift)...")

            start_date_obj = date.fromisoformat(input_dto.semesterStartDate)
            end_date_obj = date.fromisoformat(input_dto.semesterEndDate)
            num_days_in_semester = (end_date_obj - start_date_obj).days + 1
            total_semester_weeks = math.ceil(num_days_in_semester / 7) # Tính tổng số tuần học kỳ
            service_logger.info(f"Total semester weeks available: {total_semester_weeks}")

            max_room_capacity_overall = max(r.capacity for r in input_dto.rooms) if input_dto.rooms else 50
            
            processed_courses: Dict[int, ProcessedCourseProps] = {}
            for cs_dto in input_dto.courseSemesters:
                calculated_sessions_p_week = 1 # Ưu tiên 1 buổi/tuần
                calculated_total_wks_for_course = math.ceil(cs_dto.totalSemesterSessions / calculated_sessions_p_week)

                # Nếu số tuần cần thiết > tổng số tuần học kỳ, tăng số buổi/tuần
                while calculated_total_wks_for_course > total_semester_weeks and calculated_sessions_p_week < input_dto.maxSessionsPerWeekAllowed:
                    calculated_sessions_p_week += 1
                    calculated_total_wks_for_course = math.ceil(cs_dto.totalSemesterSessions / calculated_sessions_p_week)
                
                if calculated_total_wks_for_course > total_semester_weeks:
                    raise HTTPException(status_code=400, 
                                        detail=f"Course C{cs_dto.courseSemesterId} ({cs_dto.totalSemesterSessions} sessions) "
                                               f"cannot be scheduled within {total_semester_weeks} semester weeks, "
                                               f"even with {input_dto.maxSessionsPerWeekAllowed} sessions/week. "
                                               f"Needs {calculated_total_wks_for_course} weeks.")
                
                service_logger.info(f"C{cs_dto.courseSemesterId}: TotalSessions={cs_dto.totalSemesterSessions}, "
                                    f"Calculated Sessions/Week={calculated_sessions_p_week}, "
                                    f"Calculated TotalWeeks={calculated_total_wks_for_course}")

                processed_courses[cs_dto.courseSemesterId] = ProcessedCourseProps(
                    course_semester_id=cs_dto.courseSemesterId,
                    total_semester_sessions=cs_dto.totalSemesterSessions,
                    registered_students=cs_dto.registeredStudents,
                    calculated_sessions_per_week=calculated_sessions_p_week,
                    calculated_total_weeks_for_course=calculated_total_wks_for_course
                )

            lecturers_list = input_dto.lecturers
            lecturer_id_to_idx = {l.userId: i for i, l in enumerate(lecturers_list)}
            lecturer_idx_to_id = {i: l.userId for i, l in enumerate(lecturers_list)}
            lecturer_id_to_teaching_courses = {l.userId: l.teachingCourses for l in lecturers_list}

            rooms_list = input_dto.rooms
            room_name_to_idx = {r.roomNumber: i for i, r in enumerate(rooms_list)}
            room_idx_to_name = {i: r.roomNumber for i, r in enumerate(rooms_list)}
            room_caps_list = [r.capacity for r in rooms_list]

            shifts_map = {ts.shift: f"Ca{ts.shift}" for ts in input_dto.timeSlots}
            shift_indices = sorted(shifts_map.keys())
            num_shifts = len(shift_indices) 
            model_shift_idx_to_str = {i: shifts_map[s_val] for i, s_val in enumerate(shift_indices)} 

            day_to_idx = {day: i for i, day in enumerate(input_dto.days)}
            day_idx_to_str = {i: day for i, day in enumerate(input_dto.days)}
            num_days_wk = len(input_dto.days)

            num_lect = len(lecturers_list) 
            num_rooms = len(rooms_list)

            num_wk_slots_unique = num_days_wk * num_shifts 
            num_total_sem_slots_per_resource = num_wk_slots_unique * total_semester_weeks

            sem_slot_map: Dict[int, Tuple[int, int, int]] = {}
            _slot_count = 0
            for swk_idx in range(total_semester_weeks):
                for day_idx_model in range(num_days_wk):
                    for sh_idx_model in range(num_shifts):
                        sem_slot_map[_slot_count] = (swk_idx, day_idx_model, sh_idx_model)
                        _slot_count += 1
            
            internal_groups: List[ClassGroupInternal] = []
            output_groups_dto_map: Dict[Tuple[int,int], ClassGroupOutputDTO] = {} 
            all_sessions: List[ClassSessionInternal] = []

            for cs_id, course_p in processed_courses.items(): # course_p giờ là ProcessedCourseProps
                if course_p.registered_students <= 0 or course_p.total_semester_sessions <= 0 : continue
                num_grps = math.ceil(course_p.registered_students / max_room_capacity_overall) if max_room_capacity_overall > 0 else 1
                if num_grps <= 0: num_grps = 1
                base_stud, rem_stud = divmod(course_p.registered_students, num_grps)
                for i in range(num_grps):
                    grp_num = i + 1
                    stud_in_grp = base_stud + (1 if i < rem_stud else 0)
                    if stud_in_grp == 0 and course_p.registered_students > 0 : continue
                    grp_obj = ClassGroupInternal(course_p, grp_num, stud_in_grp)
                    internal_groups.append(grp_obj)
                    # Thêm sessionsPerWeekAssigned vào DTO output
                    output_groups_dto_map[(cs_id, grp_num)] = ClassGroupOutputDTO(
                        courseSemesterId=cs_id, groupNumber=grp_num,
                        maxStudents=stud_in_grp, registeredStudents=stud_in_grp,
                        sessionsPerWeekAssigned=course_p.sessions_per_week 
                    )
                    if stud_in_grp > 0 and course_p.total_semester_sessions > 0:
                        created_s, curr_cwk = 0, 1 # course_week_number
                        # Vòng lặp tạo session dựa trên total_semester_sessions
                        # và sessions_per_week đã được tính toán trước
                        while created_s < course_p.total_semester_sessions:
                            for sess_in_wk_num in range(1, course_p.sessions_per_week + 1): 
                                if created_s < course_p.total_semester_sessions:
                                    created_s += 1
                                    # sess_in_wk_num là buổi thứ mấy trong tuần của MÔN HỌC này (1-indexed)
                                    # curr_cwk là tuần thứ mấy của MÔN HỌC này (1-indexed)
                                    sess = ClassSessionInternal(grp_obj, curr_cwk, sess_in_wk_num, created_s)
                                    grp_obj.sessions.append(sess)
                                    all_sessions.append(sess)
                                else: break
                            curr_cwk += 1 
                            # Đảm bảo không vượt quá số tuần đã tính cho môn đó
                            if curr_cwk > course_p.calculated_total_weeks_for_course + 1: # +1 để an toàn
                                if created_s < course_p.total_semester_sessions: # Nếu vẫn chưa đủ session
                                    service_logger.error(f"Logic error: C{cs_id}G{grp_num} - Not enough sessions created within calculated weeks. "
                                                         f"Created: {created_s}/{course_p.total_semester_sessions}, "
                                                         f"CourseWeeks: {curr_cwk-1}/{course_p.calculated_total_weeks_for_course}")
                                    # Có thể raise lỗi ở đây hoặc cố gắng xếp tiếp, nhưng có thể gây INFEASIBLE
                                break 
            
            output_groups_dto = list(output_groups_dto_map.values())

            if not all_sessions:
                 return ScheduleResultDTO(classGroups=output_groups_dto, schedule=[], violations=["No sessions to schedule."],
                                        lecturerLoad=[], totalCourseSessionsToSchedule=0, 
                                        totalSemesterWeekSlots=num_total_sem_slots_per_resource,
                                        totalAvailableRoomSlotsInSemester=num_total_sem_slots_per_resource * num_rooms,
                                        lecturerPotentialLoad={}, loadDifference=0, detailedSuggestions=[])

            total_req_course_sessions = len(all_sessions)
            violations = [] 
            lect_potential_load: Dict[int, int] = {lect_id: 0 for lect_id in lecturer_id_to_idx.keys()}
            for l_user_id in lecturer_id_to_idx.keys():
                load = 0
                for cs_id_can_teach in lecturer_id_to_teaching_courses.get(l_user_id, []):
                    if cs_id_can_teach in processed_courses:
                        course_p_obj = processed_courses[cs_id_can_teach]
                        num_actual_grps_for_course = sum(1 for g_dto in output_groups_dto if g_dto.courseSemesterId == cs_id_can_teach)
                        load += course_p_obj.total_semester_sessions * num_actual_grps_for_course
                lect_potential_load[l_user_id] = load

            model = cp_model.CpModel()

            for grp_obj in internal_groups:
                props = grp_obj.course_props # props giờ là ProcessedCourseProps
                if props.calculated_total_weeks_for_course > 0 :
                    # Giới hạn trên cho start_semester_week_var vẫn dựa trên calculated_total_weeks_for_course
                    upper_b = max(0, total_semester_weeks - props.calculated_total_weeks_for_course) 
                    grp_obj.start_semester_week_var = model.NewIntVar(0, upper_b, f'start_sw_c{props.course_semester_id}_g{grp_obj.group_number}')
                    
                    grp_obj.fixed_weekly_slot_vars = []
                    fixed_slot_ids_for_group = [] 
                    # Số lượng fixed_weekly_slot_vars được tạo dựa trên sessions_per_week đã tính ở preprocessing
                    for i in range(props.sessions_per_week): 
                        day_var = model.NewIntVar(0, num_days_wk - 1, f'fx_day_c{props.course_semester_id}_g{grp_obj.group_number}_siw{i+1}')
                        shift_var = model.NewIntVar(0, num_shifts - 1, f'fx_sh_c{props.course_semester_id}_g{grp_obj.group_number}_siw{i+1}')
                        grp_obj.fixed_weekly_slot_vars.append((day_var, shift_var))
                        
                        fixed_weekly_slot_id_var = model.NewIntVar(0, num_wk_slots_unique - 1, 
                                                                  f'fx_slot_id_c{props.course_semester_id}_g{grp_obj.group_number}_siw{i+1}')
                        model.Add(fixed_weekly_slot_id_var == day_var * num_shifts + shift_var)
                        fixed_slot_ids_for_group.append(fixed_weekly_slot_id_var)

                    if len(fixed_slot_ids_for_group) > 1:
                        model.AddAllDifferent(fixed_slot_ids_for_group) 

            all_fixed_day_shift_violation_bools: List[cp_model.BoolVar] = []
            for sess in all_sessions:
                sess.slot_var = model.NewIntVar(0, num_total_sem_slots_per_resource - 1, f'{sess.id}_slot')
                sess.lecturer_var = model.NewIntVar(0, num_lect - 1, f'{sess.id}_lect')
                sess.room_var = model.NewIntVar(0, num_rooms - 1, f'{sess.id}_room')
                sess.assigned_semester_week_var = model.NewIntVar(0, total_semester_weeks - 1, f'{sess.id}_asg_sw')
                sess.is_fixed_day_shift_violated_var = model.NewBoolVar(f'{sess.id}_is_fixed_viol')
                all_fixed_day_shift_violation_bools.append(sess.is_fixed_day_shift_violated_var)

                start_wk_var = sess.class_group.start_semester_week_var
                if start_wk_var is not None: 
                    model.Add(sess.assigned_semester_week_var == start_wk_var + (sess.course_week_number - 1))
                
                slot_wk_comp_var = model.NewIntVar(0, total_semester_weeks - 1, f'{sess.id}_slot_wk_c')
                slot_day_comp_var = model.NewIntVar(0, num_days_wk -1, f'{sess.id}_slot_day_c')
                slot_shift_comp_var = model.NewIntVar(0, num_shifts - 1, f'{sess.id}_slot_sh_c')

                model.AddElement(sess.slot_var, [sem_slot_map[s_idx][0] for s_idx in range(num_total_sem_slots_per_resource)], slot_wk_comp_var)
                model.AddElement(sess.slot_var, [sem_slot_map[s_idx][1] for s_idx in range(num_total_sem_slots_per_resource)], slot_day_comp_var)
                model.AddElement(sess.slot_var, [sem_slot_map[s_idx][2] for s_idx in range(num_total_sem_slots_per_resource)], slot_shift_comp_var)
                model.Add(slot_wk_comp_var == sess.assigned_semester_week_var)

                session_in_week_idx = sess.session_in_course_week - 1 
                if session_in_week_idx < len(sess.class_group.fixed_weekly_slot_vars):
                    fixed_day_var, fixed_shift_var = sess.class_group.fixed_weekly_slot_vars[session_in_week_idx]
                    if fixed_day_var is not None and fixed_shift_var is not None:
                        day_diff_abs = model.NewIntVar(0, num_days_wk -1, f'{sess.id}_day_diff_abs')
                        shift_diff_abs = model.NewIntVar(0, num_shifts -1, f'{sess.id}_shift_diff_abs')
                        model.AddAbsEquality(day_diff_abs, slot_day_comp_var - fixed_day_var)
                        model.AddAbsEquality(shift_diff_abs, slot_shift_comp_var - fixed_shift_var)
                        sum_diff = model.NewIntVar(0, num_days_wk + num_shifts -1, f'{sess.id}_sum_diff')
                        model.Add(sum_diff == day_diff_abs + shift_diff_abs)
                        model.Add(sum_diff > 0).OnlyEnforceIf(sess.is_fixed_day_shift_violated_var)
                        model.Add(sum_diff == 0).OnlyEnforceIf(sess.is_fixed_day_shift_violated_var.Not())
                    else: model.Add(sess.is_fixed_day_shift_violated_var == False) 
                else: model.Add(sess.is_fixed_day_shift_violated_var == False)

            # --- 4. Define Constraints ---
            # (Giữ nguyên các ràng buộc RB1-RB5)
            # ... (RB1) ...
            for sess in all_sessions: 
                c_id = sess.class_group.course_props.course_semester_id
                allowed_l_indices = [l_idx for l_idx, luid in lecturer_idx_to_id.items() if c_id in lecturer_id_to_teaching_courses.get(luid, [])]
                if not allowed_l_indices: raise HTTPException(status_code=400, detail=f"No lecturer for C{c_id}")
                if sess.lecturer_var is not None: model.AddAllowedAssignments([sess.lecturer_var], [(lidx,) for lidx in allowed_l_indices])

            # ... (RB_SingleLecturerPerGroup) ...
            for grp_obj in internal_groups:
                if grp_obj.sessions and len(grp_obj.sessions) > 1:
                    ref_lect_var = grp_obj.sessions[0].lecturer_var
                    if ref_lect_var is not None:
                        for i in range(1, len(grp_obj.sessions)): 
                            if grp_obj.sessions[i].lecturer_var is not None:
                                model.Add(grp_obj.sessions[i].lecturer_var == ref_lect_var)
            
            # ... (RB2) ...
            room_caps_consts = [model.NewConstant(cap) for cap in room_caps_list]
            for sess in all_sessions:
                stud_c = sess.class_group.registered_students
                rcap_var = model.NewIntVar(0, max(room_caps_list) if room_caps_list else 0, f'{sess.id}_rcap')
                if sess.room_var is not None:
                    model.AddElement(sess.room_var, room_caps_consts, rcap_var)
                    model.Add(rcap_var >= stud_c)

            # ... (RB3) ...
            for grp_obj in internal_groups:
                # limit bây giờ là props.sessions_per_week (đã được tính toán trước)
                limit = grp_obj.course_props.sessions_per_week
                for sem_wk_idx in range(total_semester_weeks):
                    bools = []
                    for sess_obj in grp_obj.sessions:
                        if sess_obj.assigned_semester_week_var is not None:
                            b = model.NewBoolVar(f'g{grp_obj.group_number}_c{grp_obj.course_props.course_semester_id}_s{sess_obj.overall_session_sequence_num}_in_semwk{sem_wk_idx}')
                            model.Add(sess_obj.assigned_semester_week_var == sem_wk_idx).OnlyEnforceIf(b)
                            model.Add(sess_obj.assigned_semester_week_var != sem_wk_idx).OnlyEnforceIf(b.Not())
                            bools.append(b)
                    if bools: model.Add(sum(bools) <= limit) # Số session của nhóm trong 1 tuần học kỳ <= sessions_per_week của nhóm đó
            
            # ... (RB4) ...
            for grp_obj in internal_groups:
                if grp_obj.course_props.sessions_per_week > 1: # Chỉ cần AddAllDifferent nếu một nhóm có > 1 buổi/tuần
                    sess_by_cwk: Dict[int, List[ClassSessionInternal]] = {}
                    for s_obj in grp_obj.sessions: sess_by_cwk.setdefault(s_obj.course_week_number, []).append(s_obj)
                    for _, sessions_in_cwk in sess_by_cwk.items():
                        # sessions_in_cwk là list các session của cùng 1 group, trong cùng 1 course_week
                        # (ví dụ, 2 session của môn X, nhóm 1, trong tuần thứ 3 của môn X)
                        # Các slot_var của chúng phải khác nhau.
                        slots = [s.slot_var for s in sessions_in_cwk if s.slot_var is not None]
                        if len(slots) > 1: model.AddAllDifferent(slots)

            # ... (RB5 NoOverlap2D) ...
            lx_ivs, ly_ivs, rx_ivs, ry_ivs = [], [], [], []
            s1_const = model.NewConstant(1)
            for sess in all_sessions:
                if sess.lecturer_var is None or sess.slot_var is None or sess.room_var is None: continue
                lx_e, ly_e, rx_e = model.NewIntVar(0,num_lect,''), model.NewIntVar(0,num_total_sem_slots_per_resource,''), model.NewIntVar(0,num_rooms,'')
                model.Add(lx_e == sess.lecturer_var + s1_const); model.Add(ly_e == sess.slot_var + s1_const); model.Add(rx_e == sess.room_var + s1_const)
                lx_ivs.append(model.NewIntervalVar(sess.lecturer_var, s1_const, lx_e, f'{sess.id}_lxi_no_final4')); ly_ivs.append(model.NewIntervalVar(sess.slot_var, s1_const, ly_e, f'{sess.id}_lyi_no_final4'))
                rx_ivs.append(model.NewIntervalVar(sess.room_var, s1_const, rx_e, f'{sess.id}_rxi_no_final4')); ry_ivs.append(model.NewIntervalVar(sess.slot_var, s1_const, ly_e, f'{sess.id}_ryi_no_final4'))
            if lx_ivs: model.AddNoOverlap2D(lx_ivs, ly_ivs)
            if rx_ivs: model.AddNoOverlap2D(rx_ivs, ry_ivs)


            # --- 5. Define Objective Function ---
            # (Giữ nguyên như phiên bản trước)
            actual_lecturer_loads_vars = []
            objective_terms = []

            total_fixed_day_shift_violations_obj_var = model.NewIntVar(0, len(all_sessions) + 1, 'total_fixed_day_shift_violations_obj')
            valid_violation_bools_for_obj = [v for v in all_fixed_day_shift_violation_bools if v is not None]
            if valid_violation_bools_for_obj:
                model.Add(total_fixed_day_shift_violations_obj_var == sum(valid_violation_bools_for_obj))
            else:
                model.Add(total_fixed_day_shift_violations_obj_var == 0)

            weighted_fixed_violations = model.NewIntVar(0, (len(all_sessions) + 1) * input_dto.penaltyWeightFixedDayShiftViolation, 'weighted_fixed_viol_obj')
            model.AddMultiplicationEquality(weighted_fixed_violations, total_fixed_day_shift_violations_obj_var, input_dto.penaltyWeightFixedDayShiftViolation)
            objective_terms.append(weighted_fixed_violations)
            
            if input_dto.objectiveStrategy != "FEASIBLE_ONLY":
                if num_lect > 0 and total_req_course_sessions > 0: 
                    actual_lecturer_loads_vars = [model.NewIntVar(0, total_req_course_sessions, f'al_l{i}') for i in range(num_lect)]
                    for l_idx in range(num_lect):
                        asg = []
                        for s_obj in all_sessions:
                            if s_obj.lecturer_var is not None:
                                b = model.NewBoolVar(f'{s_obj.id}_al_obj_{l_idx}')
                                model.Add(s_obj.lecturer_var == l_idx).OnlyEnforceIf(b)
                                model.Add(s_obj.lecturer_var != l_idx).OnlyEnforceIf(b.Not())
                                asg.append(b)
                        if asg: model.Add(actual_lecturer_loads_vars[l_idx] == sum(asg))
                        else: model.Add(actual_lecturer_loads_vars[l_idx] == 0)
                    
                    if "BALANCE_LOAD" in input_dto.objectiveStrategy.upper() and actual_lecturer_loads_vars:
                        max_l, min_l = model.NewIntVar(0,total_req_course_sessions,'maxl_obj'), model.NewIntVar(0,total_req_course_sessions,'minl_obj')
                        model.AddMaxEquality(max_l, actual_lecturer_loads_vars); model.AddMinEquality(min_l, actual_lecturer_loads_vars)
                        load_diff_term = model.NewIntVar(0, total_req_course_sessions, 'ld_term_obj'); model.Add(load_diff_term == max_l - min_l)
                        objective_terms.append(load_diff_term) 

                    if "EARLY_START" in input_dto.objectiveStrategy.upper():
                        valid_assigned_week_vars = [s.assigned_semester_week_var for s in all_sessions if s.assigned_semester_week_var is not None]
                        if valid_assigned_week_vars: 
                            sum_of_sw = model.NewIntVar(0, total_semester_weeks * len(all_sessions) +1, 'sum_sw_obj') 
                            model.Add(sum_of_sw == sum(valid_assigned_week_vars))
                            objective_terms.append(sum_of_sw) 
            
            if objective_terms:
                max_possible_obj_val = ((len(all_sessions)+1) * input_dto.penaltyWeightFixedDayShiftViolation + 
                                        total_req_course_sessions + total_semester_weeks * len(all_sessions) +1 )
                total_objective_var = model.NewIntVar(0, max_possible_obj_val , 'total_obj_final') 
                model.Add(total_objective_var == sum(objective_terms))
                model.Minimize(total_objective_var)


            # --- 6. Solve the Model ---
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = input_dto.solverTimeLimitSeconds
            solver.parameters.log_search_progress = True 
            status = solver.Solve(model)

            # --- 7. Process Solution ---
            # (Logic xử lý kết quả và điền DTO output giữ nguyên như phiên bản trước đó bạn đã có kết quả tốt)
            # ... (Bao gồm việc lấy giá trị solved_fixed_weekly_slots_map và điền fixedDayShiftViolations) ...
            final_sched: List[ScheduleEntryDTO] = []
            final_l_load: List[LecturerLoadDTO] = []
            load_diff_val: Optional[int] = None
            detailed_suggestions: List[ViolationDetailDTO] = [] 
            solved_start_weeks: Dict[Tuple[int, int], int] = {}
            solved_fixed_weekly_slots_map: Dict[Tuple[int, int], List[Tuple[int, int]]] = {}


            if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
                service_logger.info("Solution found by solver.")
                
                for grp_obj in internal_groups:
                    grp_key = (grp_obj.course_props.course_semester_id, grp_obj.group_number)
                    if grp_obj.start_semester_week_var is not None:
                        try: solved_start_weeks[grp_key] = solver.Value(grp_obj.start_semester_week_var)
                        except: pass
                    
                    grp_fixed_slots_values = []
                    if hasattr(grp_obj, 'fixed_weekly_slot_vars'): # Kiểm tra thuộc tính tồn tại
                        for day_var, shift_var in grp_obj.fixed_weekly_slot_vars:
                            day_val, shift_val = -1, -1 
                            if day_var is not None:
                                try: day_val = solver.Value(day_var)
                                except: pass
                            if shift_var is not None:
                                try: shift_val = solver.Value(shift_var)
                                except: pass
                            grp_fixed_slots_values.append((day_val, shift_val))
                    if grp_fixed_slots_values : solved_fixed_weekly_slots_map[grp_key] = grp_fixed_slots_values
                
                total_fixed_violations_found_in_sol = 0
                try:
                    if valid_violation_bools_for_obj:
                         total_fixed_violations_found_in_sol = solver.Value(total_fixed_day_shift_violations_obj_var)
                         service_logger.info(f"Total fixed day/shift violations in solution (from objective): {total_fixed_violations_found_in_sol}")
                except: pass

                for grp_dto_idx, grp_dto in enumerate(output_groups_dto):
                    grp_key = (grp_dto.courseSemesterId, grp_dto.groupNumber)
                    internal_grp_props = processed_courses.get(grp_dto.courseSemesterId) # Lấy ProcessedCourseProps
                    
                    retrieved_fixed_slots = solved_fixed_weekly_slots_map.get(grp_key, [])
                    grp_dto.assignedFixedWeeklySlots = [] 
                    if internal_grp_props: # Cần props để biết sessions_per_week
                        for i in range(internal_grp_props.sessions_per_week):
                            day_str, shift_str = None, None
                            if i < len(retrieved_fixed_slots):
                                day_idx, shift_idx = retrieved_fixed_slots[i]
                                if day_idx != -1 and day_idx is not None: day_str = day_idx_to_str.get(day_idx)
                                if shift_idx != -1 and shift_idx is not None: shift_str = model_shift_idx_to_str.get(shift_idx)
                            grp_dto.assignedFixedWeeklySlots.append(FixedSlotInfo(sessionSequenceInWeek=i+1, day=day_str, shift=shift_str))
                    
                    current_internal_group = next((ig for ig in internal_groups if ig.course_props.course_semester_id == grp_key[0] and ig.group_number == grp_key[1]), None)
                    if current_internal_group:
                        group_violation_count_for_this_group = 0
                        for sess_obj in current_internal_group.sessions:
                            if sess_obj.is_fixed_day_shift_violated_var is not None:
                                try:
                                    if solver.Value(sess_obj.is_fixed_day_shift_violated_var):
                                        group_violation_count_for_this_group +=1
                                        actual_slot_val = solver.Value(sess_obj.slot_var)
                                        _, actual_day_idx, actual_shift_idx = sem_slot_map[actual_slot_val]
                                        actual_day_str = day_idx_to_str[actual_day_idx]
                                        actual_shift_str = model_shift_idx_to_str[actual_shift_idx]
                                        
                                        target_day_str, target_shift_str = "N/A", "N/A"
                                        sess_in_week_idx = sess_obj.session_in_course_week - 1
                                        if sess_in_week_idx < len(grp_dto.assignedFixedWeeklySlots):
                                            target_slot_info = grp_dto.assignedFixedWeeklySlots[sess_in_week_idx]
                                            target_day_str = target_slot_info.day or "N/A"
                                            target_shift_str = target_slot_info.shift or "N/A"

                                        grp_dto.fixedDayShiftViolations.append({
                                            "sessionOverallSequence": sess_obj.overall_session_sequence_num,
                                            "sessionInCourseWeek": sess_obj.session_in_course_week,
                                            "scheduledDay": actual_day_str, 
                                            "scheduledShift": actual_shift_str,
                                            "message": f"Sess {sess_obj.overall_session_sequence_num} (buổi {sess_obj.session_in_course_week}/tuần) on {actual_day_str}-{actual_shift_str} instead of fixed {target_day_str}-{target_shift_str}"
                                        })
                                except : pass 
                        
                        if group_violation_count_for_this_group > 0:
                             fixed_slots_str = "; ".join([f"Buổi {fs.sessionSequenceInWeek}: {fs.day or 'N/A'}-{fs.shift or 'N/A'}" for fs in grp_dto.assignedFixedWeeklySlots])
                             detailed_suggestions.append(ViolationDetailDTO(
                                 constraintType="FixedDayShiftSoftViolation",
                                 description=f"C{grp_key[0]}G{grp_key[1]} ({group_violation_count_for_this_group} session(s) deviate) from its assigned target weekly slots: [{fixed_slots_str}].",
                                 affectedItems=[f"C{grp_key[0]}G{grp_key[1]}"],
                                 suggestedAction="This group could not be perfectly fixed for all its weekly sessions. Review its detailed violations. Consider if this deviation is acceptable, or if resources are too constrained for these target slots, or if this group needs more flexibility."
                             ))
                
                for grp_dto in output_groups_dto: 
                    start_wk_idx = solved_start_weeks.get((grp_dto.courseSemesterId, grp_dto.groupNumber))
                    course_p = processed_courses.get(grp_dto.courseSemesterId)
                    if start_wk_idx is not None and course_p and course_p.calculated_total_weeks_for_course > 0:
                        grp_dto.startSemesterWeek = start_wk_idx + 1
                        grp_dto.totalTeachingWeeks = course_p.calculated_total_weeks_for_course
                        grp_dto.endSemesterWeek = grp_dto.startSemesterWeek + grp_dto.totalTeachingWeeks - 1
                        grp_start_date = start_date_obj + timedelta(weeks=start_wk_idx)
                        grp_end_date_week_start = start_date_obj + timedelta(weeks=start_wk_idx + grp_dto.totalTeachingWeeks - 1)
                        grp_dto.startDate = grp_start_date.strftime("%Y-%m-%d")
                        grp_dto.endDate = (grp_end_date_week_start + timedelta(days=6)).strftime("%Y-%m-%d")

                for s in all_sessions:
                    try:
                        slot_v, lect_idx_v, room_idx_v = solver.Value(s.slot_var), solver.Value(s.lecturer_var), solver.Value(s.room_var)
                        sem_wk_v, day_idx_v, sh_idx_v = sem_slot_map[slot_v] 
                        final_sched.append(ScheduleEntryDTO(
                            courseSemesterId=s.class_group.course_props.course_semester_id, groupNumber=s.class_group.group_number,
                            semesterWeek=sem_wk_v + 1, sessionSequenceInWeek=s.session_in_course_week, overallSessionSequence=s.overall_session_sequence_num,
                            shift=model_shift_idx_to_str[sh_idx_v], room=room_idx_to_name[room_idx_v], lecturerId=lecturer_idx_to_id[lect_idx_v], day=day_idx_to_str[day_idx_v] ))
                    except: violations.append(f"Error processing session {s.id}")

                if actual_lecturer_loads_vars:
                    try:
                        actual_loads = [solver.Value(lv) for lv in actual_lecturer_loads_vars]
                        for lidx, load_val in enumerate(actual_loads): final_l_load.append(LecturerLoadDTO(lecturerId=lecturer_idx_to_id[lidx], sessionsAssigned=load_val))
                        if actual_loads: load_diff_val = max(actual_loads) - min(actual_loads)
                    except: violations.append("Error processing lecturer loads")


            elif status == cp_model.INFEASIBLE : 
                violations.append("INFEASIBLE: Critical constraints conflict. Even allowing deviations from fixed day/shift, no solution was found.")
                detailed_suggestions.append(ViolationDetailDTO(
                    constraintType="CoreFeasibility",
                    description="The solver could not find any schedule satisfying all core constraints (NoOverlap, qualifications, room capacity, etc.), even when day/shift fixing was treated as soft.",
                    suggestedAction="This is a serious issue. Review: 1. Are there enough rooms/lecturers for the total number of sessions? 2. Are lecturer qualifications correctly assigned to courses? 3. Are room capacities sufficient for class sizes? 4. Is the semester long enough for all courses? 5. Check for logical errors in constraint definitions."
                 ))
            else: 
                violations.append(f"Solver status: {solver.StatusName(status)}. No optimal or feasible solution guaranteed.")
                if status == cp_model.MODEL_INVALID:
                    detailed_suggestions.append(ViolationDetailDTO(constraintType="ModelInvalid", description="CP-SAT model issue. Check logs.", suggestedAction="Review model code."))

            if not final_l_load and num_lect > 0:
                for l_id_key in lecturer_id_to_idx.keys(): final_l_load.append(LecturerLoadDTO(lecturerId=l_id_key, sessionsAssigned=0))

            return ScheduleResultDTO(
                classGroups=output_groups_dto, schedule=final_sched, violations=violations,
                lecturerLoad=final_l_load, loadDifference=load_diff_val,
                totalCourseSessionsToSchedule=total_req_course_sessions,
                totalSemesterWeekSlots=num_total_sem_slots_per_resource, 
                totalAvailableRoomSlotsInSemester=num_total_sem_slots_per_resource * num_rooms,
                lecturerPotentialLoad=lect_potential_load, detailedSuggestions=detailed_suggestions
            )

        except ValidationError as e:
            service_logger.error(f"Pydantic Val Err: {e.errors()}", exc_info=False) 
            raise HTTPException(status_code=422, detail=e.errors())
        except HTTPException as he:
            service_logger.error(f"HTTPException in service: Status {he.status_code}, Detail: {he.detail}", exc_info=False)
            raise he
        except ValueError as ve: 
            service_logger.error(f"ValueError in service: {str(ve)}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Bad request or internal logic error: {str(ve)}")
        except Exception as e:
            service_logger.critical(f"UNEXPECTED SERVICE ERROR: {type(e).__name__} - {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {type(e).__name__} - {str(e)}")