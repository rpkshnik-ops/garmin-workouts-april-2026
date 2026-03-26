"""
Главный скрипт: читает Excel → строит тренировки → загружает в Garmin Connect.

Использование:
    # Показать маппинг без загрузки:
    python main.py --dry-run

    # Загрузить все тренировки:
    python main.py

    # Загрузить только определённые тренировки (по номеру):
    python main.py --workouts 1,2,3

    # Перезаписать существующие дубликаты:
    python main.py --overwrite

Переменные окружения (или интерактивный ввод):
    GARMIN_EMAIL    — логин Garmin Connect
    GARMIN_PASSWORD — пароль Garmin Connect
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass

# Файл Excel задаётся через аргумент или переменную окружения
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
    status: str   # 'created' | 'skipped' | 'error' | 'dry_run'
    garmin_id: str | None = None
    error: str | None = None


def main():
    parser = argparse.ArgumentParser(description='Загрузка тренировок из Excel в Garmin Connect')
    parser.add_argument('--xlsx', default=os.environ.get('TRAINING_XLSX', DEFAULT_XLSX),
                        help='Путь к Excel-файлу')
    parser.add_argument('--dry-run', action='store_true',
                        help='Показать маппинг без загрузки в Garmin')
    parser.add_argument('--workouts', type=str, default=None,
                        help='Номера тренировок через запятую (например, 1,2,3). По умолчанию — все.')
    parser.add_argument('--overwrite', action='store_true',
                        help='Перезаписать тренировки с одинаковым именем')
    parser.add_argument('--save-json', action='store_true', default=True,
                        help='Сохранить JSON каждой тренировки в папку output_json/')
    args = parser.parse_args()

    # ── 1. Читаем Excel ────────────────────────────────────────────────────
    from parse_excel import parse_workouts, print_mapping
    from garmin_workout_builder import build_garmin_workout, describe_workout
    from garmin_client import GarminClient

    logger.info(f"Читаю файл: {args.xlsx}")
    if not os.path.exists(args.xlsx):
        logger.error(f"Файл не найден: {args.xlsx}")
        sys.exit(1)

    workouts = parse_workouts(args.xlsx)
    logger.info(f"Найдено {len(workouts)} тренировок")

    # ── 2. Фильтрация по номерам ───────────────────────────────────────────
    if args.workouts:
        requested = {int(x.strip()) for x in args.workouts.split(',')}
        workouts = [w for w in workouts if w.number in requested]
        logger.info(f"После фильтра: {len(workouts)} тренировок")

    # ── 3. Строим JSON и показываем маппинг ───────────────────────────────
    workout_jsons = []
    for w in workouts:
        j = build_garmin_workout(w)
        workout_jsons.append((w, j))
        print(describe_workout(w))
        print()

    print_mapping(workouts)

    if args.dry_run:
        logger.info("Режим dry-run: загрузка пропущена")
        if args.save_json:
            _save_jsons(workout_jsons)
        return

    # ── 4. Подтверждение пользователя ─────────────────────────────────────
    answer = input(f"\nЗагрузить {len(workouts)} тренировок в Garmin Connect? [y/N]: ").strip().lower()
    if answer != 'y':
        logger.info("Отменено пользователем")
        return

    # ── 5. Подключаемся к Garmin ───────────────────────────────────────────
    client = GarminClient()
    if not client.connect():
        logger.error("Не удалось подключиться к Garmin Connect. Выход.")
        sys.exit(1)

    existing = client.get_existing_workouts()
    logger.info(f"Существующих тренировок в Garmin: {len(existing)}")

    # ── 6. Загружаем ──────────────────────────────────────────────────────
    results: list[UploadResult] = []

    for workout, workout_json in workout_jsons:
        name = workout_json['workoutName']
        dup = client.find_duplicate(name, existing)

        if dup and not args.overwrite:
            logger.info(f"[ПРОПУСК] '{name}' уже существует (id={dup.get('workoutId')})")
            results.append(UploadResult(
                workout_num=workout.number,
                workout_name=name,
                status='skipped',
                garmin_id=str(dup.get('workoutId')),
            ))
            continue

        if args.save_json:
            _save_jsons([(workout, workout_json)])

        resp = client.create_workout(workout_json)
        if resp:
            workout_id = resp.get('workoutId') or resp.get('id') or '?'
            logger.info(f"[OK] '{name}' → id={workout_id}")
            results.append(UploadResult(
                workout_num=workout.number,
                workout_name=name,
                status='created',
                garmin_id=str(workout_id),
            ))
        else:
            results.append(UploadResult(
                workout_num=workout.number,
                workout_name=name,
                status='error',
                error='Ошибка API (см. лог выше)',
            ))

        # Небольшая пауза чтобы не перегружать API
        time.sleep(1.5)

    # ── 7. Отчёт ──────────────────────────────────────────────────────────
    _print_report(results)


def _save_jsons(workout_jsons: list):
    OUTPUT_DIR.mkdir(exist_ok=True)
    for workout, j in workout_jsons:
        safe_name = j['workoutName'].replace(' ', '_').replace('/', '-').replace('—', '-')
        path = OUTPUT_DIR / f"{safe_name}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
        logger.info(f"Сохранён JSON: {path}")


def _print_report(results: list[UploadResult]):
    created = [r for r in results if r.status == 'created']
    skipped = [r for r in results if r.status == 'skipped']
    errors  = [r for r in results if r.status == 'error']

    print("\n" + "="*60)
    print("ОТЧЁТ О ЗАГРУЗКЕ")
    print("="*60)
    print(f"Создано:   {len(created)}")
    print(f"Пропущено: {len(skipped)} (дубликаты)")
    print(f"Ошибки:    {len(errors)}")

    if created:
        print("\nСозданные тренировки:")
        for r in created:
            print(f"  ✓ Т{r.workout_num}: {r.workout_name}  (id={r.garmin_id})")

    if skipped:
        print("\nПропущены (уже существуют):")
        for r in skipped:
            print(f"  ~ Т{r.workout_num}: {r.workout_name}  (id={r.garmin_id})")

    if errors:
        print("\nОшибки:")
        for r in errors:
            print(f"  ✗ Т{r.workout_num}: {r.workout_name}  — {r.error}")

    print("="*60)
    print("Подробности — в файле garmin_upload.log")


if __name__ == '__main__':
    main()
