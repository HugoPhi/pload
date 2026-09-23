import os
import shutil
import subprocess
from pathlib import Path

from pload.errors import PloadError
from pload.managers.color import Colors


class VenvManager:
    def __init__(self, config):
        self.config = config

    def create_venv(
        self,
        version=None,
        message="normal",
        is_local=False,
        project_dir=None,
        target=None,
        name=None,
    ):
        try:
            target_path, display_name = self.config.resolve_venv_path(
                version=version,
                message=message,
                is_local=is_local,
                project_dir=project_dir,
                target=target,
                name=name,
            )
        except ValueError as exc:
            raise PloadError(str(exc)) from exc

        if target_path.exists():
            raise PloadError(f"environment already exists: {target_path}")

        python_exe = self.config.get_python_path(version)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        print(f"[*] Creating {Colors.green(display_name)} at {Colors.green(target_path)}")
        process = subprocess.run(
            [str(python_exe), "-m", "venv", str(target_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if process.returncode != 0:
            shutil.rmtree(target_path, ignore_errors=True)
            detail = process.stderr.strip() or process.stdout.strip()
            raise PloadError(f"failed to create {display_name}: {detail}")

        print(f"[*] Created {Colors.green(display_name)}")
        return target_path

    def get_existing_venvs(self):
        root = self.config.venv_path
        if not root.is_dir():
            return []
        return sorted(
            child.name for child in root.iterdir()
            if not child.is_symlink()
            and child.is_dir()
            and (child / "pyvenv.cfg").is_file()
        )

    def resolve_existing(self, venv_name, project_dir=None):
        if venv_name == ".":
            path = Path(project_dir or Path.cwd()).expanduser().resolve() / ".venv"
        else:
            candidate = Path(venv_name).expanduser()
            has_separator = "/" in venv_name or "\\" in venv_name
            if candidate.is_absolute() or has_separator:
                path = candidate
            else:
                path = self.config.venv_path / venv_name
        if path.is_symlink():
            raise PloadError(f"refusing to manage a symlink as an environment: {path}")
        path = path.resolve()
        if not (path / "pyvenv.cfg").is_file():
            raise PloadError(f"not a virtual environment: {path}")
        return path.resolve()

    def remove_venv(self, venv_name, project_dir=None):
        target_path = self.resolve_existing(venv_name, project_dir=project_dir)
        active = Path(os.environ["VIRTUAL_ENV"]).resolve() if os.environ.get("VIRTUAL_ENV") else None
        if active == target_path:
            raise PloadError(f"cannot remove the active environment: {target_path}")
        shutil.rmtree(target_path)
        print(f"[*] Removed {Colors.green(target_path)}")

    def activation_script(self, venv_name, shell=None, project_dir=None):
        path = self.resolve_existing(venv_name, project_dir=project_dir)
        script = self.config.activate_path(path, shell=shell)
        if not script.is_file():
            raise PloadError(f"activation script not found: {script}")
        return script
