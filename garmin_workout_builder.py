"""
Строит JSON-структуру тренировки в формате Garmin Connect API.
Основан на анализе реального API Garmin Connect (strength_training).
"""

from typing import Optional
from parse_excel import Workout, Exercise


# Маппинг русских названий упражнений → Garmin exercise category/name
# Garmin использует предопределённые категории. Для неизвестных — CUSTOM
EXERCISE_CATEGORY_MAP = {
    # ГРУДЬ
    'жим от груди':         ('BENCH_PRESS', 'MACHINE_CHEST_PRESS'),
    'жим лёжа':             ('BENCH_PRESS', 'BARBELL_BENCH_PRESS'),
    'жим лёжа накл':        ('BENCH_PRESS', 'INCLINE_BARBELL_BENCH_PRESS'),
    'жим лёжа гор':         ('BENCH_PRESS', 'BARBELL_BENCH_PRESS'),
    'разводка':             ('FLY', 'DUMBBELL_FLY'),
    'сведение':             ('FLY', 'CABLE_CROSSOVER'),
    'бабочка':              ('FLY', 'PEC_DECK'),
    'пек-дек':              ('FLY', 'PEC_DECK'),
    # ПЛЕЧИ
    'отведение рук в сторону': ('LATERAL_RAISE', 'DUMBBELL_LATERAL_RAISE'),
    'подъём рук перед собой':  ('FRONT_RAISE', 'DUMBBELL_FRONT_RAISE'),
    'протяжка':             ('UPRIGHT_ROW', 'BARBELL_UPRIGHT_ROW'),
    'жим над головой':      ('SHOULDER_PRESS', 'SEATED_DUMBBELL_SHOULDER_PRESS'),
    # СПИНА
    'тяга в наклоне':       ('ROW', 'BARBELL_BENT_OVER_ROW'),
    'подтягивания':         ('PULLUP', 'PULLUP'),
    'тяга верхн':           ('PULLDOWN', 'CABLE_PULLDOWN'),
    'тяга гор':             ('ROW', 'SEATED_CABLE_ROW'),
    'тяга изол':            ('ROW', 'MACHINE_ROW'),
    'пуловер':              ('PULLOVER', 'CABLE_PULLOVER'),
    # ТРИЦЕПС
    'франц':                ('TRICEP_EXTENSION', 'EZ_BAR_LYING_TRICEPS_EXTENSION'),
    'разгиб. из-за головы': ('TRICEP_EXTENSION', 'DUMBBELL_OVERHEAD_TRICEP_EXTENSION'),
    'разгиб. на трицепс':   ('PUSHDOWN', 'CABLE_PUSHDOWN'),
    'трицепс изол':         ('TRICEP_EXTENSION', 'MACHINE_TRICEP_EXTENSION'),
    'обратные отжимания':   ('DIP', 'DIP'),
    # БИЦЕПС
    'бицепс (z-гриф)':      ('CURL', 'EZ_BAR_CURL'),
    'бицепс z-гриф':        ('CURL', 'EZ_BAR_CURL'),
    'бицепс классика':      ('CURL', 'DUMBBELL_BICEP_CURL'),
    'бицепс молот':         ('CURL', 'HAMMER_CURL'),
    'бицепс (угл':          ('CURL', 'CABLE_CURL'),
    # НОГИ
    'жим ног':              ('LEG_PRESS', 'LEG_PRESS'),
    'румынская тяга':       ('DEADLIFT', 'ROMANIAN_DEADLIFT'),
    'приседания':           ('SQUAT', 'SQUAT'),
    'выпады':               ('LUNGE', 'DUMBBELL_LUNGE'),
    'разгибание голени':    ('LEG_EXTENSION', 'LEG_EXTENSION'),
    'сгибание голени':      ('LEG_CURL', 'LEG_CURL'),
    # ПРЕСС / КОРА
    'экстензия (поясница)': ('BACK_EXTENSION', 'HYPEREXTENSION'),
    'скручивания':          ('CRUNCH', 'CRUNCH'),
    'обр. скруч':           ('CRUNCH', 'REVERSE_CRUNCH'),
    'обратные скручивания': ('CRUNCH', 'REVERSE_CRUNCH'),
    'рим. стул':            ('CRUNCH', 'ROMAN_CHAIR_SITUP'),
    'русский твист':        ('CRUNCH', 'RUSSIAN_TWIST'),
    'скрестные касания':    ('CRUNCH', 'BICYCLE_CRUNCH'),
}


def find_exercise_category(name: str) -> tuple[str, str]:
    """Ищет категорию и тип упражнения Garmin по русскому названию."""
    name_lower = name.lower()
    for key, (category, exercise_type) in EXERCISE_CATEGORY_MAP.items():
        if key in name_lower:
            return category, exercise_type
    # Не найдено — возвращаем CUSTOM
    return 'OTHER', 'CUSTOM'


def parse_reps_to_int(reps_str: str) -> int:
    """Извлекает первое числовое значение из строки повторений."""
    import re
    # "10–12" → 10, "max" → 0, "25" → 25
    if 'max' in reps_str.lower():
        return 0
    m = re.search(r'\d+', reps_str)
    return int(m.group()) if m else 10


def build_workout_step(exercise: Exercise, step_order: int) -> list[dict]:
    """
    Строит шаги для одного упражнения.
    Возвращает список шагов (один на каждый подход).
    """
    steps = []
    category, exercise_name = find_exercise_category(exercise.name)

    for set_idx, reps_str in enumerate(exercise.reps_per_set):
        reps = parse_reps_to_int(reps_str)

        step: dict = {
            "type": "ExecutableStepDTO",
            "stepOrder": step_order + set_idx,
            "stepType": {
                "stepTypeId": 1,
                "stepTypeKey": "interval"
            },
            "childStepId": None,
            "description": exercise.comment if set_idx == 0 else None,
            "exerciseCategory": category,
            "exerciseName": exercise_name,
            "displayName": exercise.name,
        }

        # Тип цели: количество повторений
        if reps > 0:
            step["endCondition"] = {
                "conditionTypeKey": "reps",
                "conditionTypeId": 3
            }
            step["endConditionValue"] = reps
        else:
            # max — ставим time 60 сек
            step["endCondition"] = {
                "conditionTypeKey": "time",
                "conditionTypeId": 2
            }
            step["endConditionValue"] = 60

        # Вес (только если числовой)
        if exercise.weight_kg:
            step["weightValue"] = exercise.weight_kg
            step["weightUnit"] = {"unitKey": "kilogram"}

        # Отдых после каждого подхода (кроме последнего)
        if set_idx < len(exercise.reps_per_set) - 1:
            rest_step = {
                "type": "ExecutableStepDTO",
                "stepOrder": step_order + set_idx + 0.5,
                "stepType": {
                    "stepTypeId": 2,
                    "stepTypeKey": "rest"
                },
                "childStepId": None,
                "endCondition": {
                    "conditionTypeKey": "time",
                    "conditionTypeId": 2
                },
                "endConditionValue": exercise.rest_seconds,
            }
            steps.append(step)
            steps.append(rest_step)
        else:
            steps.append(step)

    return steps


def build_garmin_workout(workout: Workout) -> dict:
    """
    Собирает полный JSON тренировки для Garmin Connect API.
    """
    all_steps = []
    step_order = 1

    for exercise in workout.exercises:
        ex_steps = build_workout_step(exercise, step_order)
        # Переназначаем stepOrder как целые числа
        for i, s in enumerate(ex_steps):
            s["stepOrder"] = step_order + i
        step_order += len(ex_steps)
        all_steps.extend(ex_steps)

    workout_json = {
        "workoutName": f"Н{workout.week} Т{workout.number} — {workout.name}",
        "description": f"Апрель 2026. Неделя {workout.week}, тренировка {workout.number}. {workout.name}.",
        "sportType": {
            "sportTypeId": 4,
            "sportTypeKey": "strength_training"
        },
        "subSportType": None,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": {
                    "sportTypeId": 4,
                    "sportTypeKey": "strength_training"
                },
                "workoutSteps": all_steps
            }
        ]
    }

    return workout_json


def describe_workout(workout: Workout) -> str:
    """Короткое текстовое описание тренировки для лога."""
    lines = [f"Тренировка {workout.number} (Неделя {workout.week}) — {workout.name}"]
    for ex in workout.exercises:
        cat, ex_type = find_exercise_category(ex.name)
        lines.append(f"  • {ex.name} → [{cat}/{ex_type}]  {ex.sets}×{'|'.join(ex.reps_per_set)}  {ex.weight}")
    return '\n'.join(lines)
