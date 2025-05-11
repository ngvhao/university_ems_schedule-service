import logging
import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from ortools.sat.python import cp_model
from pydantic import BaseModel, Field, ValidationError, validator 
from fastapi import HTTPException

# --- DTOs for Input (Giả định đã được định nghĩa như trong file trước của bạn) ---
class CourseSemesterDTO(BaseModel):
    courseSemesterId: int
    credits: int
    totalRequiredSessions: int = Field(gt=0)
    registeredStudents: int
    desiredNumberOfGroups: Optional[int] = Field(default=None, ge=1)
    registrationStatus: str = "CLOSED"
    preRegisteredStudents: int = 0
    sessionsPerWeek: Optional[int] = None
    calculatedTotalWeeksForCourse: Optional[int] = None

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
    courseSemesters: List[CourseSemesterDTO]
    lecturers: List[LecturerDTO]
    rooms: List[RoomDTO]
    timeSlots: List[TimeSlotDTO]
    days: List[str]
    maxSessionsPerLecturerConstraint: Optional[int] = None
    totalSemesterWeeks: Optional[int] = None

    @validator('semesterStartDate', 'semesterEndDate')
    def validate_date_format(cls, v_str, values):
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
class ClassGroupOutputDTO(BaseModel): 
    groupNumber: int
    maxStudents: int
    registeredStudents: int
    status: str = "OPEN"
    courseSemesterId: int
    startSemesterWeek: Optional[int] = None 
    endSemesterWeek: Optional[int] = None   
    totalTeachingWeeks: Optional[int] = None 

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

class ScheduleResultDTO(BaseModel):
    classGroups: List[ClassGroupOutputDTO] 
    schedule: List[ScheduleEntryDTO]
    violations: List[str]
    lecturerLoad: List[LecturerLoadDTO]
    loadDifference: Optional[int] = None
    totalCourseSessionsToSchedule: int
    totalSemesterWeekSlots: int
    totalAvailableRoomSlotsInSemester: int
    lecturerPotentialLoad: Dict[int, int] 

# --- Helper Structures ---
class CourseProps: 
    def __init__(self, cs_dto: CourseSemesterDTO, calculated_sessions_per_week: int, calculated_total_weeks_for_course: int):
        self.course_semester_id = cs_dto.courseSemesterId
        self.credits = cs_dto.credits
        self.total_required_sessions = cs_dto.totalRequiredSessions
        self.registered_students = cs_dto.registeredStudents
        self.desired_number_of_groups = cs_dto.desiredNumberOfGroups
        self.sessions_per_week = calculated_sessions_per_week
        self.calculated_total_weeks_for_course = calculated_total_weeks_for_course

class ClassGroupInternal:
    def __init__(self, course_props: CourseProps, group_number: int, registered_students: int):
        self.course_props = course_props
        self.group_number = group_number
        self.registered_students = registered_students
        self.sessions: List[ClassSessionInternal] = []
        self.start_semester_week_var: Optional[cp_model.IntVar] = None 

    def __repr__(self):
        return (f"CG(csId={self.course_props.course_semester_id}, gN={self.group_number}, stud={self.registered_students})")

class ClassSessionInternal:
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

    def __repr__(self): return self.id

# --- Schedule Service ---
class ScheduleService:
    @staticmethod
    def _get_sessions_per_week_from_credits(credits: int, course_id: int) -> int:
        if 1 <= credits <= 3: return 1
        if 4 <= credits <= 5: return 2
        logging.warning(f"C{course_id}(cr{credits}): Default 1 sess/wk.")
        return 1 

    @staticmethod
    async def calculate_with_cp(input_dto: ScheduleInputDTO) -> ScheduleResultDTO:
        service_logger = logging.getLogger(f"{__name__}.ScheduleService.calculate_with_cp")
        try:
            service_logger.info("Starting schedule calculation...")
            
            start_date_obj = date.fromisoformat(input_dto.semesterStartDate)
            end_date_obj = date.fromisoformat(input_dto.semesterEndDate)
            
            num_days_in_semester = (end_date_obj - start_date_obj).days + 1
            total_semester_weeks = math.ceil(num_days_in_semester / 7)
            service_logger.info(f"Total semester weeks: {total_semester_weeks}")
            
            processed_courses: Dict[int, CourseProps] = {}
            for cs_dto in input_dto.courseSemesters:
                sessions_p_week = ScheduleService._get_sessions_per_week_from_credits(cs_dto.credits, cs_dto.courseSemesterId)
                if sessions_p_week <= 0 : 
                     raise HTTPException(status_code=400, detail=f"C{cs_dto.courseSemesterId} has <=0 sess/wk.")
                
                calc_total_wks = math.ceil(cs_dto.totalRequiredSessions / sessions_p_week)
                cs_dto.sessionsPerWeek = sessions_p_week
                cs_dto.calculatedTotalWeeksForCourse = calc_total_wks
                
                processed_courses[cs_dto.courseSemesterId] = CourseProps(cs_dto, sessions_p_week, calc_total_wks)
                if calc_total_wks <= 0 and cs_dto.totalRequiredSessions > 0 :
                     service_logger.warning(f"C{cs_dto.courseSemesterId} has totalRequiredSessions > 0 but calculatedTotalWeeksForCourse is 0. Check sessionsPerWeek logic.")
                elif calc_total_wks > total_semester_weeks:
                    raise HTTPException(status_code=400, 
                                        detail=f"C{cs_dto.courseSemesterId} needs {calc_total_wks}w > sem {total_semester_weeks}w.")

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
            shift_idx_to_str = {i: shifts_map[s_val] for i, s_val in enumerate(shift_indices)}
            
            day_to_idx = {day: i for i, day in enumerate(input_dto.days)}
            day_idx_to_str = {i: day for i, day in enumerate(input_dto.days)}

            num_lect, num_rooms, num_shifts, num_days_wk = len(lecturers_list), len(rooms_list), len(shift_indices), len(input_dto.days)
            num_wk_slots = num_days_wk * num_shifts
            num_total_sem_slots = num_wk_slots * total_semester_weeks

            sem_slot_map: Dict[int, Tuple[int, int, int]] = {} 
            _slot_count = 0
            for swk_idx in range(total_semester_weeks):
                for day_idx in range(num_days_wk):
                    for sh_idx in range(num_shifts):
                        sem_slot_map[_slot_count] = (swk_idx, day_idx, sh_idx)
                        _slot_count += 1
            
            internal_groups: List[ClassGroupInternal] = []
            output_groups_dto: List[ClassGroupOutputDTO] = []
            all_sessions: List[ClassSessionInternal] = []

            for cs_id, course_p in processed_courses.items():
                if course_p.registered_students <= 0 or course_p.total_required_sessions <= 0:
                    service_logger.info(f"C{cs_id} has 0 students or 0 required sessions. Skipping.")
                    continue
                
                num_grps = course_p.desired_number_of_groups if course_p.desired_number_of_groups else 1
                if num_grps <= 0: num_grps = 1
                
                base_stud, rem_stud = divmod(course_p.registered_students, num_grps)
                
                for i in range(num_grps):
                    grp_num = i + 1
                    stud_in_grp = base_stud + (1 if i < rem_stud else 0)
                    if stud_in_grp == 0 and course_p.registered_students > 0: 
                        service_logger.warning(f"C{cs_id} G{grp_num}: 0 students after division. Skipping.")
                        continue

                    grp_obj = ClassGroupInternal(course_p, grp_num, stud_in_grp)
                    internal_groups.append(grp_obj)
                    output_groups_dto.append(ClassGroupOutputDTO(
                        courseSemesterId=cs_id, groupNumber=grp_num,
                        maxStudents=stud_in_grp, registeredStudents=stud_in_grp))
                    
                    if stud_in_grp > 0 and course_p.total_required_sessions > 0 :
                        created_s, curr_cwk = 0, 1
                        while created_s < course_p.total_required_sessions:
                            for sess_in_wk_num in range(1, course_p.sessions_per_week + 1):
                                if created_s < course_p.total_required_sessions:
                                    created_s += 1
                                    sess = ClassSessionInternal(grp_obj, curr_cwk, sess_in_wk_num, created_s)
                                    grp_obj.sessions.append(sess)
                                    all_sessions.append(sess)
                                else: break
                            curr_cwk += 1
                            if curr_cwk > course_p.calculated_total_weeks_for_course + 5: 
                                service_logger.error(f"Logic err: Exceeded calc wks for C{cs_id}G{grp_num}")
                                break
            
            if not all_sessions:
                 return ScheduleResultDTO(classGroups=output_groups_dto, schedule=[], violations=["No sessions to schedule."], 
                    lecturerLoad=[], totalCourseSessionsToSchedule=0, totalSemesterWeekSlots=num_total_sem_slots,
                    totalAvailableRoomSlotsInSemester=num_total_sem_slots * num_rooms, 
                    lecturerPotentialLoad={}, loadDifference=0)

            total_req_course_sessions = len(all_sessions)
            violations = [] 
            
            lect_potential_load: Dict[int, int] = {lect_id: 0 for lect_id in lecturer_id_to_idx.keys()}
            for l_user_id in lecturer_id_to_idx.keys():
                load = 0
                for cs_id_can_teach in lecturer_id_to_teaching_courses.get(l_user_id, []):
                    if cs_id_can_teach in processed_courses:
                        course_p_obj = processed_courses[cs_id_can_teach]
                        num_actual_grps_for_course = sum(1 for g_dto in output_groups_dto if g_dto.courseSemesterId == cs_id_can_teach)
                        load += course_p_obj.total_required_sessions * num_actual_grps_for_course 
                lect_potential_load[l_user_id] = load

            if total_req_course_sessions > num_total_sem_slots * num_rooms:
                violations.append(f"Sessions ({total_req_course_sessions}) > room-slots ({num_total_sem_slots*num_rooms}).")
            if violations: 
                 return ScheduleResultDTO(classGroups=output_groups_dto, schedule=[], violations=violations,
                    lecturerLoad=[LecturerLoadDTO(lecturerId=l_id, sessionsAssigned=0) for l_id in lecturer_id_to_idx.keys()],
                    totalCourseSessionsToSchedule=total_req_course_sessions, totalSemesterWeekSlots=num_total_sem_slots,
                    totalAvailableRoomSlotsInSemester=num_total_sem_slots * num_rooms, lecturerPotentialLoad=lect_potential_load)

            model = cp_model.CpModel()
            
            for grp_obj in internal_groups:
                props = grp_obj.course_props
                if props.calculated_total_weeks_for_course > 0 : 
                    upper_b = total_semester_weeks - props.calculated_total_weeks_for_course
                    if upper_b < 0: 
                        service_logger.error(f"C{props.course_semester_id} calc_wks ({props.calculated_total_weeks_for_course}) > sem_wks ({total_semester_weeks}) - check logic.")
                        raise ValueError(f"C{props.course_semester_id} needs more weeks than available in semester.")
                    grp_obj.start_semester_week_var = model.NewIntVar(0, upper_b, f'start_sw_c{props.course_semester_id}_g{grp_obj.group_number}')

            for sess in all_sessions:
                sess.slot_var = model.NewIntVar(0, num_total_sem_slots - 1, f'{sess.id}_slot')
                sess.lecturer_var = model.NewIntVar(0, num_lect - 1, f'{sess.id}_lect')
                sess.room_var = model.NewIntVar(0, num_rooms - 1, f'{sess.id}_room')
                sess.assigned_semester_week_var = model.NewIntVar(0, total_semester_weeks - 1, f'{sess.id}_asg_sw')

                start_wk_var = sess.class_group.start_semester_week_var
                if start_wk_var is not None:
                    model.Add(sess.assigned_semester_week_var == start_wk_var + (sess.course_week_number - 1))
                elif sess.class_group.course_props.calculated_total_weeks_for_course > 0:
                     service_logger.critical(f"Logic error: start_wk_var None for C{sess.class_group.course_props.course_semester_id}G{sess.class_group.group_number}")
                     raise ValueError("Missing start_wk_var for group that should have one.")
                
                slot_wk_comp_var = model.NewIntVar(0, total_semester_weeks - 1, f'{sess.id}_slot_wk_c')
                possible_wks = [sem_slot_map[s_idx][0] for s_idx in range(num_total_sem_slots)]
                model.AddElement(sess.slot_var, possible_wks, slot_wk_comp_var)
                model.Add(slot_wk_comp_var == sess.assigned_semester_week_var)

            # RB1: Lecturer teaches assigned course
            for sess in all_sessions:
                c_id = sess.class_group.course_props.course_semester_id
                allowed_l_ids = [l_idx for l_idx, luid in lecturer_idx_to_id.items() if c_id in lecturer_id_to_teaching_courses.get(luid, [])]
                if not allowed_l_ids: raise HTTPException(status_code=400, detail=f"No lecturer for C{c_id}")
                model.AddAllowedAssignments([sess.lecturer_var], [(lidx,) for lidx in allowed_l_ids])

            # RB2: Room capacity
            room_caps_consts = [model.NewConstant(cap) for cap in room_caps_list]
            for sess in all_sessions:
                stud_c = sess.class_group.registered_students
                rcap_var = model.NewIntVar(0, max(room_caps_list) if room_caps_list else 0, f'{sess.id}_rcap')
                model.AddElement(sess.room_var, room_caps_consts, rcap_var)
                model.Add(rcap_var >= stud_c)

            # RB New: Limit sessions per week for a group/course
            for grp_obj in internal_groups:
                course_id = grp_obj.course_props.course_semester_id 
                sessions_per_week_limit = grp_obj.course_props.sessions_per_week
                for sem_wk_idx in range(total_semester_weeks):
                    sessions_in_this_sem_week_bools = []
                    for sess_obj in grp_obj.sessions: 
                        b = model.NewBoolVar(f'g{grp_obj.group_number}_c{course_id}_s{sess_obj.overall_session_sequence_num}_in_semwk{sem_wk_idx}')
                        model.Add(sess_obj.assigned_semester_week_var == sem_wk_idx).OnlyEnforceIf(b)
                        model.Add(sess_obj.assigned_semester_week_var != sem_wk_idx).OnlyEnforceIf(b.Not())
                        sessions_in_this_sem_week_bools.append(b)
                    if sessions_in_this_sem_week_bools:
                        model.Add(sum(sessions_in_this_sem_week_bools) <= sessions_per_week_limit)

            # RB4: Sessions of same group & course_week are in different day/shift slots
            for grp_obj in internal_groups:
                sess_by_cwk: Dict[int, List[ClassSessionInternal]] = {}
                for s in grp_obj.sessions: sess_by_cwk.setdefault(s.course_week_number, []).append(s)
                for _, sessions_in_cwk in sess_by_cwk.items():
                    valid_slot_vars_for_alldiff = [s.slot_var for s in sessions_in_cwk if s.slot_var is not None]
                    if len(valid_slot_vars_for_alldiff) > 1:
                        model.AddAllDifferent(valid_slot_vars_for_alldiff)
            
            # RB7 & RB8: NoOverlap2D
            lx_ivs, ly_ivs, rx_ivs, ry_ivs = [], [], [], []
            s1 = 1 
            for sess in all_sessions:
                lx_e, ly_e, rx_e = model.NewIntVar(0,num_lect,f'{sess.id}_lxe'), model.NewIntVar(0,num_total_sem_slots,f'{sess.id}_lye'), model.NewIntVar(0,num_rooms,f'{sess.id}_rxe')
                model.Add(lx_e == sess.lecturer_var + s1); model.Add(ly_e == sess.slot_var + s1); model.Add(rx_e == sess.room_var + s1)
                lx_ivs.append(model.NewIntervalVar(sess.lecturer_var,s1,lx_e,f'{sess.id}_lxi')); ly_ivs.append(model.NewIntervalVar(sess.slot_var,s1,ly_e,f'{sess.id}_lyi'))
                rx_ivs.append(model.NewIntervalVar(sess.room_var,s1,rx_e,f'{sess.id}_rxi')); ry_ivs.append(model.NewIntervalVar(sess.slot_var,s1,ly_e,f'{sess.id}_ryi'))
            if lx_ivs: model.AddNoOverlap2D(lx_ivs, ly_ivs)
            if rx_ivs: model.AddNoOverlap2D(rx_ivs, ry_ivs)

            # Objective
            actual_loads_vars = []
            if num_lect > 0 and total_req_course_sessions > 0:
                actual_loads_vars = [model.NewIntVar(0,total_req_course_sessions,f'al_l{i}') for i in range(num_lect)]
                for lidx in range(num_lect):
                    asg = [model.NewBoolVar(f'{s.id}_al{lidx}') for s in all_sessions]
                    for i,s_obj in enumerate(all_sessions): model.Add(s_obj.lecturer_var==lidx).OnlyEnforceIf(asg[i]); model.Add(s_obj.lecturer_var!=lidx).OnlyEnforceIf(asg[i].Not())
                    model.Add(actual_loads_vars[lidx] == sum(asg))
                if actual_loads_vars:
                    max_l,min_l = model.NewIntVar(0,total_req_course_sessions,'maxl'), model.NewIntVar(0,total_req_course_sessions,'minl')
                    model.AddMaxEquality(max_l,actual_loads_vars); model.AddMinEquality(min_l,actual_loads_vars)
                    model.Minimize(max_l-min_l)
            
            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = 180.0
            solver.parameters.log_search_progress = True
            
            service_logger.info("Solver starting...")
            status = solver.Solve(model)
            service_logger.info(f"Solver finished. Status: {solver.StatusName(status)}")

            final_sched: List[ScheduleEntryDTO] = []
            final_l_load: List[LecturerLoadDTO] = []
            load_diff_val: Optional[int] = None

            solved_start_weeks: Dict[Tuple[int,int], int] = {}
            if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
                if internal_groups : 
                    for grp_obj in internal_groups:
                        if grp_obj.start_semester_week_var is not None: 
                            try:
                                start_val = solver.Value(grp_obj.start_semester_week_var)
                                solved_start_weeks[(grp_obj.course_props.course_semester_id, grp_obj.group_number)] = start_val
                            except Exception as e_val: 
                                service_logger.warning(f"Could not get solver value for start_var of C{grp_obj.course_props.course_semester_id}G{grp_obj.group_number}: {e_val}")

                for grp_dto in output_groups_dto: 
                    start_wk_idx = solved_start_weeks.get((grp_dto.courseSemesterId, grp_dto.groupNumber))
                    course_p = processed_courses.get(grp_dto.courseSemesterId)
                    if start_wk_idx is not None and course_p and course_p.calculated_total_weeks_for_course > 0:
                        grp_dto.startSemesterWeek = start_wk_idx + 1 
                        grp_dto.totalTeachingWeeks = course_p.calculated_total_weeks_for_course
                        grp_dto.endSemesterWeek = grp_dto.startSemesterWeek + grp_dto.totalTeachingWeeks - 1
                
                objective_value_str = "N/A"
                if actual_loads_vars: 
                    try:
                        obj_val = solver.ObjectiveValue()
                        objective_value_str = str(obj_val) 
                    except Exception as e_obj: 
                        service_logger.warning(f"Could not retrieve objective value: {e_obj}")
                service_logger.info(f"Solution found! Objective: {objective_value_str}")

                for s in all_sessions:
                    slot_v, lect_idx_v, room_idx_v = solver.Value(s.slot_var), solver.Value(s.lecturer_var), solver.Value(s.room_var)
                    sem_wk_v, day_idx_v, sh_idx_v = sem_slot_map[slot_v]
                    final_sched.append(ScheduleEntryDTO(
                        courseSemesterId=s.class_group.course_props.course_semester_id, groupNumber=s.class_group.group_number, 
                        semesterWeek=sem_wk_v + 1, sessionSequenceInWeek=s.session_in_course_week,
                        overallSessionSequence=s.overall_session_sequence_num, shift=shift_idx_to_str[sh_idx_v], 
                        room=room_idx_to_name[room_idx_v], lecturerId=lecturer_idx_to_id[lect_idx_v], day=day_idx_to_str[day_idx_v]))
                
                if actual_loads_vars:
                    act_loads = [solver.Value(lv) for lv in actual_loads_vars]
                    for lidx, l_val in enumerate(act_loads): final_l_load.append(LecturerLoadDTO(lecturerId=lecturer_idx_to_id[lidx], sessionsAssigned=l_val))
                    if act_loads: load_diff_val = max(act_loads) - min(act_loads)
            
            elif status == cp_model.INFEASIBLE: violations.append("INFEASIBLE: Constraints conflict.")
            else: violations.append(f"Solver status: {solver.StatusName(status)}")

            if not final_l_load and num_lect > 0:
                for l_id in lecturer_id_to_idx.keys(): final_l_load.append(LecturerLoadDTO(lecturerId=l_id, sessionsAssigned=0))
            
            return ScheduleResultDTO(
                classGroups=output_groups_dto, schedule=final_sched, violations=violations, lecturerLoad=final_l_load, 
                loadDifference=load_diff_val, totalCourseSessionsToSchedule=total_req_course_sessions,
                totalSemesterWeekSlots=num_total_sem_slots, totalAvailableRoomSlotsInSemester=num_total_sem_slots*num_rooms,
                lecturerPotentialLoad=lect_potential_load)
        
        except ValidationError as e:
            service_logger.error(f"Pydantic Val Err: {e.errors()}", exc_info=False)
            raise HTTPException(status_code=422, detail=e.errors())
        except HTTPException as he: 
            service_logger.error(f"HTTPException in service: Status {he.status_code}, Detail: {he.detail}", exc_info=False)
            raise he 
        except ValueError as ve: 
            service_logger.error(f"ValueError in service: {str(ve)}", exc_info=True)
            raise HTTPException(status_code=400, detail=f"Bad request/logic err: {str(ve)}")
        except Exception as e: 
            service_logger.critical(f"UNEXPECTED SERVICE ERROR: {type(e).__name__} - {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Internal Server Error: {type(e).__name__} - {str(e)}")
