from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]


def app_data_dir() -> Path:
    configured = os.environ.get("WEB_LIBRARY_DATA_DIR")
    return Path(configured).expanduser().resolve() if configured else BASE_DIR / "app-data"


def app_db_path() -> Path:
    return app_data_dir() / "app.sqlite"


def libraries_dir() -> Path:
    return app_data_dir() / "libraries"
