import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.text import Text

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
        description=None,
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
        command = [str(python_exe), "-m", "venv", str(target_path)]
        console = Console(highlight=False)
        if console.is_terminal:
            status = Text.assemble(
                ("Creating ", "bold cyan"),
                (display_name, "bold green"),
                (" at ", "dim"),
                (str(target_path), "green"),
            )
            with console.status(status, spinner="dots", spinner_style="bold cyan"):
                process = subprocess.run(
                    command, capture_output=True, text=True, check=False
                )
        else:
            print(f"[*] Creating {Colors.green(display_name)} at {Colors.green(target_path)}")
            process = subprocess.run(
                command, capture_output=True, text=True, check=False
            )
        if process.returncode != 0:
            shutil.rmtree(target_path, ignore_errors=True)
            detail = process.stderr.strip() or process.stdout.strip()
            raise PloadError(f"failed to create {display_name}: {detail}")

        if console.is_terminal:
            console.print(Text.assemble(
                ("✓ ", "bold green"),
                ("Created ", "white"),
                (display_name, "bold"),
            ))
        else:
            print(f"[*] Created {Colors.green(display_name)}")
        entry = self.register_environment(
            target_path,
            name=display_name,
            description=description or "",
        )
        if console.is_terminal:
            console.print(Text.assemble(
                ("✓ ", "bold green"),
                ("Assigned ", "white"),
                (entry["id"], "bold cyan"),
            ))
        else:
            print(f"[*] Assigned {Colors.cyan(entry['id'])}")
        return target_path

    @property
    def registry_path(self):
        return self.config.state_path / "environments.json"

    def _read_registry(self):
        path = self.registry_path
        if not path.is_file():
            return {"version": 1, "next_id": 1, "environments": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PloadError(f"cannot read environment registry {path}: {exc}") from exc
        if not isinstance(data, dict) or not isinstance(data.get("environments"), list):
            raise PloadError(f"invalid environment registry: {path}")
        data.setdefault("version", 1)
        data.setdefault("next_id", 1)
        return data

    def _write_registry(self, data):
        self.config.state_path.mkdir(parents=True, exist_ok=True)
        path = self.registry_path
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    @staticmethod
    def _valid_environment(path):
        path = Path(path)
        return not path.is_symlink() and path.is_dir() and (path / "pyvenv.cfg").is_file()

    @staticmethod
    def _id_number(environment_id):
        value = str(environment_id)
        return int(value[1:]) if value.startswith("v") and value[1:].isdigit() else 0

    def register_environment(self, path, name=None, description=None):
        resolved = Path(path).expanduser().resolve()
        data = self._read_registry()
        for entry in data["environments"]:
            if Path(entry.get("path", "")).expanduser().resolve() == resolved:
                changed = False
                if name and entry.get("name") != name:
                    entry["name"] = name
                    changed = True
                if description is not None and entry.get("description") != description:
                    entry["description"] = description
                    changed = True
                if changed:
                    self._write_registry(data)
                return entry

        used = {
            self._id_number(item.get("id"))
            for item in data["environments"]
            if self._id_number(item.get("id")) > 0
        }
        next_id = 1
        while next_id in used:
            next_id += 1
        entry = {
            "id": f"v{next_id}",
            "name": name or resolved.name,
            "path": str(resolved),
            "description": description or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        data["environments"].append(entry)
        # Keep this legacy field useful for older readers, while allocation above
        # always scans for the first available ID so deleted IDs are reusable.
        data["next_id"] = max(used | {next_id}) + 1
        self._write_registry(data)
        return entry

    def environments(self):
        """Return registered environments and import legacy managed environments."""
        data = self._read_registry()
        registered_paths = {
            str(Path(entry.get("path", "")).expanduser().resolve())
            for entry in data["environments"]
            if entry.get("path")
        }
        root = self.config.venv_path
        if root.is_dir():
            for child in sorted(root.iterdir(), key=lambda item: item.name.lower()):
                resolved = str(child.resolve())
                if self._valid_environment(child) and resolved not in registered_paths:
                    self.register_environment(child, name=child.name)
                    registered_paths.add(resolved)

        data = self._read_registry()
        result = []
        for entry in data["environments"]:
            path = Path(entry.get("path", "")).expanduser()
            if self._valid_environment(path):
                item = dict(entry)
                item["python"] = self.environment_python_version(path)
                result.append(item)
        def created_key(item):
            stamp = item.get("created_at") or ""
            try:
                return datetime.fromisoformat(stamp).timestamp()
            except (TypeError, ValueError, OverflowError):
                return 0

        # Newest environments are easiest to find at the top. ID order is only
        # a deterministic tie-breaker for old registries without timestamps.
        return sorted(
            result,
            key=lambda item: (created_key(item), self._id_number(item.get("id"))),
            reverse=True,
        )

    @staticmethod
    def environment_python_version(path):
        config = Path(path) / "pyvenv.cfg"
        try:
            values = {}
            for line in config.read_text(encoding="utf-8").splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    values[key.strip().lower()] = value.strip()
            return values.get("version") or values.get("version_info") or "unknown"
        except OSError:
            return "unknown"

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
            by_id = next(
                (entry for entry in self.environments() if entry.get("id") == venv_name),
                None,
            )
            if by_id:
                path = Path(by_id["path"])
            else:
                path = None
            candidate = Path(venv_name).expanduser()
            has_separator = "/" in venv_name or "\\" in venv_name
            if path is not None:
                pass
            elif candidate.is_absolute() or has_separator:
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
        data = self._read_registry()
        data["environments"] = [
            entry for entry in data["environments"]
            if Path(entry.get("path", "")).expanduser().resolve() != target_path
        ]
        self._write_registry(data)
        print(f"[*] Removed {Colors.green(target_path)}")

    def activation_script(self, venv_name, shell=None, project_dir=None):
        path = self.resolve_existing(venv_name, project_dir=project_dir)
        script = self.config.activate_path(path, shell=shell)
        if not script.is_file():
            raise PloadError(f"activation script not found: {script}")
        return script
