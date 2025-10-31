import logging
import sys
import os


def configure_logging() -> None:
    # Preparar directorio de logs
    os.makedirs("logs", exist_ok=True)
    log_file = os.path.join("logs", "instagram-webhook.log")

    # Limpiar handlers previos para evitar duplicados en reinicios
    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    formatter = logging.Formatter(fmt)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)

    root.setLevel(logging.INFO)
    root.addHandler(console_handler)
    root.addHandler(file_handler)


