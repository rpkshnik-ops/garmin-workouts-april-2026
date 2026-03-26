"""
Главный скрипт: Excel → Garmin Connect тренировки.

Использование:
    # Проверить маппинг без загрузки:
    python main.py --dry-run

    # Загрузить все 12 тренировок:
    python main.py

    # Загрузить только 1, 2, 3:
    python main.py --workouts 1,2,3

    # Перезаписать существующие:
    python main.py --overwrite

Переменные окружения:
    GARMIN_EMAIL       — логин Garmin Connect
    GARMIN_PASSWORD    — пароль Garmin Connect
    TRAINING_XLSX      — путь к Excel (опционально)
"""

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_XLSX = r'C:\Users\User\Downloads\Программа_тренировок_апрель_2026.xlsx'
OUTPUT_DIR = Path(__file__).parent / 'output_json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('garmin_upload.log', encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    workout_num: int
    workout_name: str
    status: str          # 'created' | 'skipped' | 'error' | 'dry_run'
    garmin_id: str = ''
    step_count: int = 0
    error: str = ''


def main():
    parser = argparse.ArgumentParser(description='Загрузка тренировок из Excel в Garmin Connect')
    parser.add_argument('--xlsx', default=os.environ.get('TRAINING_XLSX', DEFAULT_XLSX))
    parser.add_argument('--dry-run', action='store_true', help='Только показать маппинг')
    parser.add_argument('--workouts', type=str, default=None,
                        help='Номера через запятую: 1,2,3')
    parser.add_argument('--overwrite', action='store_true',
                        help='Перезаписать существующие')
    args = parser.parse_args()

    from parse_excel import parse_workouts, print_mapping
    from garmin_workout_builder import (
        build_garmin_workout, describe_workout_mapping, count_total_steps
    )
    from garmin_client import GarminClient

    # ── 1. Читаем Excel ────────────────────────────────────────────────────
    if not os.path.exists(args.xlsx):
        logger.error("Файл не найден: %s", args.xlsx)
        sys.exit(1)

    logger.info("Читаю: %s", args.xlsx)
    workouts = parse_workouts(args.xlsx)
    logger.info("Найдено тренировок: %d", len(workouts))

    if args.workouts:
        requested = {int(x.strip()) for x in args.workouts.split(',')}
        workouts = [w for w in workouts if w.number in requested]
        logger.info("После фильтра: %d тренировок", len(workouts))

    # ── 2. Строим объекты Garmin ───────────────────────────────────────────
    workout_objects = []
    for w in workouts:
        obj = build_garmin_workout(w)
        steps = count_total_steps(obj)
        workout_objects.append((w, obj, steps))
        print(describe_workout_mapping(w))
        print(f"  [Шагов в Garmin: {steps}/50]\n")

    print_mapping(workouts)

    # Предупреждение если превышаем лимит
    over_limit = [(w.number, steps) for w, _, steps in workout_objects if steps > 50]
    if over_limit:
        logger.warning("ВНИМАНИЕ: тренировки превышают лимит 50 шагов: %s", over_limit)

    # ── 3. Сохраняем JSON ─────────────────────────────────────────────────
    OUTPUT_DIR.mkdir(exist_ok=True)
    for workout, obj, steps in workout_objects:
        fname = obj.workoutName.replace(' ', '_').replace('/', '-').replace('—', '-')
        path = OUTPUT_DIR / f"{fname}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(obj.to_dict(), f, ensure_ascii=False, indent=2)

    logger.info("JSON файлы сохранены в: %s", OUTPUT_DIR)

    if args.dry_run:
        logger.info("Режим --dry-run: загрузка пропущена")
        return

    # ── 4. Подтверждение ──────────────────────────────────────────────────
    ans = input(f"\nЗагрузить {len(workouts)} тренировок в Garmin Connect? [y/N]: ").strip().lower()
    if ans != 'y':
        logger.info("Отменено")
        return

    # ── 5. Подключаемся ───────────────────────────────────────────────────
    client = GarminClient()
    if not client.connect():
        sys.exit(1)

    existing = client.get_existing_workouts()
    logger.info("Существующих тренировок в Garmin: %d", len(existing))

    # ── 6. Загружаем ──────────────────────────────────────────────────────
    results: list[UploadResult] = []

    for workout, obj, steps in workout_objects:
        name = obj.workoutName
        dup = client.find_duplicate(name, existing)

        if dup and not args.overwrite:
            dup_id = str(dup.get('workoutId', '?'))
            logger.info("[ПРОПУСК] '%s' уже существует (id=%s)", name, dup_id)
            results.append(UploadResult(workout.number, name, 'skipped', dup_id, steps))
            continue

        resp = client.upload_workout(obj)
        if resp:
            wid = str(resp.get('workoutId') or resp.get('id') or '?')
            results.append(UploadResult(workout.number, name, 'created', wid, steps))
        else:
            results.append(UploadResult(workout.number, name, 'error', '',
                                        steps, 'Ошибка API (см. лог)'))

        time.sleep(1.5)  # пауза чтобы не перегружать API

    # ── 7. Отчёт ──────────────────────────────────────────────────────────
    _print_report(results)


def _print_report(results: list[UploadResult]):
    created = [r for r in results if r.status == 'created']
    skipped = [r for r in results if r.status == 'skipped']
    errors  = [r for r in results if r.status == 'error']

    print("\n" + "=" * 60)
    print("ОТЧЁТ О ЗАГРУЗКЕ")
    print("=" * 60)
    print(f"Создано:   {len(created)}")
    print(f"Пропущено: {len(skipped)} (дубликаты)")
    print(f"Ошибки:    {len(errors)}")

    if created:
        print("\nСозданные тренировки:")
        for r in created:
            print(f"  OK  Т{r.workout_num}: {r.workout_name}  (id={r.garmin_id}, шагов={r.step_count})")

    if skipped:
        print("\nПропущены (уже существуют):")
        for r in skipped:
            print(f"  ~   Т{r.workout_num}: {r.workout_name}  (id={r.garmin_id})")

    if errors:
        print("\nОшибки:")
        for r in errors:
            print(f"  ERR Т{r.workout_num}: {r.workout_name}  — {r.error}")

    print("=" * 60)
    print("Детали — в garmin_upload.log")


if __name__ == '__main__':
    main()
