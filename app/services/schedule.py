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

def get_semester_week_and_day_indices(
    target_date: date, semester_start_date: date, days_of_week_map: Dict[str, int]
) -> Tuple[Optional[int], Optional[int]]:
    """
    Tính toán semester_week_index (0-based) và day_index (0-based theo days_of_week_map)
    cho một target_date dựa trên semester_start_date.
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
    return None, None

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
    objectiveStrategy: List[str] = Field(
        default_factory=lambda: [
            EObjectStrategy.BALANCE_LOAD.value, 
            EObjectStrategy.EARLY_START.value, 
        ]
    )
    
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
            if start_str and date.fromisoformat(v_end_date) <= date.fromisoformat(start_str):
                raise ValueError("semesterEndDate must be after semesterStartDate")
        return v_end_date
    
# --- DTOs for Output ---
class LecturerLoadDTO(BaseModel):
    lecturerId: int
    sessionsAssigned: int

class WeeklyScheduleDetailDTO(BaseModel):  
    dayOfWeek: str 
    timeSlotId: int 
    roomId: int  
    scheduledDates: List[str] 

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
        self.courseId, self.credits, self.totalSemesterSessions, self.registeredStudents, self.potentialLecturerIds, self.sessionsPerWeek, self.totalCourseWeeks = course_dto.courseId, course_dto.credits, course_dto.totalSemesterSessions, course_dto.registeredStudents, course_dto.potentialLecturerIds, sessions_p_week, total_course_weeks

class SchedulingGroupInternal: 
    def __init__(self, group_id_tuple: Tuple[int, int, int], course_props: CoursePropertiesInternal, actual_students_in_group: int):
        self.id_tuple = group_id_tuple
        self.course_props = course_props
        self.actual_students_in_group = actual_students_in_group
        self.sessions_to_schedule: List[SessionInternal] = []  
        self.assigned_lecturer_var: Optional[cp_model.IntVar] = None
        self.fixed_day_var: Optional[cp_model.IntVar] = None
        self.fixed_shift_var: Optional[cp_model.IntVar] = None
        self.fixed_room_var: Optional[cp_model.IntVar] = None
    def __repr__(self): return f"SchedGrp(C{self.id_tuple[0]}, G{self.id_tuple[2]})"

class SessionInternal: 
    def __init__(self, group: SchedulingGroupInternal, overall_session_seq_num: int): 
        self.group = group
        self.overall_session_sequence_number = overall_session_seq_num
        self.id_str = f"s_c{group.id_tuple[0]}g{group.id_tuple[2]}seq{overall_session_seq_num}"
        self.assigned_global_slot_var: Optional[cp_model.IntVar] = None  
        self.assigned_semester_week_idx_var: Optional[cp_model.IntVar] = None
    def __repr__(self): return self.id_str

# --- Schedule Service ---
class ScheduleService:
    @staticmethod
    def _get_sessions_per_week(*args, **kwargs) -> Tuple[int, int]:
        total_sessions = args[0]
        return 1, total_sessions

    @staticmethod
    async def calculate_with_cp(input_dto: ScheduleInputDTO) -> FinalScheduleResultDTO:
        start_time_measurement = time.time()
        logger = logging.getLogger(f"{ScheduleService.__module__}.{ScheduleService.__name__}.calculate_with_cp")
        logger.info(f"Scheduling request for Semester ID: {input_dto.semesterId}")
        try:
            # --- 1. Basic Date & Time Setup ---
            semester_start_date_obj = date.fromisoformat(input_dto.semesterStartDate)
            semester_end_date_obj = date.fromisoformat(input_dto.semesterEndDate)
            num_calendar_days_in_semester = (semester_end_date_obj - semester_start_date_obj).days + 1
            total_calendar_weeks = math.ceil(num_calendar_days_in_semester / 7) 
            
            lecturer_id_to_idx = {l.lecturerId: i for i, l in enumerate(input_dto.lecturers)}
            lecturer_idx_to_id = {i: l.lecturerId for i, l in enumerate(input_dto.lecturers)}
            num_lecturers = len(input_dto.lecturers)
            
            room_id_to_idx = {r.id: i for i, r in enumerate(input_dto.rooms)}
            room_idx_to_id = {i: r.id for i, r in enumerate(input_dto.rooms)}
            room_capacities_by_idx = [r.capacity for r in input_dto.rooms]
            num_rooms = len(input_dto.rooms)
            if num_rooms == 0: raise ValueError("No rooms provided for scheduling.")
            
            timeslot_id_to_idx = {ts.id: i for i, ts in enumerate(input_dto.timeSlots)}
            timeslot_idx_to_id = {i: ts.id for i, ts in enumerate(input_dto.timeSlots)}
            num_shifts_per_day = len(input_dto.timeSlots)
            if num_shifts_per_day == 0: raise ValueError("No time slots provided.")
            
            day_name_to_idx = {day_name: i for i, day_name in enumerate(input_dto.daysOfWeek)}
            day_idx_to_name = {i: day_name for i, day_name in enumerate(input_dto.daysOfWeek)}
            num_days_per_week = len(input_dto.daysOfWeek)
            if num_days_per_week == 0: raise ValueError("No days of week provided for scheduling.")

            # --- 2. Pre-process Course Information & Create Scheduling Groups ---
            all_scheduling_groups: List[SchedulingGroupInternal] = []
            all_sessions_to_schedule: List[SessionInternal] = []
            course_properties_map: Dict[int, CoursePropertiesInternal] = {}

            for cs_info_dto in input_dto.coursesToSchedule:
                sessions_p_week, calc_total_course_wks = ScheduleService._get_sessions_per_week(cs_info_dto.totalSemesterSessions, total_calendar_weeks, input_dto.maxSessionsPerWeekAllowed, cs_info_dto.courseId, cs_info_dto.credits)
                course_properties_map[cs_info_dto.courseId] = CoursePropertiesInternal(cs_info_dto, sessions_p_week, calc_total_course_wks)
                course_props = course_properties_map[cs_info_dto.courseId]
                if course_props.registeredStudents <= 0 or course_props.totalSemesterSessions <= 0: continue
                
                num_groups_for_course = math.ceil(course_props.registeredStudents / input_dto.groupSizeTarget)
                if num_groups_for_course == 0 and course_props.registeredStudents > 0: num_groups_for_course = 1
                elif num_groups_for_course == 0: continue
                
                base_students_per_group, remaining_students = divmod(course_props.registeredStudents, num_groups_for_course)
                for grp_idx in range(num_groups_for_course):
                    students_in_this_group = base_students_per_group + (1 if grp_idx < remaining_students else 0)
                    if students_in_this_group == 0: continue
                    sched_group = SchedulingGroupInternal((cs_info_dto.courseId, input_dto.semesterId, grp_idx + 1), course_props, students_in_this_group)
                    all_scheduling_groups.append(sched_group)
                    for i in range(course_props.totalSemesterSessions):
                        session_obj = SessionInternal(sched_group, overall_session_seq_num=i + 1)
                        sched_group.sessions_to_schedule.append(session_obj)
                        all_sessions_to_schedule.append(session_obj)
            
            if not all_sessions_to_schedule:
                logger.info("No sessions to schedule after processing input.")
                duration_s = time.time() - start_time_measurement
                empty_lecturer_loads = [LecturerLoadDTO(lecturerId=l.lecturerId, sessionsAssigned=0) for l in input_dto.lecturers]
                return FinalScheduleResultDTO(
                    semesterId=input_dto.semesterId, semesterStartDate=input_dto.semesterStartDate, semesterEndDate=input_dto.semesterEndDate,
                    scheduledCourses=[], lecturerLoad=empty_lecturer_loads, loadDifference=None,
                    totalOriginalSessionsToSchedule=0, solverDurationSeconds=duration_s,  
                    solverStatus="NO_SESSIONS_TO_SCHEDULE", 
                    solverMessage="No sessions to schedule after processing input. All inputs are valid but result in zero scheduling tasks."
                )
            
            total_sessions_count = len(all_sessions_to_schedule)
            logger.info(f"Total {len(all_scheduling_groups)} groups and {total_sessions_count} sessions created.")

            # --- 3. Define Global Slot Mappings & Handle Exclusions (Holidays, Occupied) ---
            active_slot_details_list, date_to_swk_day_map = [], {}
            for day_offset in range(num_calendar_days_in_semester):
                current_iter_date = semester_start_date_obj + timedelta(days=day_offset)
                if current_iter_date.strftime("%Y-%m-%d") in input_dto.exceptionDates: continue
                smw_idx, d_idx = get_semester_week_and_day_indices(current_iter_date, semester_start_date_obj, day_name_to_idx)
                if smw_idx is not None and d_idx is not None:
                    date_to_swk_day_map[current_iter_date] = (smw_idx, d_idx)
                    for sh_idx in range(num_shifts_per_day): active_slot_details_list.append((smw_idx, d_idx, sh_idx))
            
            active_slot_details_list.sort()
            swk_day_to_date_map = {v: k for k, v in date_to_swk_day_map.items()}
            global_slot_to_details, details_to_global_slot, valid_global_slot_indices = {}, {}, []
            for idx, details in enumerate(active_slot_details_list):
                global_slot_to_details[idx] = details
                details_to_global_slot[details] = idx
                valid_global_slot_indices.append(idx)
            num_total_active_slots = len(valid_global_slot_indices)
            if num_total_active_slots == 0: raise ValueError("No active scheduling slots available.")

            occupied_slots_by_room: Dict[int, set] = {i: set() for i in range(num_rooms)}
            occupied_slots_by_lecturer: Dict[int, set] = {i: set() for i in range(num_lecturers)}
            
            for rec in input_dto.existingSchedules:
                try:
                    start_date, end_date = date.fromisoformat(rec.startDate), date.fromisoformat(rec.endDate)
                    day_name, ts_id = rec.dayOfWeek, rec.timeSlotId
                    if day_name not in day_name_to_idx: continue
                    day_idx, ts_idx = day_name_to_idx[day_name], timeslot_id_to_idx.get(ts_id)
                    if ts_idx is None: continue
                    current_date = start_date
                    while current_date <= end_date:
                        if current_date.strftime("%Y-%m-%d") not in input_dto.exceptionDates:
                            smw_idx, d_idx_iter = get_semester_week_and_day_indices(current_date, semester_start_date_obj, day_name_to_idx)
                            if smw_idx is not None and d_idx_iter == day_idx:
                                gs_idx = details_to_global_slot.get((smw_idx, d_idx_iter, ts_idx))
                                if gs_idx is not None:
                                    r_idx, l_idx = room_id_to_idx.get(rec.roomId), lecturer_id_to_idx.get(rec.lecturerId)
                                    if r_idx is not None: occupied_slots_by_room[r_idx].add(gs_idx)
                                    if l_idx is not None: occupied_slots_by_lecturer[l_idx].add(gs_idx)
                        current_date += timedelta(days=1)
                except Exception as e: logger.error(f"Error processing existing schedule record {rec}: {e}", exc_info=True)

            for occ in input_dto.occupiedSlots:
                try:
                    occ_date_obj = date.fromisoformat(occ.date)
                    if occ_date_obj.strftime("%Y-%m-%d") in input_dto.exceptionDates: continue
                    swk_idx, d_idx = date_to_swk_day_map.get(occ_date_obj, (None, None))
                    sh_idx = timeslot_id_to_idx.get(occ.timeSlotId)
                    if swk_idx is not None and d_idx is not None and sh_idx is not None:
                        gs_idx = details_to_global_slot.get((swk_idx, d_idx, sh_idx))
                        if gs_idx is not None:
                            if occ.resourceType == 'room':
                                res_id = int(occ.resourceId) if isinstance(occ.resourceId, str) and occ.resourceId.isdigit() else occ.resourceId
                                r_idx = room_id_to_idx.get(res_id)
                                if r_idx is not None: occupied_slots_by_room[r_idx].add(gs_idx)
                            elif occ.resourceType == 'lecturer':
                                res_id = int(occ.resourceId) if isinstance(occ.resourceId, str) and occ.resourceId.isdigit() else occ.resourceId
                                l_idx = lecturer_id_to_idx.get(res_id)
                                if l_idx is not None: occupied_slots_by_lecturer[l_idx].add(gs_idx)
                except Exception as e: logger.warning(f"Error processing occupied slot {occ}: {e}")

            total_occ_room_slots = sum(len(s) for s in occupied_slots_by_room.values())
            total_occ_lect_slots = sum(len(s) for s in occupied_slots_by_lecturer.values())
            logger.info(f"Identified {total_occ_room_slots} occupied room slots and {total_occ_lect_slots} lecturer slots.")

            # --- 4. Create CP Model and Variables ---
            model = cp_model.CpModel()
            for group in all_scheduling_groups:
                course_p = group.course_props
                potential_lect_indices = [lecturer_id_to_idx[l_id] for l_id in course_p.potentialLecturerIds if l_id in lecturer_id_to_idx]
                if not potential_lect_indices: raise ValueError(f"No potential lecturers for C{course_p.courseId}.")
                group.assigned_lecturer_var = model.NewIntVar(0, num_lecturers - 1, f'grp_lect_{group.id_tuple}')
                model.AddAllowedAssignments([group.assigned_lecturer_var], [(l_idx,) for l_idx in potential_lect_indices])
                group.fixed_day_var = model.NewIntVar(0, num_days_per_week - 1, f'grp_day_{group.id_tuple}')
                group.fixed_shift_var = model.NewIntVar(0, num_shifts_per_day - 1, f'grp_shift_{group.id_tuple}')
                group.fixed_room_var = model.NewIntVar(0, num_rooms - 1, f'grp_room_{group.id_tuple}')
            
            for session in all_sessions_to_schedule:
                group = session.group
                session.assigned_global_slot_var = model.NewIntVarFromDomain(cp_model.Domain.FromValues(valid_global_slot_indices), f'sess_gs_{session.id_str}')
                session.assigned_semester_week_idx_var = model.NewIntVar(0, total_calendar_weeks - 1, f'sess_week_{session.id_str}')
                
                day_of_gs = model.NewIntVar(0, num_days_per_week - 1, f'day_gs_{session.id_str}')
                model.AddElement(session.assigned_global_slot_var, [d[1] for d in global_slot_to_details.values()], day_of_gs)
                model.Add(day_of_gs == group.fixed_day_var)
                
                shift_of_gs = model.NewIntVar(0, num_shifts_per_day - 1, f'shift_gs_{session.id_str}')
                model.AddElement(session.assigned_global_slot_var, [d[2] for d in global_slot_to_details.values()], shift_of_gs)
                model.Add(shift_of_gs == group.fixed_shift_var)

                model.AddElement(session.assigned_global_slot_var, [d[0] for d in global_slot_to_details.values()], session.assigned_semester_week_idx_var)

            # --- 5. Define Constraints ---
            logger.info("Defining constraints...")
            for group in all_scheduling_groups:
                if len(group.sessions_to_schedule) > 1: model.AddAllDifferent([s.assigned_global_slot_var for s in group.sessions_to_schedule])
                capacity_var = model.NewIntVar(0, max(room_capacities_by_idx) if room_capacities_by_idx else 0, f'cap_g{group.id_tuple}')
                model.AddElement(group.fixed_room_var, room_capacities_by_idx, capacity_var)
                model.Add(capacity_var >= group.actual_students_in_group)
            
            for group in all_scheduling_groups:
                for lect_idx, occupied_slots in occupied_slots_by_lecturer.items():
                    if not occupied_slots: continue
                    is_this_lecturer_var = model.NewBoolVar(f"is_lect_{lect_idx}_grp{group.id_tuple}")
                    model.Add(group.assigned_lecturer_var == lect_idx).OnlyEnforceIf(is_this_lecturer_var)
                    model.Add(group.assigned_lecturer_var != lect_idx).OnlyEnforceIf(is_this_lecturer_var.Not())
                    for session in group.sessions_to_schedule:
                        model.AddForbiddenAssignments([session.assigned_global_slot_var], [(s,) for s in occupied_slots]).OnlyEnforceIf(is_this_lecturer_var)

                for room_idx, occupied_slots in occupied_slots_by_room.items():
                    if not occupied_slots: continue
                    is_this_room_var = model.NewBoolVar(f"is_room_{room_idx}_grp{group.id_tuple}")
                    model.Add(group.fixed_room_var == room_idx).OnlyEnforceIf(is_this_room_var)
                    model.Add(group.fixed_room_var != room_idx).OnlyEnforceIf(is_this_room_var.Not())
                    for session in group.sessions_to_schedule:
                        model.AddForbiddenAssignments([session.assigned_global_slot_var], [(s,) for s in occupied_slots]).OnlyEnforceIf(is_this_room_var)

            lecturer_intervals_x, lecturer_intervals_y, room_intervals_x, room_intervals_y = [], [], [], []
            size_one = model.NewConstant(1)
            for session in all_sessions_to_schedule:
                g = session.group
                l_end = model.NewIntVar(0, num_lecturers, f"LEND_{session.id_str}"); model.Add(l_end == g.assigned_lecturer_var + 1)
                gs_end_l = model.NewIntVar(0, num_total_active_slots, f"GSLEND_L_{session.id_str}"); model.Add(gs_end_l == session.assigned_global_slot_var + 1)
                lecturer_intervals_x.append(model.NewIntervalVar(g.assigned_lecturer_var, size_one, l_end, f"LXV_{session.id_str}"))
                lecturer_intervals_y.append(model.NewIntervalVar(session.assigned_global_slot_var, size_one, gs_end_l, f"LYV_{session.id_str}"))
                
                r_end = model.NewIntVar(0, num_rooms, f"REND_{session.id_str}"); model.Add(r_end == g.fixed_room_var + 1)
                gs_end_r = model.NewIntVar(0, num_total_active_slots, f"GSLEND_R_{session.id_str}"); model.Add(gs_end_r == session.assigned_global_slot_var + 1)
                room_intervals_x.append(model.NewIntervalVar(g.fixed_room_var, size_one, r_end, f"RXV_{session.id_str}"))
                room_intervals_y.append(model.NewIntervalVar(session.assigned_global_slot_var, size_one, gs_end_r, f"RYV_{session.id_str}"))
            
            if lecturer_intervals_x: model.AddNoOverlap2D(lecturer_intervals_x, lecturer_intervals_y)
            if room_intervals_x: model.AddNoOverlap2D(room_intervals_x, room_intervals_y)

            # --- 6. Define Objective Function ---
            logger.info("Defining objective function...")
            objective_terms, objective_weights = [], []
            
            actual_lecturer_loads_vars: List[cp_model.IntVar] = []
            if num_lecturers > 0 and total_sessions_count > 0:
                actual_lecturer_loads_vars = [model.NewIntVar(0, total_sessions_count, f'load_l{l_idx}') for l_idx in range(num_lecturers)]
                for l_idx in range(num_lecturers):
                    terms = []
                    for group in all_scheduling_groups:
                        is_lect_var = model.NewBoolVar(f'is_l{l_idx}_g{group.id_tuple}')
                        model.Add(group.assigned_lecturer_var == l_idx).OnlyEnforceIf(is_lect_var)
                        model.Add(group.assigned_lecturer_var != l_idx).OnlyEnforceIf(is_lect_var.Not())
                        term_var = model.NewIntVar(0, len(group.sessions_to_schedule), f'term_l{l_idx}_g{group.id_tuple}')
                        model.Add(term_var == len(group.sessions_to_schedule)).OnlyEnforceIf(is_lect_var)
                        model.Add(term_var == 0).OnlyEnforceIf(is_lect_var.Not())
                        terms.append(term_var)
                    if terms: model.Add(actual_lecturer_loads_vars[l_idx] == sum(terms))
                    else: model.Add(actual_lecturer_loads_vars[l_idx] == 0)

            if "BALANCE_LOAD" in input_dto.objectiveStrategy and actual_lecturer_loads_vars:
                max_load = model.NewIntVar(0, total_sessions_count, 'max_load')
                min_load = model.NewIntVar(0, total_sessions_count, 'min_load')
                model.AddMaxEquality(max_load, actual_lecturer_loads_vars)
                model.AddMinEquality(min_load, actual_lecturer_loads_vars)
                diff = model.NewIntVar(0, total_sessions_count, 'load_diff')
                model.Add(diff == max_load - min_load)
                objective_terms.append(diff)
                objective_weights.append(10)

            if "EARLY_START" in input_dto.objectiveStrategy:
                all_global_slot_vars = [s.assigned_global_slot_var for s in all_sessions_to_schedule]
                if all_global_slot_vars:
                    max_sum_val = len(all_global_slot_vars) * (num_total_active_slots - 1)
                    if max_sum_val <= 0: max_sum_val = 1
                    
                    sum_of_global_slots_var = model.NewIntVar(0, max_sum_val, 'obj_sum_global_slots')
                    model.Add(sum_of_global_slots_var == sum(all_global_slot_vars))
                    
                    objective_terms.append(sum_of_global_slots_var)
                    objective_weights.append(1)  
                    logger.info(f"Added 'EARLY_START' objective by minimizing sum of global slots.")
            
            if "COMPACT_SCHEDULE" in input_dto.objectiveStrategy:
                span_terms = []
                for group in all_scheduling_groups:
                    week_vars = [s.assigned_semester_week_idx_var for s in group.sessions_to_schedule]
                    
                    if len(week_vars) > 1:
                        min_w = model.NewIntVar(0, total_calendar_weeks - 1, f'min_w_{group.id_tuple}')
                        max_w = model.NewIntVar(0, total_calendar_weeks - 1, f'max_w_{group.id_tuple}')
                        model.AddMinEquality(min_w, week_vars)
                        model.AddMaxEquality(max_w, week_vars)
                        
                        span = model.NewIntVar(0, total_calendar_weeks - 1, f'span_{group.id_tuple}')
                        model.Add(span == max_w - min_w)
                        span_terms.append(span)

                if span_terms:
                    max_total_span = len(span_terms) * (total_calendar_weeks - 1)
                    if max_total_span <= 0: max_total_span = 1
                    total_span = model.NewIntVar(0, max_total_span, 'total_span')
                    model.Add(total_span == sum(span_terms))
                    objective_terms.append(total_span)
                    objective_weights.append(20) # Ưu tiên cao cho sự nhỏ gọn
                    logger.info(f"Added 'COMPACT_SCHEDULE' objective by minimizing schedule span.")

            if "OPTIMIZE_ROOM_FIT" in input_dto.objectiveStrategy and input_dto.groupSizeTarget > 0 and room_capacities_by_idx:
                penalty_terms = []
                max_cap = max(room_capacities_by_idx)
                target_cap = input_dto.groupSizeTarget
                for group in all_scheduling_groups:
                    cap_var = model.NewIntVar(0, max_cap, f'cap_pen_{group.id_tuple}')
                    model.AddElement(group.fixed_room_var, room_capacities_by_idx, cap_var)
                    pen_var = model.NewIntVar(0, max_cap, f'pen_{group.id_tuple}')
                    model.AddAbsEquality(pen_var, cap_var - target_cap)
                    penalty_terms.append(pen_var)
                if penalty_terms:
                    max_total_pen = len(penalty_terms) * max_cap
                    total_pen = model.NewIntVar(0, max_total_pen if max_total_pen > 0 else 1, 'total_room_pen')
                    model.Add(total_pen == sum(penalty_terms))
                    objective_terms.append(total_pen)
                    objective_weights.append(5)

            if objective_terms:
                model.Minimize(cp_model.LinearExpr.WeightedSum(objective_terms, objective_weights))
            else:
                logger.info("No specific objective.")

            # --- 7. Solve the Model & 8. Process Solution ---
            logger.info("Starting solver...")
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = input_dto.solverTimeLimitSeconds
            solver.parameters.log_search_progress = True
            
            output_scheduled_courses, output_lecturer_loads, output_load_difference = [], [], None
            
            solution_status_code = solver.Solve(model)
            solution_status_name = solver.StatusName(solution_status_code)
            logger.info(f"Solver finished with status: {solution_status_name}")

            if solution_status_code in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
                groups_by_course: Dict[int, List[SchedulingGroupInternal]] = {}
                for group_obj in all_scheduling_groups:
                    groups_by_course.setdefault(group_obj.course_props.courseId, []).append(group_obj)
                
                for course_id, list_of_groups_for_course in groups_by_course.items():
                    original_course_props = course_properties_map[course_id]
                    course_scheduled_dto = CourseScheduledDTO(
                        courseId=course_id, totalRegisteredStudents=original_course_props.registeredStudents,
                        totalSessionsForCourse=original_course_props.totalSemesterSessions, scheduledClassGroups=[]
                    )
                    
                    for group in list_of_groups_for_course:
                        try:
                            assigned_lect_id = lecturer_idx_to_id[solver.Value(group.assigned_lecturer_var)]
                            assigned_room_idx = solver.Value(group.fixed_room_var)
                            assigned_room_id = room_idx_to_id[assigned_room_idx]
                            assigned_day_name = day_idx_to_name[solver.Value(group.fixed_day_var)]
                            assigned_timeslot_id = timeslot_idx_to_id[solver.Value(group.fixed_shift_var)]
                            
                            max_students_for_group = room_capacities_by_idx[assigned_room_idx]

                            scheduled_dates = []
                            for session in group.sessions_to_schedule:
                                solved_gs_idx = solver.Value(session.assigned_global_slot_var)
                                smw_idx, d_idx, _ = global_slot_to_details[solved_gs_idx]
                                actual_date = swk_day_to_date_map.get((smw_idx, d_idx))
                                if actual_date: scheduled_dates.append(actual_date.strftime("%Y-%m-%d"))
                            
                            scheduled_dates.sort()
                            
                            weekly_detail = WeeklyScheduleDetailDTO(
                                dayOfWeek=assigned_day_name, timeSlotId=assigned_timeslot_id,
                                roomId=assigned_room_id, scheduledDates=scheduled_dates
                            )
                            
                            class_group_dto = ClassGroupScheduledDTO(
                                groupNumber=group.id_tuple[2], maxStudents=max_students_for_group,
                                lecturerId=assigned_lect_id,
                                groupStartDate=scheduled_dates[0] if scheduled_dates else "N/A",
                                groupEndDate=scheduled_dates[-1] if scheduled_dates else "N/A",
                                totalTeachingWeeksForGroup=len(scheduled_dates),
                                sessionsPerWeekForGroup=1, weeklyScheduleDetails=[weekly_detail]
                            )
                            course_scheduled_dto.scheduledClassGroups.append(class_group_dto)
                        except Exception as e:
                            logger.error(f"Error processing solution for group {group.id_tuple}: {e}", exc_info=True)
                    
                    if course_scheduled_dto.scheduledClassGroups:
                        output_scheduled_courses.append(course_scheduled_dto)

                if actual_lecturer_loads_vars:
                    try:
                        loads = [solver.Value(lv) for lv in actual_lecturer_loads_vars]
                        output_lecturer_loads = [LecturerLoadDTO(lecturerId=lecturer_idx_to_id[i], sessionsAssigned=load) for i, load in enumerate(loads)]
                        if loads: output_load_difference = max(loads) - min(loads)
                    except Exception as e: logger.error(f"Error processing lecturer loads: {e}", exc_info=True)
                
                elif num_lecturers > 0:
                    output_lecturer_loads = [LecturerLoadDTO(lecturerId=l.lecturerId, sessionsAssigned=0) for l in input_dto.lecturers]

            elif solution_status_code == cp_model.INFEASIBLE:
                logger.warning("Solver determined the model is INFEASIBLE.")
            
            duration_seconds = time.time() - start_time_measurement
            final_message = f"Solver finished with status: {solution_status_name}."
            if solution_status_code in [cp_model.OPTIMAL, cp_model.FEASIBLE] and not output_scheduled_courses:
                final_message = "Feasible/Optimal solution found, but no courses were scheduled (check constraints)."

            return FinalScheduleResultDTO( 
                semesterId=input_dto.semesterId, semesterStartDate=input_dto.semesterStartDate,
                semesterEndDate=input_dto.semesterEndDate, scheduledCourses=output_scheduled_courses,
                lecturerLoad=output_lecturer_loads, loadDifference=output_load_difference, 
                totalOriginalSessionsToSchedule=total_sessions_count, solverDurationSeconds=duration_seconds,
                solverStatus=solution_status_name, solverMessage=final_message 
            )

        except (HTTPException, ValueError) as e:
            logger.error(f"Validation or business logic error: {e}", exc_info=False)
            raise
        except Exception as e:  
            logger.critical(f"Unexpected error in scheduling service: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")