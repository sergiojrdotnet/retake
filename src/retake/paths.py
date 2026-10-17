from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_data_path, user_log_path, user_videos_path

APP = "retake"


def config_dir() -> Path:
    return user_config_path(APP, ensure_exists=True)


def data_dir() -> Path:
    return user_data_path(APP, ensure_exists=True)


def cache_dir() -> Path:
    return user_cache_path(APP, ensure_exists=True)


def logs_dir() -> Path:
    return user_log_path(APP, ensure_exists=True)


def models_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_languages_dir() -> Path:
    return data_dir() / "languages"


def default_projects_dir() -> Path:
    return user_videos_path() / "Retake"


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR") or str(cache_dir())
    path = Path(base) / APP
    path.mkdir(parents=True, exist_ok=True)
    return path


def control_socket() -> Path:
    return runtime_dir() / "control.sock"


def omarchy_theme_dir() -> Path:
    return Path.home() / ".local/state/omarchy/current/theme"
