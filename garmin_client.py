"""
Клиент Garmin Connect.
- Аутентификация через GARMIN_EMAIL / GARMIN_PASSWORD (переменные окружения)
  или интерактивный ввод (getpass — пароль не выводится в терминал).
- Логин/пароль НИКОГДА не логируются.
- Для загрузки использует garminconnect.upload_workout() → garth.connectapi POST.
"""

import getpass
import json
import logging
import os
from typing import Optional

from garminconnect.workout import FitnessEquipmentWorkout

logger = logging.getLogger(__name__)


class GarminClient:
    def __init__(self):
        self.api = None
        self._connected = False

    def connect(self) -> bool:
        email = os.environ.get('GARMIN_EMAIL') or input('Garmin Connect email: ').strip()
        password = os.environ.get('GARMIN_PASSWORD') or getpass.getpass('Garmin Connect password: ')

        if not email or not password:
            logger.error("Email или пароль не указаны")
            return False

        try:
            import garminconnect
            self.api = garminconnect.Garmin(email, password)
            self.api.login()
            logger.info("Подключение к Garmin Connect: OK")
            self._connected = True
            return True
        except Exception as e:
            logger.error("Ошибка подключения: %s: %s", type(e).__name__, e)
            return False

    def get_existing_workouts(self) -> list[dict]:
        if not self._connected:
            return []
        try:
            return self.api.get_workouts(0, 200) or []
        except Exception as e:
            logger.warning("Не удалось получить список тренировок: %s", e)
            return []

    def find_duplicate(self, name: str, existing: list[dict]) -> Optional[dict]:
        for w in existing:
            if w.get('workoutName') == name:
                return w
        return None

    def upload_workout(self, workout: FitnessEquipmentWorkout) -> Optional[dict]:
        """Загружает тренировку, возвращает ответ API или None."""
        if not self._connected:
            logger.error("Не подключён к Garmin Connect")
            return None
        try:
            payload = workout.to_dict()
            result = self.api.upload_workout(payload)
            logger.info("Создана тренировка: %s", workout.workoutName)
            return result
        except Exception as e:
            logger.error("Ошибка загрузки '%s': %s: %s", workout.workoutName, type(e).__name__, e)
            return None

    def schedule_workout(self, workout_id: str | int, date_str: str) -> bool:
        """Добавляет тренировку в календарь Garmin Connect."""
        if not self._connected:
            return False
        try:
            self.api.schedule_workout(workout_id, date_str)
            logger.info("Запланирована тренировка %s на %s", workout_id, date_str)
            return True
        except Exception as e:
            logger.warning("Не удалось запланировать тренировку: %s", e)
            return False

    def save_json(self, workout: FitnessEquipmentWorkout, filepath: str):
        """Сохраняет JSON тренировки на диск."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(workout.to_dict(), f, ensure_ascii=False, indent=2)
