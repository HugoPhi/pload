from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import ClassVar

from pload.errors import PloadError


@dataclass(frozen=True)
class PythonRuntime:
    version: str
    source: str
    path: Path
    implementation: str = "Python"
    id: str | None = None
    alias: str | None = None

    @property
    def display_id(self):
        if self.id and self.alias:
            return f"{self.id}:{self.alias}"
        return self.id or self.alias or "-"


class PythonManager:
    SOURCES = ("sys", "pyenv", "uv", "conda", "mise", "asdf", "homebrew", "other")
    SOURCE_ALIASES: ClassVar = {"managed": "uv", "system": "sys"}
    SOURCE_PRIORITY: ClassVar = {
        "uv": 0,
        "pyenv": 1,
        "conda": 2,
        "mise": 3,
        "asdf": 4,
        "homebrew": 5,
        "sys": 6,
        "other": 7,
    }
    _PYTHON_NAME = re.compile(
        r"(?:python(?:3(?:\.\d+)?)?|pypy3?)(?:\.exe)?$", re.IGNORECASE
    )

    def __init__(self, config):
        self.config = config

    def install_python(self, version):
        uv = self.config.uv_executable()
        if not uv:
            raise PloadError(
                "uv is required for managed Python downloads. Run pload-install "
                "to create the private runtime, or install uv separately."
            )
        install_dir = Path(self.config.python["install_dir"]).expanduser()
        bin_dir = Path(self.config.python["bin_dir"]).expanduser()
        cache_dir = Path(self.config.python["cache_dir"]).expanduser()
        install_dir.mkdir(parents=True, exist_ok=True)
        bin_dir.mkdir(parents=True, exist_ok=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(uv), "python", "install", version,
            "--install-dir", str(install_dir),
        ]
        mirror = self.config.python.get("mirror")
        if mirror:
            command += ["--mirror", mirror]
        print(f"[*] Installing managed Python {version} into {install_dir}")
        result = subprocess.run(
            command, env=self.config.uv_environment(), check=False
        )
        if result.returncode != 0:
            raise PloadError(f"failed to install Python {version} with uv")
        python = self.config.find_managed_python(version)
        if not python:
            raise PloadError(
                f"uv completed but Python {version} was not found under {install_dir}"
            )
        print(f"[*] Installed Python {version}: {python}")
        return python

    @classmethod
    def parse_sources(cls, values):
        if not values:
            return None
        requested = set()
        for value in values:
            for item in value.split(","):
                item = item.strip().lower()
                item = cls.SOURCE_ALIASES.get(item, item)
                if item:
                    requested.add(item)
        unknown = requested.difference(cls.SOURCES)
        if unknown:
            choices = ", ".join(cls.SOURCES)
            raise PloadError(
                f"unknown Python source(s): {', '.join(sorted(unknown))}; "
                f"choose from {choices}"
            )
        return requested

    def discover(self, sources=None):
        selected = self.parse_sources(sources)
        discovered = {}
        for declared_source, path in self._candidate_paths(selected):
            path = Path(path).expanduser()
            if not path.is_file() or not self._is_python_name(path.name):
                continue
            source = self._classify_path(path, declared_source)
            if selected is not None and source not in selected:
                continue
            key = self._path_key(path)
            if key in discovered:
                continue
            runtime = self._probe(path, source)
            if runtime:
                discovered[key] = runtime
        runtimes = sorted(
            discovered.values(),
            key=lambda item: (
                self._version_key(item.version),
                self.SOURCE_PRIORITY.get(item.source, 99),
                str(item.path),
            ),
        )
        return self._assign_ids(runtimes)

    @property
    def registry_path(self):
        return self.config.state_path / "python-runtimes.json"

    def _assign_ids(self, runtimes):
        """Persist a stable pyN ID for every currently discovered executable."""
        path = self.registry_path
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise PloadError(f"cannot read Python registry {path}: {exc}") from exc
        else:
            data = {"version": 1, "runtimes": []}
        if not isinstance(data, dict) or not isinstance(data.get("runtimes"), list):
            raise PloadError(f"invalid Python registry: {path}")

        saved_records = [item for item in data["runtimes"] if item.get("path")]
        saved = {
            self._path_key(item.get("path", "")): item
            for item in saved_records
        }
        used = {
            int(item["id"][2:])
            for item in saved.values()
            if re.fullmatch(r"py\d+", str(item.get("id", "")))
        }
        assigned = []
        changed = False
        for runtime in runtimes:
            key = self._path_key(runtime.path)
            item = saved.get(key)
            if item:
                runtime_id = item["id"]
            else:
                number = 1
                while number in used:
                    number += 1
                runtime_id = f"py{number}"
                used.add(number)
                changed = True
            alias = f"{runtime.source}-v{runtime.version}"
            if not item or item.get("alias") != alias or item.get("source") != runtime.source:
                changed = True
            assigned.append(replace(runtime, id=runtime_id, alias=alias))

        current_records = [
            {
                "id": runtime.id,
                "alias": runtime.alias,
                "source": runtime.source,
                "version": runtime.version,
                "path": str(runtime.path),
            }
            for runtime in assigned
        ]
        records_by_path = {self._path_key(item["path"]): item for item in saved_records}
        records_by_path.update({self._path_key(item["path"]): item for item in current_records})
        records = list(records_by_path.values())
        if changed or records != data["runtimes"]:
            self.config.state_path.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"version": 1, "runtimes": records}, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return assigned

    def find_python(self, version):
        requested = str(version)
        runtimes = self.discover()
        for runtime in runtimes:
            if requested in {runtime.id, runtime.alias, runtime.display_id}:
                return runtime.path
        for prefix in ("cpython@", "cpython-"):
            if requested.startswith(prefix):
                requested = requested[len(prefix):]
        matches = [
            runtime for runtime in runtimes
            if runtime.version == requested or runtime.version.startswith(requested + ".")
        ]
        if not matches:
            return None
        return max(
            matches,
            key=lambda item: (
                self._version_key(item.version),
                -self.SOURCE_PRIORITY.get(item.source, 99),
            ),
        ).path

    def get_installed_versions(self, sources=None):
        return self.format_runtimes(self.discover(sources))

    @staticmethod
    def format_runtimes(runtimes):
        if not runtimes:
            return []
        id_width = max([10] + [len(item.display_id) for item in runtimes])
        version_width = max([7] + [len(item.version) for item in runtimes])
        source_width = max([4] + [len(item.source) for item in runtimes])
        lines = [
            f"{'ID / ALIAS':<{id_width}}  {'VERSION':<{version_width}}  {'TYPE':<{source_width}}  PATH",
            f"{'-' * id_width}  {'-' * version_width}  {'-' * source_width}  {'-' * 4}",
        ]
        lines.extend(
            f"{item.display_id:<{id_width}}  {item.version:<{version_width}}  {item.source:<{source_width}}  {item.path}"
            for item in runtimes
        )
        return lines

    def _candidate_paths(self, selected=None):
        def wants(source):
            return selected is None or source in selected

        candidates = []
        if wants("uv"):
            candidates.extend(("uv", path) for path in self.config.managed_python_candidates())
            for root in self._uv_roots():
                candidates.extend(("uv", path) for path in self._python_files(root, recursive=True))
        if wants("pyenv"):
            candidates.extend(
                self._version_manager_candidates("pyenv", self.config.pyenv_versions)
            )
        if wants("conda"):
            candidates.extend(self._conda_candidates())
        if wants("mise"):
            mise_data = Path(os.environ.get(
                "MISE_DATA_DIR", Path.home() / ".local" / "share" / "mise"
            ))
            candidates.extend(
                self._version_manager_candidates("mise", mise_data / "installs" / "python")
            )
        if wants("asdf"):
            asdf_data = Path(os.environ.get("ASDF_DATA_DIR", Path.home() / ".asdf"))
            candidates.extend(
                self._version_manager_candidates("asdf", asdf_data / "installs" / "python")
            )
        if wants("homebrew"):
            candidates.extend(self._homebrew_candidates())
        if wants("sys"):
            candidates.extend(self._system_candidates())
            candidates.extend(self._windows_launcher_candidates())
        if wants("other"):
            candidates.extend(self._path_candidates())
        return candidates

    def _uv_roots(self):
        roots = [Path(self.config.python["install_dir"]).expanduser()]
        environment_root = os.environ.get("UV_PYTHON_INSTALL_DIR")
        if environment_root:
            roots.append(Path(environment_root).expanduser())
        uv = self.config.uv_executable()
        if uv:
            env = os.environ.copy()
            env.pop("UV_PYTHON_INSTALL_DIR", None)
            try:
                result = subprocess.run(
                    [str(uv), "python", "dir"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                    env=env,
                )
            except (OSError, subprocess.TimeoutExpired):
                result = None
            if result and result.returncode == 0 and result.stdout.strip():
                roots.append(Path(result.stdout.strip()).expanduser())
        return self._unique_paths(roots)

    def _version_manager_candidates(self, source, root):
        root = Path(root).expanduser()
        if not root.is_dir():
            return []
        candidates = []
        for version_dir in root.iterdir():
            if version_dir.is_dir():
                python = self.config._python_in(version_dir)
                if python.is_file():
                    candidates.append((source, python))
        return candidates

    def _conda_candidates(self):
        prefixes = []
        for variable in ("CONDA_PREFIX", "MAMBA_ROOT_PREFIX"):
            value = os.environ.get(variable)
            if value:
                prefixes.append(Path(value))
        for variable in ("CONDA_ENVS_PATH", "MAMBA_ENVS_PATH"):
            for root in os.environ.get(variable, "").split(os.pathsep):
                if root:
                    path = Path(root).expanduser()
                    if path.is_dir():
                        prefixes.extend(item for item in path.iterdir() if item.is_dir())
        default_roots = [
            Path.home() / name
            for name in ("miniconda3", "anaconda3", "miniforge3", "mambaforge")
        ]
        prefixes.extend(default_roots)
        env_roots = [Path.home() / ".conda" / "envs"]
        env_roots.extend(root / "envs" for root in default_roots)
        mamba_root = os.environ.get("MAMBA_ROOT_PREFIX")
        if mamba_root:
            env_roots.append(Path(mamba_root).expanduser() / "envs")
        for root in env_roots:
            if root.is_dir():
                prefixes.extend(item for item in root.iterdir() if item.is_dir())
        conda = shutil.which("conda") or shutil.which("mamba")
        if conda:
            try:
                result = subprocess.run(
                    [conda, "env", "list", "--json"],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                if result.returncode == 0:
                    prefixes.extend(Path(item) for item in json.loads(result.stdout).get("envs", []))
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        return [
            ("conda", python)
            for prefix in self._unique_paths(prefixes)
            for python in [self.config._python_in(prefix)]
            if python.is_file()
        ]

    def _homebrew_candidates(self):
        if sys.platform == "win32":
            return []
        candidates = []
        for root in (Path("/opt/homebrew/opt"), Path("/usr/local/opt")):
            if not root.is_dir():
                continue
            for prefix in root.glob("python*"):
                candidates.extend(("homebrew", path) for path in self._python_files(prefix / "bin"))
        return candidates

    def _system_candidates(self):
        candidates = []
        base_executable = getattr(sys, "_base_executable", None)
        if base_executable:
            candidates.append(("sys", Path(base_executable)))
        if sys.platform == "win32":
            roots = []
            for variable in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
                value = os.environ.get(variable)
                if value:
                    roots.append(Path(value))
            for root in roots:
                for prefix in root.glob("Programs/Python/Python*"):
                    candidates.extend(("sys", path) for path in self._python_files(prefix))
                for prefix in root.glob("Python*"):
                    candidates.extend(("sys", path) for path in self._python_files(prefix))
        else:
            for root in (Path("/usr/bin"), Path("/usr/local/bin")):
                candidates.extend(("sys", path) for path in self._python_files(root))
            framework = Path("/Library/Frameworks/Python.framework/Versions")
            if framework.is_dir():
                for prefix in framework.iterdir():
                    candidates.extend(("sys", path) for path in self._python_files(prefix / "bin"))
        return candidates

    def _windows_launcher_candidates(self):
        if sys.platform != "win32":
            return []
        launcher = shutil.which("py")
        if not launcher:
            return []
        try:
            result = subprocess.run(
                [launcher, "-0p"], capture_output=True, text=True, check=False, timeout=5
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        candidates = []
        for line in result.stdout.splitlines():
            match = re.search(r"([A-Za-z]:\\.*?python(?:\.exe)?)\s*$", line, re.IGNORECASE)
            if match:
                candidates.append(("sys", Path(match.group(1))))
        return candidates

    def _path_candidates(self):
        candidates = []
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            if entry:
                candidates.extend(("other", path) for path in self._python_files(Path(entry)))
        return candidates

    def _python_files(self, root, recursive=False):
        root = Path(root).expanduser()
        if not root.is_dir():
            return []
        try:
            paths = root.rglob("python*") if recursive else root.iterdir()
            return [path for path in paths if path.is_file() and self._is_python_name(path.name)]
        except OSError:
            return []

    def _classify_path(self, path, declared):
        resolved = str(path.resolve()).replace("\\", "/").lower()
        configured_uv = str(Path(self.config.python["install_dir"]).expanduser()).replace(
            "\\", "/"
        ).lower()
        patterns = (
            ("uv", (configured_uv, "/.local/share/uv/python/", "/uv/python/")),
            ("pyenv", ("/.pyenv/versions/",)),
            ("conda", ("/anaconda", "/miniconda", "/miniforge", "/mambaforge", "/conda/envs/")),
            ("mise", ("/.local/share/mise/installs/python/",)),
            ("asdf", ("/.asdf/installs/python/",)),
            ("homebrew", ("/homebrew/", "/cellar/python", "/usr/local/opt/python")),
        )
        for source, markers in patterns:
            if any(marker and marker in resolved for marker in markers):
                return source
        if resolved.startswith(("/usr/bin/", "/usr/local/bin/")):
            return "sys"
        return declared if declared in self.SOURCES else "other"

    def _probe(self, path, source):
        code = (
            "import json,platform;"
            "print(json.dumps({'version':platform.python_version(),"
            "'implementation':platform.python_implementation()}))"
        )
        try:
            result = subprocess.run(
                [str(path), "-I", "-S", "-c", code],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
            if result.returncode != 0:
                return None
            data = json.loads(result.stdout.strip())
            version = str(data["version"])
            if not version.startswith("3."):
                return None
            return PythonRuntime(version, source, path.resolve(), data["implementation"])
        except (KeyError, OSError, ValueError, subprocess.TimeoutExpired):
            return None

    @classmethod
    def _is_python_name(cls, name):
        return bool(cls._PYTHON_NAME.fullmatch(name))

    @staticmethod
    def _path_key(path):
        return os.path.normcase(str(Path(path).expanduser().resolve()))

    @staticmethod
    def _version_key(version):
        return tuple(int(item) for item in re.findall(r"\d+", version))

    @staticmethod
    def _unique_paths(paths):
        unique = []
        seen = set()
        for path in paths:
            key = os.path.normcase(str(Path(path).expanduser().resolve()))
            if key not in seen:
                seen.add(key)
                unique.append(Path(path).expanduser())
        return unique
