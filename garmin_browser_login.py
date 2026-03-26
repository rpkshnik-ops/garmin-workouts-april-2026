"""
Браузерный логин в Garmin Connect через Playwright.

Использует НАСТОЯЩИЙ Chrome (не Chromium Playwright) с реальным профилем —
Garmin не может отличить это от обычного пользователя.

Запуск:
    python garmin_browser_login.py

После успешного входа запусти main.py — токены подхватятся автоматически.
"""

import json
import os
import time
from pathlib import Path

TOKENSTORE = Path(os.environ.get("GARMIN_TOKENSTORE", Path.home() / ".garth"))
CHROME_EXE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GARMIN_CONNECT_URL = "https://connect.garmin.com"


def _save_oauth2_token(token_data: dict):
    TOKENSTORE.mkdir(parents=True, exist_ok=True)
    now = time.time()
    token_data.setdefault('expires_at', now + token_data.get('expires_in', 3600))
    token_data.setdefault('refresh_token_expires_at',
                          now + token_data.get('refresh_token_expires_in', 7776000))
    path = TOKENSTORE / "oauth2_token.json"
    with open(path, 'w') as f:
        json.dump(token_data, f, indent=2)
    print(f"[OK] OAuth2-токен сохранён: {path}")


def browser_login():
    from playwright.sync_api import sync_playwright
    from playwright_stealth import stealth

    print("=" * 60)
    print("ВХОД В GARMIN CONNECT (реальный Chrome)")
    print("=" * 60)
    print(f"  Chrome: {CHROME_EXE}")
    print(f"  Токены: {TOKENSTORE}")
    print()
    print("Откроется браузер Chrome. Войди в аккаунт.")
    print("Когда попадёшь на главную страницу — вернись сюда и нажми Enter.")
    print("=" * 60)
    input("\nНажми Enter чтобы открыть браузер... ")

    intercepted: dict = {}

    with sync_playwright() as p:
        # Запускаем НАСТОЯЩИЙ Chrome (не Playwright Chromium)
        browser = p.chromium.launch(
            executable_path=CHROME_EXE,
            headless=False,
            channel="chrome",
            args=[
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )

        page = context.new_page()

        # Применяем stealth-патчи (убирает navigator.webdriver и прочие маркеры бота)
        stealth(page)

        # Перехватываем OAuth2-токен из сетевых запросов
        def on_response(response):
            try:
                url = response.url
                if response.status == 200 and any(k in url for k in (
                    'oauth2/token', 'login-oauth-exchange', 'oauth-service/oauth/token'
                )):
                    try:
                        data = response.json()
                        if 'access_token' in data:
                            intercepted['oauth2'] = data
                            print(f"\n  [+] Перехвачен токен: {url.split('?')[0]}")
                    except Exception:
                        pass
            except Exception:
                pass

        page.on("response", on_response)

        page.goto(GARMIN_CONNECT_URL, wait_until="domcontentloaded", timeout=30000)

        print(f"\n  Браузер открыт: {GARMIN_CONNECT_URL}")
        print("  Войди в аккаунт. Нажми Enter здесь когда увидишь главную страницу.")
        input()

        # ── Извлекаем токены ──────────────────────────────────────────────
        success = False

        # 1. Перехваченный токен из сети
        if 'oauth2' in intercepted:
            _save_oauth2_token(intercepted['oauth2'])
            success = True

        # 2. localStorage / sessionStorage
        if not success:
            for storage_type in ('localStorage', 'sessionStorage'):
                try:
                    items = page.evaluate(f"""() => {{
                        const result = {{}};
                        for (let i = 0; i < {storage_type}.length; i++) {{
                            const k = {storage_type}.key(i);
                            result[k] = {storage_type}.getItem(k);
                        }}
                        return result;
                    }}""")
                    for key, val in items.items():
                        if val and 'access_token' in str(val):
                            try:
                                data = json.loads(val)
                                if 'access_token' in data:
                                    _save_oauth2_token(data)
                                    print(f"  [+] Токен из {storage_type}[{key}]")
                                    success = True
                                    break
                            except (json.JSONDecodeError, TypeError):
                                pass
                    if success:
                        break
                except Exception as e:
                    print(f"  {storage_type} недоступен: {e}")

        # 3. Cookies как запасной вариант
        if not success:
            cookies = context.cookies()
            garmin_cookies = [c for c in cookies
                              if 'garmin' in c.get('domain', '').lower()
                              and c.get('name', '') not in ('', 'JSESSIONID')]
            if garmin_cookies:
                TOKENSTORE.mkdir(parents=True, exist_ok=True)
                cookie_path = TOKENSTORE / "cookies.json"
                with open(cookie_path, 'w') as f:
                    json.dump(garmin_cookies, f, indent=2)
                print(f"  [+] Cookies сохранены ({len(garmin_cookies)} шт): {cookie_path}")
                success = _try_cookie_auth(garmin_cookies)

        browser.close()

    if success:
        print("\n" + "=" * 60)
        print("ВХОД ВЫПОЛНЕН")
        print(f"Токены: {TOKENSTORE}")
        print("Теперь запускай: python main.py")
        print("=" * 60)
    else:
        print("\n[!] Не удалось сохранить токены автоматически.")
        print("    Попробуй вариант с ручными cookies (см. ниже).")
        _print_manual_instructions()

    return success


def _try_cookie_auth(cookies: list) -> bool:
    """Пробует создать garth-сессию через cookies."""
    try:
        import requests
        session = requests.Session()
        for c in cookies:
            session.cookies.set(
                c['name'], c['value'],
                domain=c.get('domain', '.garmin.com'),
                path=c.get('path', '/')
            )
        # Проверяем что сессия рабочая
        r = session.get(
            "https://connect.garmin.com/userprofile-service/userprofile/personal-information",
            headers={"nk": "NT"},
            timeout=10
        )
        if r.status_code == 200:
            # Сохраняем cookies для garth
            TOKENSTORE.mkdir(parents=True, exist_ok=True)
            # Создаём минимальный pseudo-token из cookies
            cookie_dict = {c['name']: c['value'] for c in cookies}
            with open(TOKENSTORE / "session_cookies.json", 'w') as f:
                json.dump(cookie_dict, f, indent=2)
            print(f"  [OK] Cookie-сессия работает (статус {r.status_code})")
            return True
        print(f"  Cookie-сессия не работает (статус {r.status_code})")
    except Exception as e:
        print(f"  Ошибка проверки: {e}")
    return False


def _print_manual_instructions():
    print("""
РУЧНОЙ СПОСОБ (если автоматический не сработал):
─────────────────────────────────────────────────
1. Открой Chrome → connect.garmin.com → войди в аккаунт
2. F12 → Application → Local Storage → https://connect.garmin.com
3. Найди ключ с "access_token" в значении
4. Скопируй всё значение (это JSON)
5. Сохрани как: C:\\Users\\User\\.garth\\oauth2_token.json
6. Запускай: python main.py
""")


def verify_tokens() -> bool:
    """Проверяет что сохранённые токены работают."""
    token_path = TOKENSTORE / "oauth2_token.json"
    if not token_path.exists():
        print(f"[!] Файл токена не найден: {token_path}")
        return False
    try:
        import garminconnect
        api = garminconnect.Garmin()
        api.login(tokenstore=str(TOKENSTORE))
        name = api.get_full_name()
        print(f"[OK] Токены валидны. Аккаунт: {name}")
        return True
    except Exception as e:
        print(f"[!] Токены не прошли проверку: {e}")
        return False


if __name__ == "__main__":
    print("\nШаг 1: Браузерный вход...")
    if browser_login():
        print("\nШаг 2: Проверка токенов через API...")
        verify_tokens()
