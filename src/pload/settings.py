import json
import os
import sys
from pathlib import Path

from pload.errors import PloadError

USTC_PYTHON_MIRROR = (
    "https://mirrors.ustc.edu.cn/github-release/astral-sh/"
    "python-build-standalone/"
)


def default_bin_dir():
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        return Path(local) / "Programs" / "pload" / "bin" if local else Path.home() / "bin"
    return Path.home() / ".local" / "bin"


def config_path(home):
    return Path(home) / "config.json"


def load_settings(home):
    path = config_path(home)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PloadError(f"cannot read configuration {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PloadError(f"configuration must contain a JSON object: {path}")
    return data


def save_settings(home, settings):
    home = Path(home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    path = config_path(home)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def python_settings(home, settings=None):
    home = Path(home).expanduser().resolve()
    configured = dict((settings or {}).get("python", {}))
    configured.setdefault("provider", "uv")
    configured.setdefault("install_dir", str(home / "pythons"))
    configured.setdefault("bin_dir", str(home / "python-bin"))
    configured.setdefault("cache_dir", str(home / "cache" / "python"))
    configured.setdefault("source", "official")
    configured.setdefault("mirror", None)
    configured.setdefault("downloads_json_url", None)
    return configured
