"""
Строит структуру тренировки для Garmin Connect API.

Использует:
  - FitnessEquipmentWorkout (sportTypeKey: "fitness_equipment")
  - RepeatGroup для группировки подходов → лимит 50 шагов соблюдён
  - conditionTypeKey "reps" для силовых упражнений
  - Все упражнения маппятся на стандартные Garmin exerciseCategory/exerciseName
"""

import re
from typing import Any
from parse_excel import Workout, Exercise

from garminconnect.workout import (
    FitnessEquipmentWorkout,
    WorkoutSegment,
    ExecutableStep,
    RepeatGroup,
    StepType,
    ConditionType,
    TargetType,
    SportType,
    create_repeat_group,
)

# ── Маппинг: русское название → (exerciseCategory, exerciseName) ─────────────
# Garmin Connect категории упражнений для силовых тренировок
EXERCISE_MAP: dict[str, tuple[str, str]] = {
    # ГРУДЬ
    'жим от груди сидя':            ('BENCH_PRESS', 'MACHINE_CHEST_PRESS'),
    'жим от груди':                 ('BENCH_PRESS', 'MACHINE_CHEST_PRESS'),
    'жим лёжа накл':                ('BENCH_PRESS', 'INCLINE_BARBELL_BENCH_PRESS'),
    'жим лёжа гор':                 ('BENCH_PRESS', 'BARBELL_BENCH_PRESS'),
    'жим лёжа':                     ('BENCH_PRESS', 'BARBELL_BENCH_PRESS'),
    'разводка':                     ('FLY', 'DUMBBELL_FLY'),
    'бабочка':                      ('FLY', 'PEC_DECK'),
    'пек-дек':                      ('FLY', 'PEC_DECK'),
    'сведение':                     ('FLY', 'CABLE_CROSSOVER'),
    # ПЛЕЧИ
    'отведение рук в сторону':      ('LATERAL_RAISE', 'DUMBBELL_LATERAL_RAISE'),
    'подъём рук перед собой':       ('FRONT_RAISE', 'DUMBBELL_FRONT_RAISE'),
    'протяжка':                     ('UPRIGHT_ROW', 'BARBELL_UPRIGHT_ROW'),
    'жим над головой':              ('SHOULDER_PRESS', 'SEATED_DUMBBELL_SHOULDER_PRESS'),
    # СПИНА
    'тяга в наклоне':               ('ROW', 'BARBELL_BENT_OVER_ROW'),
    'тяга гор':                     ('ROW', 'SEATED_CABLE_ROW'),
    'тяга изол':                    ('ROW', 'MACHINE_ROW'),
    'подтягивания':                 ('PULLUP', 'PULLUP'),
    'тяга верхн':                   ('PULLDOWN', 'CABLE_PULLDOWN'),
    'пуловер':                      ('PULLOVER', 'CABLE_PULLOVER'),
    # ТРИЦЕПС
    'франц':                        ('TRICEP_EXTENSION', 'EZ_BAR_LYING_TRICEPS_EXTENSION'),
    'разгиб. из-за головы':         ('TRICEP_EXTENSION', 'DUMBBELL_OVERHEAD_TRICEP_EXTENSION'),
    'разгиб. на трицепс':           ('PUSHDOWN', 'CABLE_PUSHDOWN'),
    'трицепс изол':                 ('TRICEP_EXTENSION', 'MACHINE_TRICEP_EXTENSION'),
    'обратные отжимания':           ('DIP', 'DIP'),
    # БИЦЕПС
    'бицепс (z-гриф)':             ('CURL', 'EZ_BAR_CURL'),
    'бицепс z-гриф':               ('CURL', 'EZ_BAR_CURL'),
    'бицепс классика':              ('CURL', 'DUMBBELL_BICEP_CURL'),
    'бицепс молот':                 ('CURL', 'HAMMER_CURL'),
    'бицепс (угл':                  ('CURL', 'CABLE_CURL'),
    # НОГИ
    'жим ног':                      ('LEG_PRESS', 'LEG_PRESS'),
    'румынская тяга':               ('DEADLIFT', 'ROMANIAN_DEADLIFT'),
    'приседания':                   ('SQUAT', 'SQUAT'),
    'выпады':                       ('LUNGE', 'DUMBBELL_LUNGE'),
    'разгибание голени':            ('LEG_EXTENSION', 'LEG_EXTENSION'),
    'сгибание голени':              ('LEG_CURL', 'LEG_CURL'),
    # ПРЕСС / КОРА
    'экстензия (поясница)':         ('BACK_EXTENSION', 'BACK_EXTENSION'),
    'скручивания':                  ('CRUNCH', 'CRUNCH'),
    'обр. скруч':                   ('CRUNCH', 'REVERSE_CRUNCH'),
    'обратные скручивания':         ('CRUNCH', 'REVERSE_CRUNCH'),
    'рим. стул':                    ('SITUP', 'SITUP'),
    'русский твист':                ('RUSSIAN_TWIST', 'RUSSIAN_TWIST'),
    'скрестные касания':            ('CRUNCH', 'BICYCLE_CRUNCH'),
}

NO_TARGET = {
    "workoutTargetTypeId": TargetType.NO_TARGET,
    "workoutTargetTypeKey": "no.target",
    "displayOrder": 1,
}

# conditionTypeId для повторений в силовых тренировках Garmin
REPS_CONDITION = {
    "conditionTypeId": 3,
    "conditionTypeKey": "reps",
    "displayOrder": 3,
    "displayable": True,
}

REST_CONDITION = {
    "conditionTypeId": ConditionType.TIME,
    "conditionTypeKey": "time",
    "displayOrder": 2,
    "displayable": True,
}


def find_exercise_type(name: str) -> tuple[str, str]:
    """Ищет exerciseCategory и exerciseName по русскому названию."""
    name_lower = name.lower()
    for key, value in EXERCISE_MAP.items():
        if key in name_lower:
            return value
    return ('OTHER', 'OTHER')


def parse_reps_to_int(reps_str: str) -> int:
    """Первое число из строки повторений. 'max' → 0."""
    if 'max' in reps_str.lower():
        return 0
    m = re.search(r'\d+', reps_str)
    return int(m.group()) if m else 10


def _make_interval_step(
    step_order: int,
    reps: int,
    exercise: Exercise,
    category: str,
    ex_name: str,
    notes: str = '',
) -> ExecutableStep:
    """Один рабочий шаг (сет) для упражнения."""
    if reps > 0:
        end_cond = REPS_CONDITION
        end_val = float(reps)
    else:
        # max повт → 60 сек
        end_cond = REST_CONDITION
        end_val = 60.0

    step = ExecutableStep(
        stepOrder=step_order,
        stepType={
            "stepTypeId": StepType.INTERVAL,
            "stepTypeKey": "interval",
            "displayOrder": 3,
        },
        endCondition=end_cond,
        endConditionValue=end_val,
        targetType=NO_TARGET,
        exerciseCategory=category,
        exerciseName=ex_name,
    )
    if exercise.weight_kg:
        step.weightValue = exercise.weight_kg
        step.weightUnit = {"unitKey": "kilogram"}
    if notes:
        step.description = notes
    return step


def _make_rest_step(step_order: int, rest_secs: int) -> ExecutableStep:
    """Шаг отдыха между подходами."""
    return ExecutableStep(
        stepOrder=step_order,
        stepType={
            "stepTypeId": StepType.REST,
            "stepTypeKey": "rest",
            "displayOrder": 5,
        },
        endCondition=REST_CONDITION,
        endConditionValue=float(rest_secs),
        targetType=NO_TARGET,
    )


def _is_uniform_reps(reps_list: list[str]) -> bool:
    """Все подходы с одинаковым числом повторений?"""
    parsed = [parse_reps_to_int(r) for r in reps_list]
    return len(set(parsed)) == 1


def build_exercise_steps(
    exercise: Exercise,
    start_order: int,
) -> tuple[list[ExecutableStep | RepeatGroup], int]:
    """
    Строит шаги для одного упражнения.
    Возвращает (steps, next_order).

    Стратегия:
    - Одинаковые повторения → 1 RepeatGroup (экономит шаги)
    - "15/10/10/10" → 1 warmup + 1 RepeatGroup(3×10)
    - Разные повторения → RepeatGroup(N-1×) + 1 финальный, либо раздельные шаги
    Гарантирует общий счёт шагов << 50
    """
    category, ex_name = find_exercise_type(exercise.name)
    comment = exercise.comment or ''
    order = start_order
    steps: list[ExecutableStep | RepeatGroup] = []

    reps_list = exercise.reps_per_set
    sets = len(reps_list)

    # Случай 1: все повторения одинаковые → RepeatGroup
    if _is_uniform_reps(reps_list) and sets > 1:
        reps = parse_reps_to_int(reps_list[0])
        work_step = _make_interval_step(1, reps, exercise, category, ex_name, comment)
        rest_step = _make_rest_step(2, exercise.rest_seconds)
        group = create_repeat_group(
            iterations=sets,
            workout_steps=[work_step, rest_step],
            step_order=order,
        )
        steps.append(group)
        order += 1

    # Случай 2: "warmup + N×одинаковых" → warmup шаг + RepeatGroup
    elif sets >= 3 and len(set(parse_reps_to_int(r) for r in reps_list[1:])) == 1:
        # Первый сет — разминочный (другое кол-во повт)
        warmup_reps = parse_reps_to_int(reps_list[0])
        work_reps = parse_reps_to_int(reps_list[1])

        warmup_step = ExecutableStep(
            stepOrder=order,
            stepType={"stepTypeId": StepType.WARMUP, "stepTypeKey": "warmup", "displayOrder": 1},
            endCondition=REPS_CONDITION,
            endConditionValue=float(warmup_reps),
            targetType=NO_TARGET,
            exerciseCategory=category,
            exerciseName=ex_name,
            description=f"Разминочный. {comment}" if comment else "Разминочный сет",
        )
        if exercise.weight_kg:
            warmup_step.weightValue = exercise.weight_kg * 0.7  # примерный разминочный вес
        steps.append(warmup_step)
        order += 1

        rest_after_warmup = _make_rest_step(order, exercise.rest_seconds)
        steps.append(rest_after_warmup)
        order += 1

        # Рабочие сеты
        work_step = _make_interval_step(1, work_reps, exercise, category, ex_name, comment)
        rest_step = _make_rest_step(2, exercise.rest_seconds)
        group = create_repeat_group(
            iterations=sets - 1,
            workout_steps=[work_step, rest_step],
            step_order=order,
        )
        steps.append(group)
        order += 1

    # Случай 3: единственный сет
    elif sets == 1:
        reps = parse_reps_to_int(reps_list[0])
        work_step = _make_interval_step(order, reps, exercise, category, ex_name, comment)
        steps.append(work_step)
        order += 1

    # Случай 4: прочие комбинации → раздельные шаги (но не больше 4 упражнений таким способом)
    else:
        for i, rep_str in enumerate(reps_list):
            reps = parse_reps_to_int(rep_str)
            work_step = _make_interval_step(order, reps, exercise, category, ex_name,
                                            comment if i == 0 else '')
            steps.append(work_step)
            order += 1
            if i < sets - 1:
                rest_step = _make_rest_step(order, exercise.rest_seconds)
                steps.append(rest_step)
                order += 1

    return steps, order


def build_garmin_workout(workout: Workout) -> FitnessEquipmentWorkout:
    """
    Строит FitnessEquipmentWorkout из тренировки.
    Использует RepeatGroup для экономии шагов (лимит Garmin: 50).
    """
    all_steps: list[ExecutableStep | RepeatGroup] = []
    order = 1

    for exercise in workout.exercises:
        ex_steps, order = build_exercise_steps(exercise, order)
        all_steps.extend(ex_steps)

    fitness_sport = {
        "sportTypeId": SportType.FITNESS_EQUIPMENT,
        "sportTypeKey": "fitness_equipment",
        "displayOrder": 6,
    }

    segment = WorkoutSegment(
        segmentOrder=1,
        sportType=fitness_sport,
        workoutSteps=all_steps,
    )

    w = FitnessEquipmentWorkout(
        workoutName=f"Н{workout.week} Т{workout.number} — {workout.name}",
        estimatedDurationInSecs=_estimate_duration(workout),
        workoutSegments=[segment],
        description=f"Апрель 2026. Неделя {workout.week}, тренировка {workout.number}.",
    )
    return w


def _estimate_duration(workout: Workout) -> int:
    """Грубая оценка продолжительности тренировки в секундах."""
    total = 0
    for ex in workout.exercises:
        avg_reps = sum(parse_reps_to_int(r) for r in ex.reps_per_set) / len(ex.reps_per_set)
        work_time = avg_reps * 3  # ~3 сек на повторение
        total += (work_time + ex.rest_seconds) * ex.sets
    return int(total)


def count_total_steps(workout_obj: FitnessEquipmentWorkout) -> int:
    """Считает все шаги включая вложенные в RepeatGroup."""
    def _count(steps):
        n = 0
        for s in steps:
            n += 1
            if hasattr(s, 'workoutSteps'):
                n += _count(s.workoutSteps)
        return n
    total = 0
    for seg in workout_obj.workoutSegments:
        total += _count(seg.workoutSteps)
    return total


def describe_workout_mapping(workout: Workout) -> str:
    """Текстовое описание маппинга для вывода пользователю."""
    lines = [f"Тренировка {workout.number} (Неделя {workout.week}) — {workout.name}"]
    for ex in workout.exercises:
        cat, ex_type = find_exercise_type(ex.name)
        lines.append(
            f"  • {ex.name}\n"
            f"    → [{cat}/{ex_type}]  "
            f"{ex.sets}×{'|'.join(ex.reps_per_set)}  "
            f"{'🏋 ' + str(ex.weight_kg) + ' кг' if ex.weight_kg else 'Б/в'}  "
            f"Отдых {ex.rest_seconds}с"
        )
    return '\n'.join(lines)
