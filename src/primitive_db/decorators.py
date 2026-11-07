import time
from functools import wraps


def handle_db_errors(func):
    """Report database operation errors and return None on failure."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        """Report a failed operation while preserving successful return values."""
        try:
            return func(*args, **kwargs)
        except FileNotFoundError:
            print(
                "Ошибка: Файл данных не найден. "
                "Возможно, база данных не инициализирована."
            )
        except KeyError as error:
            print(f"Ошибка: Таблица или столбец {error} не найден.")
        except ValueError as error:
            print(f"Ошибка валидации: {error}")
        except OSError as error:
            print(f"Ошибка хранения данных: {error}")
        except Exception as error:
            print(f"Произошла непредвиденная ошибка: {error}")
        return None

    return wrapper


def confirm_action(action_name):
    """Require an explicit lowercase y before calling a destructive function."""

    def decorate(func):
        """Attach the named confirmation to one destructive operation."""

        @wraps(func)
        def wrapper(*args, **kwargs):
            """Execute only after an explicit affirmative response."""
            try:
                answer = input(
                    f'Вы уверены, что хотите выполнить "{action_name}"? [y/n]: '
                ).strip()
            except (EOFError, KeyboardInterrupt):
                print("\nОперация отменена.")
                return None
            if answer != "y":
                print("Операция отменена.")
                return None
            return func(*args, **kwargs)

        return wrapper

    return decorate


def log_time(func):
    """Print the duration of a successful function call."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        """Measure a successful call without changing its result."""
        started = time.monotonic()
        result = func(*args, **kwargs)
        elapsed = time.monotonic() - started
        print(f"Функция {func.__name__} выполнилась за {elapsed:.3f} секунд.")
        return result

    return wrapper


def create_cacher():
    """Return a function whose closure owns an independent result cache."""
    cache = {}

    def cache_result(key, value_func):
        """Reuse an existing result or compute and store a new one."""
        if key in cache:
            print("Результат получен из кэша.")
            return cache[key]
        result = value_func()
        cache[key] = result
        return result

    return cache_result
