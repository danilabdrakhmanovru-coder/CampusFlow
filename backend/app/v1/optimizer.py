"""Scheduling on the campus bell grid."""
from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from os import environ

from ortools.sat.python import cp_model

_DEFAULT_BELL = ((480, 560), (575, 655), (695, 775), (790, 870), (910, 990),
        (1005, 1085), (1100, 1180), (1195, 1275), (1285, 1365))


def bell_grid():
    config = environ.get("CAMPUSFLOW_BELL", "").strip()
    if not config:
        return _DEFAULT_BELL

    def minutes(value):
        parsed = time.fromisoformat(value)
        if parsed.tzinfo or parsed.second or parsed.microsecond:
            raise ValueError("Use HH:MM wall-clock times in CAMPUSFLOW_BELL")
        return parsed.hour*60+parsed.minute

    pairs = tuple(tuple(minutes(value.strip()) for value in part.split("-")) for part in config.split(","))
    if (len(pairs) != 9 or any(len(pair) != 2 or pair[0] >= pair[1] for pair in pairs)
            or any(current[1] > following[0] for current, following in zip(pairs, pairs[1:]))):
        raise ValueError("CAMPUSFLOW_BELL must contain nine ordered non-overlapping intervals")
    return pairs


BELL = bell_grid()


@dataclass(frozen=True)
class Option:
    room: int
    building: str
    slot: int
    extra_seats: int


@dataclass(frozen=True)
class LessonChoices:
    id: int
    people: tuple[str, ...]
    original: Option
    choices: tuple[Option, ...]


def optimize(lessons, fixed, *, seconds=8, transition_minutes=20, days=1):
    """fixed entries carry resource labels and grid indices."""
    model = cp_model.CpModel()
    resources = defaultdict(list)
    people_options = defaultdict(list)
    room_usage = defaultdict(list)
    choices = {}
    costs = []
    for label, slot, building in fixed:
        resources[label, slot].append(1)
        if not label.startswith("r:"):
            people_options[label].append((slot, building, 1))
    for lesson in lessons:
        variables = []
        for index, option in enumerate(lesson.choices):
            use = model.new_bool_var(f"lesson_{lesson.id}_{index}")
            variables.append((use, option))
            resources[f"r:{option.room}", option.slot].append(use)
            room_usage[option.room].append(use)
            for label in lesson.people:
                resources[label, option.slot].append(use)
                people_options[label].append((option.slot, option.building, use))
            moved = (option.room, option.slot) != (lesson.original.room, lesson.original.slot)
            costs.append(use * (8 * moved + option.extra_seats))
        if not variables:
            return {"status": "infeasible", "lesson_id": lesson.id, "assignments": []}
        model.add_exactly_one([use for use, _ in variables])
        choices[lesson.id] = variables
    for uses in resources.values():
        fixed_count = sum(isinstance(use, int) for use in uses)
        variables = [use for use in uses if not isinstance(use, int)]
        if variables:
            model.add(sum(variables) <= (0 if fixed_count else 1))
    for label, entries in people_options.items():
        for day in sorted({slot // len(BELL) for slot, _, _ in entries}):
            base = day * len(BELL)
            occupied = []
            for slot in range(base, base + len(BELL)):
                uses = resources[label, slot]
                flag = model.new_bool_var(f"busy_{label}_{slot}")
                model.add_max_equality(flag, uses or [0])
                occupied.append(flag)
            for slot in range(1, len(BELL) - 1):
                before, after, gap = [model.new_bool_var(f"{name}_{label}_{base}_{slot}") for name in ("before", "after", "gap")]
                model.add_max_equality(before, occupied[:slot])
                model.add_max_equality(after, occupied[slot + 1:])
                model.add(gap >= before + after - occupied[slot] - 1)
                costs.append(40 * gap)
            by_slot = defaultdict(lambda: defaultdict(list))
            for slot, building, use in entries:
                if base <= slot < base + len(BELL) and building:
                    by_slot[slot-base][building].append(use)
            for left_slot in range(len(BELL) - 1):
                for right_slot in range(left_slot + 1, len(BELL)):
                    between = occupied[left_slot + 1:right_slot]
                    for left, right in ((a,b) for a in by_slot[left_slot] for b in by_slot[right_slot] if a!=b):
                        first, second = by_slot[left_slot][left], by_slot[right_slot][right]
                        if not first or not second:
                            continue
                        suffix = f"{label}_{base}_{left_slot}_{right_slot}_{left}_{right}"
                        a, b, travel = [model.new_bool_var(f"{tag}_{suffix}") for tag in ("from", "to", "travel")]
                        model.add_max_equality(a, first)
                        model.add_max_equality(b, second)
                        model.add(travel >= a + b - 1 - sum(between))
                        if BELL[right_slot][0] - BELL[left_slot][1] < transition_minutes:
                            both_fixed = any(type(use) is int for use in first) and any(type(use) is int for use in second)
                            if not both_fixed:
                                model.add(a + b <= 1)
                        costs.append(15 * travel)
    for room, uses in room_usage.items():
        assigned = model.new_int_var(0, (len(BELL)*days), f"load_{room}")
        squared = model.new_int_var(0, (len(BELL)*days)**2, f"load_squared_{room}")
        occupied_count = sum(bool(resources[f"r:{room}", slot]) and any(type(use) is int for use in resources[f"r:{room}", slot]) for slot in range((len(BELL)*days)))
        model.add(assigned == sum(uses) + occupied_count)
        model.add_multiplication_equality(squared, [assigned, assigned])
        costs.append(2 * squared)
    model.minimize(sum(costs))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = seconds
    solver.parameters.num_search_workers = 4
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"status": solver.status_name(status).lower(), "assignments": []}
    assignments = [
        {"lesson_id": lesson_id, "room_id": option.room, "slot": option.slot + 1,
         "building": option.building, "extra_seats": option.extra_seats}
        for lesson_id, variables in choices.items() for use, option in variables if solver.boolean_value(use)
    ]
    return {"status": solver.status_name(status).lower(), "assignments": assignments,
            "objective": solver.objective_value, "best_bound": solver.best_objective_bound}

def measure(assignments, fixed):
    """Report comparable counts for the original and proposed day."""
    busy = defaultdict(dict)
    loads = defaultdict(set)
    for resource, slot, building in fixed:
        if resource.startswith("r:"):
            loads[int(resource[2:])].add(slot)
        else:
            busy[resource, slot // len(BELL)][slot] = building
    spare = 0
    for labels, option in assignments:
        loads[option.room].add(option.slot)
        spare += option.extra_seats
        for label in labels:
            busy[label, option.slot // len(BELL)][option.slot] = option.building
    gaps = {"group_empty_periods": 0, "teacher_empty_periods": 0}
    switches = 0
    for (label, _), day in busy.items():
        occupied = sorted(day)
        name = "group_empty_periods" if label.startswith("g:") else "teacher_empty_periods"
        gaps[name] += occupied[-1] - occupied[0] + 1 - len(occupied)
        switches += sum(bool(day[left] and day[right] and day[left]!=day[right]) for left, right in zip(occupied, occupied[1:]))
    return {**gaps, "building_switches": switches, "extra_seats": spare,
            "squared_room_load": sum(len(slots)**2 for slots in loads.values())}
