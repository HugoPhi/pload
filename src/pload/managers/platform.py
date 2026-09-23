import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from pload.settings import load_settings, python_settings


class PythonNotFoundError(RuntimeError):
    pass


class ConfigManager:
    """Resolve pload paths and interpreters without hard-coded platform paths."""

    def __init__(self, home=None, venvs_dir=None, state_dir=None):
        configured_home = home or os.environ.get("PLOAD_HOME")
        self.home = Path(configured_home or Path.home() / ".pload").expanduser().resolve()
        self.settings = load_settings(self.home)

        configured_venvs = (
            venvs_dir or os.environ.get("PLOAD_VENVS_DIR") or self.settings.get("venvs_dir")
        )
        configured_state = (
            state_dir or os.environ.get("PLOAD_STATE_DIR") or self.settings.get("state_dir")
        )
        if configured_venvs:
            resolved_venvs = Path(configured_venvs)
        else:
            resolved_venvs = self.home / "venvs"
            legacy_venvs = Path.home() / "venvs"
            may_use_legacy = configured_home is None and not resolved_venvs.exists()
            if may_use_legacy and self._looks_like_legacy_root(legacy_venvs):
                resolved_venvs = legacy_venvs
        self.venv_path = resolved_venvs.expanduser().resolve()
        self.state_path = Path(configured_state or self.home / "state").expanduser().resolve()
        self.platform = sys.platform

        configured_pyenv = os.environ.get("PYENV_ROOT") or os.environ.get("PYENV_HOME")
        self.pyenv_path = Path(configured_pyenv or Path.home() / ".pyenv").expanduser()
        self.pyenv_exe = shutil.which("pyenv")
        self.pyenv_versions = self.pyenv_path / "versions"
        self.python = python_settings(self.home, self.settings)

    @staticmethod
    def _looks_like_legacy_root(path):
        if not path.is_dir():
            return False
        if (path / "scripts").is_dir() or (path / "env_value").is_file():
            return True
        return any(
            child.is_dir() and (child / "pyvenv.cfg").is_file()
            for child in path.iterdir()
        )

    @staticmethod
    def validate_env_name(name):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name or ""):
            return False, "use letters, numbers, dots, underscores, or hyphens"
        if sys.platform == "win32" and re.fullmatch(
            r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", name
        ):
            return False, "this name is reserved by Windows"
        return True, None

    @staticmethod
    def _python_in(prefix):
        prefix = Path(prefix)
        if sys.platform == "win32":
            return prefix / "python.exe"
        return prefix / "bin" / "python"

    def get_python_path(self, version=None):
        if not version or version in {"current", "system"}:
            return Path(sys.executable).resolve()

        candidate = Path(version).expanduser()
        if candidate.is_file():
            return candidate.resolve()

        managed = self.find_managed_python(version)
        if managed:
            return managed

        direct = self._python_in(self.pyenv_versions / version)
        if direct.is_file():
            return direct.resolve()

        if self.pyenv_exe:
            env = os.environ.copy()
            env["PYENV_VERSION"] = version
            result = subprocess.run(
                [self.pyenv_exe, "which", "python"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            resolved = Path(result.stdout.strip())
            if result.returncode == 0 and resolved.is_file():
                return resolved.resolve()

        from pload.managers.pyversion import PythonManager

        discovered = PythonManager(self).find_python(version)
        if discovered:
            return discovered.resolve()

        raise PythonNotFoundError(
            f"Python {version!r} was not found. Pass an interpreter path, run "
            f"'pload python install {version}', or use 'pload python list' to "
            "inspect every discovered interpreter."
        )

    def managed_python_candidates(self):
        root = Path(self.python["install_dir"]).expanduser()
        if not root.is_dir():
            return []
        candidates = []
        for path in root.rglob("python*"):
            if (
                path.is_file()
                and self._is_python_executable_name(path.name)
                and os.access(path, os.X_OK)
            ):
                candidates.append(path)
        return sorted(set(candidates))

    @staticmethod
    def _is_python_executable_name(name, platform=None):
        platform = platform or sys.platform
        normalized = name.lower()
        if platform == "win32":
            return bool(
                re.fullmatch(r"python(?:3(?:\.\d+)?)?\.exe", normalized)
            )
        return bool(re.fullmatch(r"python(?:3(?:\.\d+)?)?", name))

    def find_managed_python(self, version):
        requested = str(version)
        for prefix in ("cpython@", "cpython-"):
            if requested.startswith(prefix):
                requested = requested[len(prefix):]
        matches = []
        for candidate in self.managed_python_candidates():
            try:
                result = subprocess.run(
                    [str(candidate), "--version"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError:
                continue
            output = (result.stdout or result.stderr).strip()
            if result.returncode == 0 and output.startswith("Python "):
                installed = output.split(None, 1)[1]
                if installed == requested or installed.startswith(requested + "."):
                    version_key = tuple(int(item) for item in re.findall(r"\d+", installed))
                    matches.append((version_key, candidate.resolve()))
        return max(matches, default=(None, None))[1]

    def uv_executable(self):
        executable = "uv.exe" if sys.platform == "win32" else "uv"
        runtime_dir = "Scripts" if sys.platform == "win32" else "bin"
        private = self.home / "runtime" / runtime_dir / executable
        if private.is_file():
            return private
        found = shutil.which("uv")
        return Path(found).resolve() if found else None

    def uv_environment(self):
        env = os.environ.copy()
        env["UV_PYTHON_INSTALL_DIR"] = str(Path(self.python["install_dir"]).expanduser())
        env["UV_PYTHON_BIN_DIR"] = str(Path(self.python["bin_dir"]).expanduser())
        env["UV_PYTHON_CACHE_DIR"] = str(Path(self.python["cache_dir"]).expanduser())
        mirror = self.python.get("mirror")
        downloads = self.python.get("downloads_json_url")
        if mirror:
            env["UV_PYTHON_INSTALL_MIRROR"] = mirror
        else:
            env.pop("UV_PYTHON_INSTALL_MIRROR", None)
        if downloads:
            env["UV_PYTHON_DOWNLOADS_JSON_URL"] = downloads
        return env

    @staticmethod
    def venv_python(venv_path):
        path = Path(venv_path)
        if sys.platform == "win32":
            return path / "Scripts" / "python.exe"
        return path / "bin" / "python"

    @classmethod
    def get_pip_command(cls, venv_path):
        return [str(cls.venv_python(venv_path)), "-m", "pip"]

    @staticmethod
    def activate_path(venv_path, shell=None):
        path = Path(venv_path)
        shell = shell or ("powershell" if sys.platform == "win32" else "posix")
        if shell == "powershell":
            return path / "Scripts" / "Activate.ps1"
        if shell == "fish":
            return path / "bin" / "activate.fish"
        return path / "bin" / "activate"

    def resolve_venv_path(
        self,
        version=None,
        message="normal",
        is_local=False,
        project_dir=None,
        target=None,
        name=None,
    ):
        project = Path(project_dir or Path.cwd()).expanduser().resolve()
        if target:
            target_path = Path(target).expanduser()
            if not target_path.is_absolute():
                target_path = project / target_path
            target_path = target_path.resolve()
            return target_path, target_path.name

        if is_local:
            return project / ".venv", ".venv"

        env_name = name or f"{version or 'current'}-{message.replace(' ', '_')}"
        valid, error = self.validate_env_name(env_name)
        if not valid:
            raise ValueError(f"invalid environment name {env_name!r}: {error}")
        return self.venv_path / env_name, env_name

    def ensure_directories(self):
        self.venv_path.mkdir(parents=True, exist_ok=True)
        self.state_path.mkdir(parents=True, exist_ok=True)

    def wrvenv(self, key, value):
        self.ensure_directories()
        file_path = self.state_path / "env_value"
        values = {}
        if file_path.is_file():
            for line in file_path.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    current_key, current_value = line.split("=", 1)
                    values[current_key] = current_value
        values[key] = str(value)
        file_path.write_text(
            "".join(f"{item_key}={item_value}\n" for item_key, item_value in values.items()),
            encoding="utf-8",
        )

    def rdvenv(self, key):
        file_path = self.state_path / "env_value"
        if not file_path.is_file():
            return None
        for line in file_path.read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("#") and "=" in line:
                current_key, value = line.split("=", 1)
                if current_key == key:
                    return value
        return None
