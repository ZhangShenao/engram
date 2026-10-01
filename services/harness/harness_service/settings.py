import os


def service_url(name: str, default: str) -> str:
    return os.environ.get(name, default).rstrip("/")


def character_url() -> str:
    return service_url("CHARACTER_URL", "http://127.0.0.1:18411")


def conversation_url() -> str:
    return service_url("CONVERSATION_URL", "http://127.0.0.1:18412")


def memory_url() -> str:
    return service_url("MEMORY_URL", "http://127.0.0.1:18413")
