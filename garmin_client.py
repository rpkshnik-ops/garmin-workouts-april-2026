"""
Клиент для Garmin Connect.
Аутентификация через переменные окружения или интерактивный ввод.
Логин/пароль НИКОГДА не выводятся в логи.
"""

import os
import getpass
import json
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class GarminClient:
    def __init__(self):
        self.api = None
        self._connected = False

    def connect(self) -> bool:
        """
        Подключается к Garmin Connect.
        Использует переменные окружения GARMIN_EMAIL и GARMIN_PASSWORD.
        Если не заданы — запрашивает интерактивно (без вывода в лог).
        """
        email = os.environ.get('GARMIN_EMAIL') or input('Garmin Connect email: ').strip()
        password = os.environ.get('GARMIN_PASSWORD') or getpass.getpass('Garmin Connect password: ')

        if not email or not password:
            logger.error("Email или пароль не указаны")
            return False

        try:
            import garminconnect
            self.api = garminconnect.Garmin(email, password)
            self.api.login()
            logger.info("Подключение к Garmin Connect успешно")
            self._connected = True
            return True
        except Exception as e:
            logger.error(f"Ошибка подключения к Garmin Connect: {type(e).__name__}: {e}")
            return False

    def get_existing_workouts(self) -> list[dict]:
        """Получает список существующих тренировок."""
        if not self._connected:
            return []
        try:
            workouts = self.api.get_workouts(0, 100)
            return workouts if workouts else []
        except Exception as e:
            logger.warning(f"Не удалось получить список тренировок: {e}")
            return []

    def find_duplicate(self, workout_name: str, existing: list[dict]) -> Optional[dict]:
        """Ищет тренировку с таким же именем в существующих."""
        for w in existing:
            if w.get('workoutName') == workout_name:
                return w
        return None

    def create_workout(self, workout_json: dict) -> Optional[dict]:
        """
        Создаёт одну тренировку. Возвращает ответ API или None при ошибке.
        """
        if not self._connected:
            logger.error("Не подключён к Garmin Connect")
            return None
        try:
            result = self.api.add_workout(workout_json)
            logger.info(f"Создана тренировка: {workout_json.get('workoutName')}")
            return result
        except Exception as e:
            logger.error(f"Ошибка создания '{workout_json.get('workoutName')}': {type(e).__name__}: {e}")
            return None

    def save_workout_json(self, workout_json: dict, filepath: str):
        """Сохраняет JSON тренировки на диск (для отладки и архива)."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(workout_json, f, ensure_ascii=False, indent=2)
