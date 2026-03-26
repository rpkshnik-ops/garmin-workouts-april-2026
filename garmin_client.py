"""
Клиент Garmin Connect.

Стратегия аутентификации (избегает 429 Too Many Requests):
  1. Проверяем наличие сохранённых OAuth-токенов (~/.garth/).
  2. Если токены есть — используем их (без SSO, без пароля).
  3. Если токенов нет — логинимся email/password, сохраняем токены.

Токены хранятся в GARMIN_TOKENSTORE (по умолчанию ~/.garth/).
Логин/пароль НИКОГДА не логируются.
"""

import getpass
import json
import logging
import os
from pathlib import Path
from typing import Optional

from garminconnect.workout import FitnessEquipmentWorkout

logger = logging.getLogger(__name__)

DEFAULT_TOKENSTORE = str(Path.home() / ".garth")


class GarminClient:
    def __init__(self):
        self.api = None
        self._connected = False

    def connect(self) -> bool:
        import garminconnect

        tokenstore = os.environ.get('GARMIN_TOKENSTORE', DEFAULT_TOKENSTORE)

        # ── Попытка 1: используем сохранённые токены ──────────────────────
        if os.path.isdir(tokenstore):
            try:
                self.api = garminconnect.Garmin()
                self.api.login(tokenstore=tokenstore)
                logger.info("Аутентификация по сохранённым токенам (%s): OK", tokenstore)
                self._connected = True
                return True
            except Exception as e:
                logger.warning("Токены недействительны (%s), пробую email/пароль: %s", tokenstore, e)

        # ── Попытка 2: email + пароль → сохранить токены ──────────────────
        email = os.environ.get('GARMIN_EMAIL') or input('Garmin Connect email: ').strip()
        password = os.environ.get('GARMIN_PASSWORD') or getpass.getpass('Garmin Connect password: ')

        if not email or not password:
            logger.error("Email или пароль не указаны")
            return False

        try:
            self.api = garminconnect.Garmin(email, password)
            self.api.login()

            # Сохраняем токены чтобы следующий запуск не делал SSO
            Path(tokenstore).mkdir(parents=True, exist_ok=True)
            self.api.garth.dump(tokenstore)
            logger.info("Подключение OK. Токены сохранены в: %s", tokenstore)
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
