from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

from ortools.sat.python import cp_model
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


logger = logging.getLogger(__name__)


class StaffMember(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., min_length=1)
    role: str = Field(
        default="enfermero",
        min_length=1,
        validation_alias=AliasChoices("role", "rol"),
    )
    seniority: Literal["senior", "intermedio", "junior"] = Field(
        default="intermedio",
        validation_alias=AliasChoices("seniority", "experiencia"),
    )
    max_hours: int = Field(
        ...,
        ge=0,
        validation_alias=AliasChoices("max_hours", "maximo_horas"),
    )
    unavailable_dates: list[date] = Field(
        default_factory=list,
        validation_alias=AliasChoices("unavailable_dates", "fechas_no_disponibles"),
    )
    unavailable_shift_ids: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("unavailable_shift_ids", "turnos_no_disponibles"),
    )
    requested_days_off: list[date] = Field(
        default_factory=list,
        validation_alias=AliasChoices("requested_days_off", "dias_solicitados_libres"),
    )
    previous_shift_kind: Literal["largo", "noche", "otro"] | None = Field(
        default=None,
        validation_alias=AliasChoices("previous_shift_kind", "tipo_turno_previo"),
    )
    previous_shift_end: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("previous_shift_end", "fin_turno_previo"),
    )


class Shift(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(..., min_length=1)
    required_staff: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("required_staff", "dotacion_requerida"),
    )
    required_by_role: dict[str, int] | None = Field(
        default=None,
        validation_alias=AliasChoices("required_by_role", "dotacion_por_rol"),
    )
    min_senior_by_role: dict[str, int] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("min_senior_by_role", "minimo_senior_por_rol"),
    )
    min_senior_staff: int = Field(
        default=0,
        ge=0,
        validation_alias=AliasChoices("min_senior_staff", "minimo_senior_total"),
    )
    day: str | None = Field(
        default=None,
        min_length=1,
        validation_alias=AliasChoices("day", "dia"),
    )
    duration: int | None = Field(
        default=None,
        gt=0,
        validation_alias=AliasChoices("duration", "duracion_horas"),
    )
    start: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("start", "inicio"),
    )
    end: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("end", "fin"),
    )
    kind: Literal["dia", "largo", "noche", "otro"] = Field(
        default="otro",
        validation_alias=AliasChoices("kind", "tipo"),
    )

    @model_validator(mode="after")
    def validate_time_fields(self) -> "Shift":
        if self.required_staff is None and not self.required_by_role:
            raise ValueError("each shift needs required_staff or required_by_role")

        if self.required_by_role is not None:
            for role, required in self.required_by_role.items():
                if required < 0:
                    raise ValueError(f"required_by_role for {role} cannot be negative")

        for role, required in self.min_senior_by_role.items():
            if required < 0:
                raise ValueError(f"min_senior_by_role for {role} cannot be negative")

        if self.start is None or self.end is None:
            if self.duration is None or self.day is None:
                raise ValueError(
                    "each shift needs start/end or legacy day/duration fields"
                )
            return self

        if self.end <= self.start:
            raise ValueError("shift end must be after shift start")

        calendar_seconds = (self.end - self.start).total_seconds()
        if calendar_seconds % 3600 != 0:
            raise ValueError("shift duration must be a whole number of hours")

        if self.duration is None:
            self.duration = int(calendar_seconds // 3600)
        if self.day is None:
            self.day = self.start.strftime("%Y-%m-%d")

        return self


class SchedulingRules(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    min_rest_hours: int = Field(
        default=12,
        ge=0,
        validation_alias=AliasChoices("min_rest_hours", "descanso_minimo_horas"),
    )
    night_rest_hours: int = Field(
        default=48,
        ge=0,
        validation_alias=AliasChoices("night_rest_hours", "descanso_post_noche_horas"),
    )
    weekly_max_hours: int | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("weekly_max_hours", "maximo_semanal_horas"),
    )
    enforce_one_shift_per_day: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "enforce_one_shift_per_day",
            "un_turno_por_dia",
        ),
    )
    enforce_cuarto_turno: bool = Field(
        default=False,
        validation_alias=AliasChoices("enforce_cuarto_turno", "cuarto_turno"),
    )
    prefer_cuarto_turno_pattern: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "prefer_cuarto_turno_pattern",
            "preferir_patron_cuarto_turno",
        ),
    )
    force_cuarto_turno_pairing: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "force_cuarto_turno_pairing",
            "forzar_pareja_cuarto_turno",
        ),
    )


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    staff: list[StaffMember] = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("staff", "personal"),
    )
    shifts: list[Shift] = Field(
        ...,
        min_length=1,
        validation_alias=AliasChoices("shifts", "turnos"),
    )
    rules: SchedulingRules = Field(
        default_factory=SchedulingRules,
        validation_alias=AliasChoices("rules", "reglas"),
    )

    @model_validator(mode="after")
    def validate_unique_ids(self) -> "ScheduleRequest":
        staff_ids = [member.id for member in self.staff]
        shift_ids = [shift.id for shift in self.shifts]

        if len(staff_ids) != len(set(staff_ids)):
            raise ValueError("staff ids must be unique")
        if len(shift_ids) != len(set(shift_ids)):
            raise ValueError("shift ids must be unique")

        return self


class Assignment(BaseModel):
    staff_id: str
    shift_id: str


class ScheduleResponse(BaseModel):
    assignments: list[Assignment]
    objective_value: float | None
    status: Literal["ok", "no_solution"]
    solver_time_seconds: float
    message: str | None = None


@dataclass(frozen=True)
class SolverSettings:
    max_time_seconds: float = 10.0
    num_search_workers: int = 8


def shifts_are_incompatible(first: Shift, second: Shift, rules: SchedulingRules) -> bool:
    if (
        first.start is None
        or first.end is None
        or second.start is None
        or second.end is None
    ):
        return False

    earlier, later = sorted([first, second], key=lambda shift: shift.start)

    if earlier.end > later.start:
        return True

    required_rest = (
        rules.night_rest_hours
        if earlier.kind == "noche"
        else rules.min_rest_hours
    )
    earliest_next_start = earlier.end + timedelta(hours=required_rest)

    return later.start < earliest_next_start


def shift_start_date(shift: Shift) -> date | None:
    return shift.start.date() if shift.start is not None else None


def shift_total_required(shift: Shift) -> int:
    if shift.required_by_role:
        return sum(shift.required_by_role.values())
    return int(shift.required_staff or 0)


def staff_hour_limit(member: StaffMember, rules: SchedulingRules) -> int:
    if rules.weekly_max_hours is None:
        return member.max_hours
    return min(member.max_hours, rules.weekly_max_hours)


def previous_rest_until(member: StaffMember, rules: SchedulingRules) -> datetime | None:
    if member.previous_shift_kind is None or member.previous_shift_end is None:
        return None

    required_rest = (
        rules.night_rest_hours
        if member.previous_shift_kind == "noche"
        else rules.min_rest_hours
    )
    return member.previous_shift_end + timedelta(hours=required_rest)


def find_shift_indexes_by_kind_and_date(
    shifts: list[Shift],
    kind: str,
    start_date: date,
) -> list[int]:
    return [
        shift_index
        for shift_index, shift in enumerate(shifts)
        if shift.kind == kind and shift_start_date(shift) == start_date
    ]


def add_cuarto_turno_constraints(
    model: cp_model.CpModel,
    assignment_vars,
    staff: list[StaffMember],
    shifts: list[Shift],
) -> None:
    for member_index in range(len(staff)):
        for shift_index, shift in enumerate(shifts):
            start_date = shift_start_date(shift)
            if start_date is None:
                continue

            if shift.kind == "largo":
                next_night_indexes = find_shift_indexes_by_kind_and_date(
                    shifts, "noche", start_date + timedelta(days=1),
                )
                if not next_night_indexes:
                    continue
                model.Add(
                    assignment_vars[(member_index, shift_index)]
                    <= sum(
                        assignment_vars[(member_index, night_index)]
                        for night_index in next_night_indexes
                    )
                )

            if shift.kind == "noche":
                previous_long_indexes = find_shift_indexes_by_kind_and_date(
                    shifts, "largo", start_date - timedelta(days=1),
                )
                if not previous_long_indexes:
                    continue
                model.Add(
                    assignment_vars[(member_index, shift_index)]
                    <= sum(
                        assignment_vars[(member_index, long_index)]
                        for long_index in previous_long_indexes
                    )
                )


def build_cuarto_turno_pattern_penalties(
    model: cp_model.CpModel,
    assignment_vars,
    staff: list[StaffMember],
    shifts: list[Shift],
):
    penalties = []

    for member_index, member in enumerate(staff):
        for shift_index, shift in enumerate(shifts):
            start_date = shift_start_date(shift)
            if start_date is None:
                continue

            if shift.kind == "largo":
                next_night_indexes = find_shift_indexes_by_kind_and_date(
                    shifts, "noche", start_date + timedelta(days=1),
                )
                if not next_night_indexes:
                    continue

                penalty = model.NewBoolVar(
                    f"pattern_break_largo_without_next_night_{member.id}_{shift.id}"
                )
                model.Add(
                    penalty
                    >= assignment_vars[(member_index, shift_index)]
                    - sum(
                        assignment_vars[(member_index, night_index)]
                        for night_index in next_night_indexes
                    )
                )
                penalties.append(penalty)

            if shift.kind == "noche":
                previous_long_indexes = find_shift_indexes_by_kind_and_date(
                    shifts, "largo", start_date - timedelta(days=1),
                )
                if not previous_long_indexes:
                    continue

                penalty = model.NewBoolVar(
                    f"pattern_break_night_without_previous_largo_{member.id}_{shift.id}"
                )
                model.Add(
                    penalty
                    >= assignment_vars[(member_index, shift_index)]
                    - sum(
                        assignment_vars[(member_index, long_index)]
                        for long_index in previous_long_indexes
                    )
                )
                penalties.append(penalty)

    return penalties


def optimize_schedule(
    staff: list[StaffMember],
    shifts: list[Shift],
    rules: SchedulingRules | None = None,
    settings: SolverSettings | None = None,
) -> ScheduleResponse:
    """Build and solve the clinical staff scheduling optimization model."""
    rules = rules or SchedulingRules()
    settings = settings or SolverSettings()

    if rules.enforce_cuarto_turno:
        invalid_shift_types = sorted(
            {shift.kind for shift in shifts if shift.kind not in {"largo", "noche"}}
        )
        if invalid_shift_types:
            return ScheduleResponse(
                assignments=[],
                objective_value=None,
                status="no_solution",
                solver_time_seconds=0.0,
                message=(
                    "El cuarto turno solo debe incluir turnos de tipo largo y "
                    f"noche. Se encontraron tipos no compatibles: {invalid_shift_types}."
                ),
            )

    for shift in shifts:
        if shift_total_required(shift) > len(staff):
            return ScheduleResponse(
                assignments=[],
                objective_value=None,
                status="no_solution",
                solver_time_seconds=0.0,
                message=(
                    "No se ha registrado el personal necesario para cubrir el "
                    f"turno {shift.id}. Requiere {shift_total_required(shift)} personas, "
                    f"pero solo hay {len(staff)} registradas."
                ),
            )

        if shift.required_by_role:
            for role, required in shift.required_by_role.items():
                staff_with_role = [member for member in staff if member.role == role]
                if required > len(staff_with_role):
                    return ScheduleResponse(
                        assignments=[],
                        objective_value=None,
                        status="no_solution",
                        solver_time_seconds=0.0,
                        message=(
                            "No se ha registrado el personal necesario para cubrir "
                            f"el rol {role} en el turno {shift.id}. Requiere "
                            f"{required}, pero solo hay {len(staff_with_role)}."
                        ),
                    )

        for role, required in shift.min_senior_by_role.items():
            senior_staff = [
                member for member in staff
                if member.role == role and member.seniority == "senior"
            ]
            if required > len(senior_staff):
                return ScheduleResponse(
                    assignments=[],
                    objective_value=None,
                    status="no_solution",
                    solver_time_seconds=0.0,
                    message=(
                        "No se ha registrado personal senior suficiente para cubrir "
                        f"el rol {role} en el turno {shift.id}. Requiere "
                        f"{required} senior, pero solo hay {len(senior_staff)}."
                    ),
                )

        if shift.min_senior_staff > 0:
            senior_staff = [member for member in staff if member.seniority == "senior"]
            if shift.min_senior_staff > len(senior_staff):
                return ScheduleResponse(
                    assignments=[],
                    objective_value=None,
                    status="no_solution",
                    solver_time_seconds=0.0,
                    message=(
                        "No se ha registrado personal senior suficiente para cubrir "
                        f"el turno {shift.id}. Requiere {shift.min_senior_staff} "
                        f"senior, pero solo hay {len(senior_staff)}."
                    ),
                )

    required_hours = sum(
        int(shift.duration or 0) * shift_total_required(shift) for shift in shifts
    )
    available_hours = sum(staff_hour_limit(member, rules) for member in staff)
    if required_hours > available_hours:
        return ScheduleResponse(
            assignments=[],
            objective_value=None,
            status="no_solution",
            solver_time_seconds=0.0,
            message=(
                "No hay capacidad horaria suficiente para cubrir la demanda. "
                f"Se requieren {required_hours} horas-persona, pero el personal "
                f"registrado aporta como maximo {available_hours} horas."
            ),
        )

    required_hours_by_role: dict[str, int] = {}
    for shift in shifts:
        if not shift.required_by_role:
            continue
        for role, required in shift.required_by_role.items():
            required_hours_by_role[role] = required_hours_by_role.get(role, 0) + (
                int(shift.duration or 0) * required
            )

    for role, role_required_hours in required_hours_by_role.items():
        role_available_hours = sum(
            staff_hour_limit(member, rules) for member in staff if member.role == role
        )
        if role_required_hours > role_available_hours:
            return ScheduleResponse(
                assignments=[],
                objective_value=None,
                status="no_solution",
                solver_time_seconds=0.0,
                message=(
                    f"No hay capacidad horaria suficiente para el rol {role}. "
                    f"Se requieren {role_required_hours} horas-persona, pero "
                    f"el personal registrado aporta como maximo {role_available_hours}."
                ),
            )

    model = cp_model.CpModel()

    assignment_vars = {
        (member_index, shift_index): model.NewBoolVar(
            f"assign_{member.id}_to_{shift.id}"
        )
        for member_index, member in enumerate(staff)
        for shift_index, shift in enumerate(shifts)
    }

    # Coverage: every shift must be assigned AT LEAST the required number of staff.
    # Using >= instead of == allows the solver to assign extra staff to shifts when
    # there is surplus personnel, so everyone follows the cuarto turno pattern
    # rather than being left idle.
    for shift_index, shift in enumerate(shifts):
        if shift.required_by_role:
            # Total coverage (>=)
            model.Add(
                sum(
                    assignment_vars[(member_index, shift_index)]
                    for member_index in range(len(staff))
                )
                >= shift_total_required(shift)
            )
            # Per-role coverage (>=) — allows surplus within each role
            for role, required in shift.required_by_role.items():
                model.Add(
                    sum(
                        assignment_vars[(member_index, shift_index)]
                        for member_index, member in enumerate(staff)
                        if member.role == role
                    )
                    >= required
                )
            # Senior minimums stay as >= (already correct)
            for role, required in shift.min_senior_by_role.items():
                model.Add(
                    sum(
                        assignment_vars[(member_index, shift_index)]
                        for member_index, member in enumerate(staff)
                        if member.role == role and member.seniority == "senior"
                    )
                    >= required
                )
            if shift.min_senior_staff > 0:
                model.Add(
                    sum(
                        assignment_vars[(member_index, shift_index)]
                        for member_index, member in enumerate(staff)
                        if member.seniority == "senior"
                    )
                    >= shift.min_senior_staff
                )
        else:
            # Total coverage (>=)
            model.Add(
                sum(
                    assignment_vars[(member_index, shift_index)]
                    for member_index in range(len(staff))
                )
                >= int(shift.required_staff or 0)
            )
            if shift.min_senior_staff > 0:
                model.Add(
                    sum(
                        assignment_vars[(member_index, shift_index)]
                        for member_index, member in enumerate(staff)
                        if member.seniority == "senior"
                    )
                    >= shift.min_senior_staff
                )

    preference_penalties = []
    for member_index, member in enumerate(staff):
        rest_until = previous_rest_until(member, rules)
        for shift_index, shift in enumerate(shifts):
            start_date = shift_start_date(shift)
            if shift.id in member.unavailable_shift_ids or (
                start_date is not None and start_date in member.unavailable_dates
            ):
                model.Add(assignment_vars[(member_index, shift_index)] == 0)

            if (
                rest_until is not None
                and shift.start is not None
                and shift.start < rest_until
            ):
                model.Add(assignment_vars[(member_index, shift_index)] == 0)

            if start_date is not None and start_date in member.requested_days_off:
                preference_penalties.append(assignment_vars[(member_index, shift_index)])

    # Optional daily rule: at most one shift per person per day.
    if rules.enforce_one_shift_per_day:
        shifts_by_day: dict[str, list[int]] = {}
        for shift_index, shift in enumerate(shifts):
            if shift.day is not None:
                shifts_by_day.setdefault(shift.day, []).append(shift_index)

        for member_index in range(len(staff)):
            for shift_indexes in shifts_by_day.values():
                model.Add(
                    sum(
                        assignment_vars[(member_index, shift_index)]
                        for shift_index in shift_indexes
                    )
                    <= 1
                )

    # Rest rules: prevent overlaps and enforce minimum rest between shifts.
    for member_index in range(len(staff)):
        for first_index in range(len(shifts)):
            for second_index in range(first_index + 1, len(shifts)):
                if shifts_are_incompatible(
                    shifts[first_index], shifts[second_index], rules,
                ):
                    model.Add(
                        assignment_vars[(member_index, first_index)]
                        + assignment_vars[(member_index, second_index)]
                        <= 1
                    )

    cuarto_turno_pattern_penalties = []

    if rules.enforce_cuarto_turno and rules.force_cuarto_turno_pairing:
        add_cuarto_turno_constraints(model, assignment_vars, staff, shifts)
    elif rules.enforce_cuarto_turno and rules.prefer_cuarto_turno_pattern:
        cuarto_turno_pattern_penalties = build_cuarto_turno_pattern_penalties(
            model, assignment_vars, staff, shifts,
        )

    # Max hours per person.
    for member_index, member in enumerate(staff):
        model.Add(
            sum(
                assignment_vars[(member_index, shift_index)]
                * int(shifts[shift_index].duration or 0)
                for shift_index in range(len(shifts))
            )
            <= staff_hour_limit(member, rules)
        )

    assigned_shift_counts = {}
    for member_index, member in enumerate(staff):
        assigned_shift_count = model.NewIntVar(
            0, len(shifts), f"assigned_shift_count_{member.id}",
        )
        model.Add(
            assigned_shift_count
            == sum(
                assignment_vars[(member_index, shift_index)]
                for shift_index in range(len(shifts))
            )
        )
        assigned_shift_counts[member_index] = assigned_shift_count

    objective_terms = []
    roles = sorted({member.role for member in staff})
    for role in roles:
        role_counts = [
            assigned_shift_counts[member_index]
            for member_index, member in enumerate(staff)
            if member.role == role
        ]
        if not role_counts:
            continue

        max_assigned_shifts = model.NewIntVar(0, len(shifts), f"max_assigned_shifts_{role}")
        min_assigned_shifts = model.NewIntVar(0, len(shifts), f"min_assigned_shifts_{role}")
        model.AddMaxEquality(max_assigned_shifts, role_counts)
        model.AddMinEquality(min_assigned_shifts, role_counts)
        objective_terms.append((max_assigned_shifts - min_assigned_shifts) * 100)

        weekend_shift_indexes = [
            shift_index
            for shift_index, shift in enumerate(shifts)
            if shift.start is not None and shift.start.weekday() >= 5
        ]
        weekend_counts = []
        for member_index, member in enumerate(staff):
            if member.role != role:
                continue
            weekend_count = model.NewIntVar(
                0, len(weekend_shift_indexes), f"weekend_shift_count_{member.id}",
            )
            model.Add(
                weekend_count
                == sum(
                    assignment_vars[(member_index, shift_index)]
                    for shift_index in weekend_shift_indexes
                )
            )
            weekend_counts.append(weekend_count)

        if weekend_counts:
            max_weekend_shifts = model.NewIntVar(0, len(weekend_shift_indexes), f"max_weekend_shifts_{role}")
            min_weekend_shifts = model.NewIntVar(0, len(weekend_shift_indexes), f"min_weekend_shifts_{role}")
            model.AddMaxEquality(max_weekend_shifts, weekend_counts)
            model.AddMinEquality(min_weekend_shifts, weekend_counts)
            objective_terms.append((max_weekend_shifts - min_weekend_shifts) * 25)

    if preference_penalties:
        objective_terms.append(sum(preference_penalties) * 10)

    # Weight 200: breaking the Largo->Noche pattern is more costly than any
    # load imbalance (weight 100), so the solver will always prefer to complete
    # the cuarto turno cycle rather than leaving isolated Largo shifts.
    if cuarto_turno_pattern_penalties:
        objective_terms.append(sum(cuarto_turno_pattern_penalties) * 200)

    model.Minimize(sum(objective_terms) if objective_terms else 0)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.max_time_seconds
    solver.parameters.num_search_workers = settings.num_search_workers

    status_code = solver.Solve(model)
    solver_time = solver.WallTime()
    logger.info(
        "Schedule optimization finished",
        extra={
            "status_code": status_code,
            "objective_value": solver.ObjectiveValue()
            if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            else None,
            "solver_time_seconds": solver_time,
        },
    )

    if status_code not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return ScheduleResponse(
            assignments=[],
            objective_value=None,
            status="no_solution",
            solver_time_seconds=solver_time,
            message=(
                "No se encontró una planificación factible con las restricciones "
                "actuales. Revisa dotación, descansos, horas máximas y cobertura."
            ),
        )

    assignments = []
    for member_index, member in enumerate(staff):
        for shift_index, shift in enumerate(shifts):
            if solver.BooleanValue(assignment_vars[(member_index, shift_index)]):
                assignments.append(Assignment(staff_id=member.id, shift_id=shift.id))

    return ScheduleResponse(
        assignments=assignments,
        objective_value=solver.ObjectiveValue(),
        status="ok",
        solver_time_seconds=solver_time,
        message="Planificación generada correctamente.",
    )
