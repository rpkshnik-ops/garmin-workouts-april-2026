"""
Браузерный логин в Garmin Connect через Playwright.

Зачем: Garmin SSO блокирует автоматические POST-запросы (429 Too Many Requests).
Решение: открыть настоящий браузер, залогиниться вручную (поддерживает MFA),
перехватить OAuth2-токены и сохранить в ~/.garth/ для последующего использования.

Запуск:
    python garmin_browser_login.py

После успешного входа запусти main.py — он подхватит токены автоматически.
"""

import json
import os
import time
from pathlib import Path

TOKENSTORE = Path(os.environ.get("GARMIN_TOKENSTORE", Path.home() / ".garth"))
GARMIN_CONNECT_URL = "https://connect.garmin.com"
GARMIN_SSO_URL = "https://sso.garmin.com"


def extract_and_save_tokens(page) -> bool:
    """
    Пытается извлечь OAuth2-токены из:
    1. localStorage браузера
    2. Перехваченных сетевых запросов
    Возвращает True если токены успешно сохранены.
    """
    # Способ 1: localStorage
    try:
        token_data = page.evaluate("""() => {
            const keys = Object.keys(localStorage);
            const result = {};
            for (const k of keys) {
                result[k] = localStorage.getItem(k);
            }
            return result;
        }""")
        for key, val in token_data.items():
            if val and ('access_token' in str(val) or 'oauth' in key.lower()):
                try:
                    parsed = json.loads(val)
                    if 'access_token' in parsed:
                        _save_garth_token(parsed)
                        print(f"[OK] Токен извлечён из localStorage (ключ: {key})")
                        return True
                except (json.JSONDecodeError, TypeError):
                    pass
    except Exception as e:
        print(f"  localStorage недоступен: {e}")

    return False


def _save_garth_token(token_data: dict):
    """Сохраняет OAuth2-токен в формате garth."""
    TOKENSTORE.mkdir(parents=True, exist_ok=True)

    import time as t
    if 'expires_at' not in token_data:
        expires_in = token_data.get('expires_in', 3600)
        token_data['expires_at'] = t.time() + expires_in
    if 'refresh_token_expires_at' not in token_data:
        refresh_expires_in = token_data.get('refresh_token_expires_in', 7776000)
        token_data['refresh_token_expires_at'] = t.time() + refresh_expires_in

    path = TOKENSTORE / "oauth2_token.json"
    with open(path, 'w') as f:
        json.dump(token_data, f, indent=2)
    print(f"[OK] Токен сохранён: {path}")


def browser_login():
    from playwright.sync_api import sync_playwright

    print("=" * 60)
    print("БРАУЗЕРНЫЙ ВХОД В GARMIN CONNECT")
    print("=" * 60)
    print("1. Откроется браузер с Garmin Connect")
    print("2. Войди в аккаунт вручную (логин, пароль, MFA если нужно)")
    print("3. Когда увидишь главную страницу — нажми Enter здесь")
    print("=" * 60)
    input("Нажми Enter чтобы открыть браузер...")

    intercepted_tokens = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--no-sandbox"],
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )

        # Перехватываем ответы с токенами
        def intercept_response(response):
            try:
                url = response.url
                if ('oauth2/token' in url or 'login-oauth-exchange' in url) and response.status == 200:
                    try:
                        data = response.json()
                        if 'access_token' in data:
                            intercepted_tokens['oauth2'] = data
                            print(f"\n[+] Перехвачен OAuth2-токен с {url}")
                    except Exception:
                        pass
            except Exception:
                pass

        page = context.new_page()
        page.on("response", intercept_response)

        # Открываем Garmin Connect
        page.goto(GARMIN_CONNECT_URL, wait_until="domcontentloaded")
        print(f"\nБраузер открыт. Войди в аккаунт на {GARMIN_CONNECT_URL}")
        print("После успешного входа нажми Enter здесь.")
        input()

        # Пробуем извлечь токены разными способами
        success = False

        # Способ 1: перехваченные токены
        if 'oauth2' in intercepted_tokens:
            _save_garth_token(intercepted_tokens['oauth2'])
            success = True

        # Способ 2: localStorage
        if not success:
            for attempt in range(3):
                if extract_and_save_tokens(page):
                    success = True
                    break
                if attempt < 2:
                    time.sleep(1)

        # Способ 3: cookies → создаём минимальный garth-совместимый файл
        if not success:
            print("\n[!] Не удалось автоматически извлечь OAuth2-токен.")
            print("    Пробую через cookies Garmin Connect...")
            cookies = context.cookies()
            garmin_cookies = [c for c in cookies if 'garmin' in c.get('domain', '').lower()]
            if garmin_cookies:
                TOKENSTORE.mkdir(parents=True, exist_ok=True)
                cookie_path = TOKENSTORE / "cookies.json"
                with open(cookie_path, 'w') as f:
                    json.dump(garmin_cookies, f, indent=2)
                print(f"    Cookies сохранены: {cookie_path}")
                print("    (Будут использованы при следующем запуске)")
                success = True

        browser.close()

        if success:
            print("\n" + "=" * 60)
            print("ВХОД ВЫПОЛНЕН УСПЕШНО")
            print(f"Токены сохранены в: {TOKENSTORE}")
            print("Теперь запускай: python main.py")
            print("=" * 60)
        else:
            print("\n[ERROR] Не удалось сохранить токены.")
            print("Убедись что вошёл в аккаунт и повтори.")

    return success


def verify_tokens() -> bool:
    """Проверяет что сохранённые токены работают."""
    token_path = TOKENSTORE / "oauth2_token.json"
    if not token_path.exists():
        return False
    try:
        import garminconnect
        api = garminconnect.Garmin()
        api.login(tokenstore=str(TOKENSTORE))
        profile = api.get_full_name()
        print(f"[OK] Токены валидны. Пользователь: {profile}")
        return True
    except Exception as e:
        print(f"[!] Токены не прошли проверку: {e}")
        return False


if __name__ == "__main__":
    print("\nШаг 1: Браузерный вход...")
    if browser_login():
        print("\nШаг 2: Проверка токенов...")
        verify_tokens()
