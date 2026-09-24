"""Portable package recipes, checked wheel bundles and optional remote storage.

Only Python's standard library and the target interpreter's pip are required
locally. SSH remotes use OpenSSH; Git remotes use the user's existing Git.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pload.errors import PloadError
from pload.managers.venv import VenvManager
from pload.settings import save_settings

PROBE = """
import json, platform, sys, os
from importlib import metadata
packages = []
for dist in metadata.distributions():
    name = dist.metadata.get('Name')
    if name and name.lower() not in ('pip', 'setuptools', 'wheel'):
        packages.append({'name': name, 'version': dist.version,
                         'direct_url': dist.read_text('direct_url.json')})
print(json.dumps({'python': platform.python_version(),
 'implementation': sys.implementation.name, 'system': platform.system(),
 'machine': platform.machine(), 'libc': list(platform.libc_ver()),
 'conda': os.path.isdir(os.path.join(sys.prefix, 'conda-meta')), 'packages': packages}))
"""


def execute(command, capture=True, cwd=None):
    try:
        result = subprocess.run(command, capture_output=capture, text=True, cwd=cwd, check=False)
    except OSError as exc:
        raise PloadError(f"cannot run {command[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "").strip() if capture else ""
        raise PloadError(f"{command[0]} failed: {detail or result.returncode}")
    return result.stdout.strip() if capture else ""


def safe_name(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,99}", value or ""):
        raise PloadError("use a name of 1–100 letters, numbers, dots, underscores or hyphens")
    return value


def digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def write_json(path, data):
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PloadError(f"cannot read {path}: {exc}") from exc


def probe(python):
    return json.loads(execute([str(python), "-c", PROBE]))


def public_index(url):
    """Store useful provenance without passwords, tokens or URL query strings."""
    if not url:
        return None
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", ""))


def validate_bundle(path):
    path = Path(path)
    if path.is_symlink() or (path / "snapshot.json").is_symlink():
        raise PloadError("snapshot must not be a symbolic link")
    data = read_json(path / "snapshot.json")
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise PloadError("unsupported snapshot schema")
    files = data.get("files")
    if not isinstance(files, dict) or "requirements.txt" not in files:
        raise PloadError("snapshot has no requirements checksum")
    if not isinstance(data.get("runtime"), dict):
        raise PloadError("snapshot has no runtime metadata")
    for name, checksum in files.items():
        if name != "requirements.txt" and not re.fullmatch(
            r"wheels/[A-Za-z0-9][A-Za-z0-9_.+!-]*\.whl", name
        ):
            raise PloadError(f"invalid snapshot file: {name}")
        item = path / name
        if any(part.is_symlink() for part in (item, item.parent)):
            raise PloadError(f"snapshot contains a symbolic link: {name}")
        if not item.is_file() or digest(item) != checksum:
            raise PloadError(f"snapshot checksum mismatch or missing file: {name}")
    # Snapshots contain only exact pins, never executable requirements directives.
    for line in (path / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+!-]*", line):
            raise PloadError(f"snapshot requires an exact package pin: {line!r}")
    return data


class SnapshotManager:
    def __init__(self, config):
        self.config = config
        self.root = config.home / "snapshots"
        self.wheels = config.home / "cache" / "wheels"

    def path(self, name):
        if name == "objects":
            raise PloadError("'objects' is reserved for repository wheel storage")
        return self.root / safe_name(name)

    def export(self, name, environment=None, python=None, bundle=None, index=None, links=None):
        target = self.path(name)
        if target.exists():
            raise PloadError(f"snapshot already exists: {name}; choose a new name")
        if python:
            candidate = Path(python).expanduser()
            # Resolving bin/python's symlink escapes a venv and probes the base Python.
            interpreter = candidate.absolute() if candidate.is_file() else self.config.get_python_path(python)
        else:
            env = VenvManager(self.config).resolve_existing(environment or ".")
            interpreter = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        runtime = probe(interpreter)
        if runtime.get("conda"):
            raise PloadError("Conda environments contain native dependencies that pip cannot reproduce; "
                             "use conda export for the full environment, or export a pip requirements "
                             "file explicitly and pass it to pload restore")
        pins = []
        exact_wheels = {}
        for package in sorted(runtime.pop("packages"), key=lambda p: p["name"].lower()):
            pin = f"{package['name']}=={package['version']}"
            if package["direct_url"]:
                provenance = json.loads(package["direct_url"])
                archive = provenance.get("archive_info", {})
                checksum = archive.get("hashes", {}).get("sha256")
                if not checksum and archive.get("hash", "").startswith("sha256="):
                    checksum = archive["hash"].split("=", 1)[1]
                normalized = re.sub(r"[-_.]+", "-", package["name"].lower())
                selected = {re.sub(r"[-_.]+", "-", item.lower())
                            for item in (bundle or "").split(",")}
                if checksum and (bundle == "all" or normalized in selected):
                    for directory in [self.wheels] + [Path(p).expanduser() for p in links or []]:
                        for wheel in directory.glob("*.whl"):
                            wheel_name = re.sub(r"[-_.]+", "-", wheel.name.split("-")[0].lower())
                            if wheel_name != normalized:
                                continue
                            if digest(wheel) == checksum:
                                exact_wheels[pin] = str(wheel.absolute())
                                break
                        if pin in exact_wheels:
                            break
                if pin not in exact_wheels:
                    raise PloadError(
                        f"{package['name']} is a direct/local install: bundle its original wheel "
                        "using --bundle and --find-links (matching installation SHA-256 required). "
                        "Editable/VCS sources must first be built and installed as wheels."
                    )
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*==[A-Za-z0-9][A-Za-z0-9_.+!-]*", pin):
                raise PloadError(f"invalid installed package metadata: {pin!r}")
            pins.append(pin)
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".export-", dir=str(self.root)) as temporary:
            stage = Path(temporary) / name
            stage.mkdir()
            requirements = stage / "requirements.txt"
            requirements.write_text("".join(pin + "\n" for pin in pins), encoding="utf-8")
            files = {"requirements.txt": digest(requirements)}
            if bundle:
                selected = {re.sub(r"[-_.]+", "-", p.lower()) for p in bundle.split(",")}
                download = pins if bundle == "all" else [
                    pin for pin in pins
                    if re.sub(r"[-_.]+", "-", pin.split("==")[0].lower()) in selected
                ]
                found = {re.sub(r"[-_.]+", "-", pin.split("==")[0].lower()) for pin in download}
                if bundle != "all" and selected - found:
                    raise PloadError("bundled packages not installed: " + ", ".join(selected - found))
                wheel_dir = stage / "wheels"
                wheel_dir.mkdir()
                self.wheels.mkdir(parents=True, exist_ok=True)
                if download:
                    download = [exact_wheels.get(pin, pin) for pin in download]
                    command = [str(interpreter), "-m", "pip", "download", "--only-binary=:all:",
                               "--no-deps", "--dest", str(wheel_dir),
                               "--find-links", str(self.wheels)]
                    for link in links or []:
                        command.extend(["--find-links", str(Path(link).expanduser().resolve())])
                    # First try without networking; fall back to pip's normal HTTP/wheel cache.
                    try:
                        execute(command + ["--no-index"] + download)
                    except PloadError:
                        if index or self.config.settings.get("pip_index"):
                            command += ["--index-url", index or self.config.settings["pip_index"]]
                        execute(command + download, capture=False)
                for wheel in sorted(wheel_dir.glob("*.whl")):
                    files["wheels/" + wheel.name] = digest(wheel)
                    cached = self.wheels / wheel.name
                    if cached.exists() and digest(cached) != digest(wheel):
                        raise PloadError(f"different wheel with same filename in cache: {wheel.name}")
                    if not cached.exists():
                        shutil.copyfile(wheel, cached)
            write_json(stage / "snapshot.json", {
                "schema": 1, "name": name, "runtime": runtime, "files": files,
                "bundle": bundle or "none",
                "index_url": public_index(index or self.config.settings.get("pip_index")),
            })
            validate_bundle(stage)
            stage.rename(target)
        return target

    def restore(self, source, name, version=None, offline=False, portable=False, index=None):
        candidate = Path(source).expanduser()
        path = candidate if candidate.exists() else self.path(source)
        is_recipe = path.is_file()
        data = None if is_recipe else validate_bundle(path)
        if offline and is_recipe:
            raise PloadError("offline mode requires a validated snapshot, not an arbitrary requirements file")
        if data:
            runtime = data["runtime"]
            version = version or ".".join(runtime.get("python", "").split(".")[:2])
        interpreter = self.config.get_python_path(version)
        if data:
            actual = probe(interpreter)
            for key in ("implementation", "system", "machine"):
                if actual.get(key) != runtime.get(key) and not portable:
                    raise PloadError(f"{key} mismatch: {runtime.get(key)} vs {actual.get(key)}; "
                                     "use --portable for a fresh platform-specific resolution")
            if actual["python"].split(".")[:2] != runtime.get("python", "").split(".")[:2]:
                raise PloadError("Python major/minor must match the snapshot")
            if portable and offline:
                raise PloadError("--portable cannot be combined with --offline")
            if offline and data.get("bundle") != "all":
                raise PloadError("offline restoration requires a snapshot exported with --bundle all")
        requirements = path if is_recipe else path / "requirements.txt"
        self.root.mkdir(parents=True, exist_ok=True)
        env = VenvManager(self.config).create_venv(version=str(interpreter), name=name)
        command = self.config.get_pip_command(env) + ["install", "-r", str(requirements.resolve())]
        if data and not portable:
            # Only checksum-verified artifacts may be used from a snapshot.
            with tempfile.TemporaryDirectory(prefix=".restore-", dir=str(self.root)) as stage:
                artifacts = []
                for filename in data["files"]:
                    if filename.startswith("wheels/"):
                        wheel = Path(stage) / Path(filename).name
                        shutil.copyfile(path / filename, wheel)
                        if digest(wheel) != data["files"][filename]:
                            raise PloadError("snapshot changed during restoration")
                        # Old pip records hashes only when supplied in the file URL.
                        artifacts.append(wheel.resolve().as_uri() + "#sha256=" +
                                         data["files"][filename])
                if artifacts:
                    # Install exact verified files first so an index cannot replace them.
                    execute(self.config.get_pip_command(env) +
                            ["install", "--no-index", "--no-deps"] + artifacts, capture=False)
                command += ["--find-links", stage]
                self._install(command, offline, index)
        else:
            self._install(command, offline, index)
        execute(self.config.get_pip_command(env) + ["check"], capture=False)
        return env

    def _install(self, command, offline, index):
        if self.wheels.is_dir():
            command += ["--find-links", str(self.wheels)]
        if offline:
            command += ["--no-index", "--no-deps"]
        elif index or self.config.settings.get("pip_index"):
            command += ["--index-url", index or self.config.settings["pip_index"]]
        try:
            if not offline:
                try:
                    execute(command + ["--no-index", "--only-binary=:all:"])
                    return
                except PloadError:
                    pass
            execute(command, capture=False)
        except PloadError as exc:
            raise PloadError(f"restore failed; the new environment is kept for inspection: {exc}")


class RepositoryManager:
    def __init__(self, config):
        self.config = config
        self.snapshots = SnapshotManager(config)

    def repositories(self):
        return self.config.settings.get("repositories", {})

    def add(self, name, location, kind):
        safe_name(name)
        repositories = dict(self.repositories())
        if name in repositories:
            raise PloadError("repository exists; remove its configuration before replacing it")
        if kind == "ssh":
            self.ssh_location(location)
        elif kind == "local":
            location = str(Path(location).expanduser().resolve())
        elif location.startswith("-") or not location:
            raise PloadError("invalid Git location")
        repositories[name] = {"kind": kind, "location": location}
        self.config.settings["repositories"] = repositories
        save_settings(self.config.home, self.config.settings)

    def remove(self, name):
        repositories = dict(self.repositories())
        if name not in repositories:
            raise PloadError(f"unknown repository: {name}")
        del repositories[name]
        self.config.settings["repositories"] = repositories
        save_settings(self.config.home, self.config.settings)

    @staticmethod
    def ssh_location(location):
        host, separator, path = location.partition(":")
        if (not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]*", host)
                or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path)
                or ".." in path.split("/") or path == "/"):
            raise PloadError("SSH location must be HOST:/absolute/directory (no spaces or '..')")
        return host, path.rstrip("/")

    def transfer(self, repo, name, push=False):
        safe_name(name)
        configured = self.repositories().get(repo)
        if not configured:
            raise PloadError(f"unknown repository: {repo}")
        target = self.snapshots.path(name)
        if not push and target.exists():
            raise PloadError("local snapshot exists; immutable snapshots are never overwritten")
        if push:
            data = validate_bundle(target)
        self.snapshots.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".transfer-", dir=str(self.snapshots.root)) as temp:
            temp = Path(temp)
            kind, location = configured["kind"], configured["location"]
            if kind == "ssh":
                host, root = self.ssh_location(location)
                remote = root + "/" + name
                if push:
                    # Publish a complete staging directory atomically; refuse overwrites.
                    stage = root + "/.upload-" + uuid.uuid4().hex
                    execute(["ssh", "-o", "BatchMode=yes", host,
                             f"mkdir -p {shlex.quote(stage + '/wheels')}"])
                    for filename in ["snapshot.json"] + list(data["files"]):
                        if filename.startswith("wheels/"):
                            obj = root + "/objects/" + data["files"][filename]
                            execute(["ssh", "-o", "BatchMode=yes", host,
                                     f"mkdir -p {shlex.quote(root + '/objects')}"])
                            exists = execute(["ssh", "-o", "BatchMode=yes", host,
                                              f"if test -f {shlex.quote(obj)}; then printf yes; fi"])
                            if exists != "yes":
                                pending = obj + "." + uuid.uuid4().hex
                                execute(["scp", "-q", "-o", "BatchMode=yes", str(target / filename),
                                         host + ":" + pending])
                                execute(["ssh", "-o", "BatchMode=yes", host,
                                         f"mv -n {shlex.quote(pending)} {shlex.quote(obj)}"])
                            remote_hash = execute(["ssh", "-o", "BatchMode=yes", host,
                                                   f"sha256sum {shlex.quote(obj)}"])
                            if remote_hash.split()[0] != data["files"][filename]:
                                raise PloadError("remote wheel checksum mismatch; snapshot not published")
                            execute(["ssh", "-o", "BatchMode=yes", host,
                                     f"ln {shlex.quote(obj)} {shlex.quote(stage + '/' + filename)}"])
                        else:
                            execute(["scp", "-q", "-o", "BatchMode=yes", str(target / filename),
                                     host + ":" + stage + "/" + filename])
                    execute(["ssh", "-o", "BatchMode=yes", host,
                             (f"test ! -e {shlex.quote(remote)} && "
                              f"mv -T {shlex.quote(stage)} {shlex.quote(remote)}")])
                else:
                    stage = temp / name
                    stage.mkdir()
                    execute(["scp", "-q", "-o", "BatchMode=yes",
                             host + ":" + remote + "/snapshot.json", str(stage / "snapshot.json")])
                    data = read_json(stage / "snapshot.json")
                    files = data.get("files", {}) if isinstance(data, dict) else {}
                    if not isinstance(files, dict):
                        raise PloadError("invalid remote file list")
                    for filename in files:
                        if filename != "requirements.txt" and not re.fullmatch(
                            r"wheels/[A-Za-z0-9][A-Za-z0-9_.+!-]*\.whl", filename
                        ):
                            raise PloadError("invalid remote filename")
                        (stage / filename).parent.mkdir(parents=True, exist_ok=True)
                        cached = self.snapshots.wheels / Path(filename).name
                        if filename.startswith("wheels/") and cached.is_file() and digest(cached) == files[filename]:
                            shutil.copyfile(cached, stage / filename)
                        else:
                            execute(["scp", "-q", "-o", "BatchMode=yes",
                                     host + ":" + remote + "/" + filename, str(stage / filename)])
                    validate_bundle(stage)
                    self.cache_bundle(stage, data)
                    stage.rename(target)
                return
            if kind == "git":
                if push and any(f.startswith("wheels/") for f in data["files"]):
                    raise PloadError("Git repositories store recipes only; use SSH/local for wheels")
                checkout = temp / "git"
                execute(["git", "clone", "--", location, str(checkout)])
                remote = checkout / "snapshots" / name
            elif kind == "local":
                remote = Path(location) / name
            else:
                raise PloadError(f"unsupported repository kind: {kind}")
            if push:
                if remote.exists():
                    raise PloadError("remote snapshot already exists; choose a new snapshot name")
                remote.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix=".publish-", dir=str(remote.parent)) as pending:
                    stage = Path(pending) / name
                    stage.mkdir()
                    for filename in ["snapshot.json"] + list(data["files"]):
                        (stage / filename).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(target / filename, stage / filename)
                    validate_bundle(stage)
                    stage.rename(remote)
                if kind == "git":
                    execute(["git", "add", "--", "snapshots/" + name], cwd=checkout)
                    execute(["git", "commit", "-m", "Add pload snapshot " + name], cwd=checkout)
                    execute(["git", "push", "origin", "HEAD"], cwd=checkout)
            else:
                data = validate_bundle(remote)
                stage = temp / name
                stage.mkdir()
                for filename in ["snapshot.json"] + list(data["files"]):
                    (stage / filename).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(remote / filename, stage / filename)
                validate_bundle(stage)
                self.cache_bundle(stage, data)
                stage.rename(target)

    def cache_bundle(self, path, data):
        self.snapshots.wheels.mkdir(parents=True, exist_ok=True)
        for filename, checksum in data["files"].items():
            if filename.startswith("wheels/"):
                cached = self.snapshots.wheels / Path(filename).name
                if cached.exists() and digest(cached) != checksum:
                    raise PloadError(f"cache filename collision: {cached.name}")
                if not cached.exists():
                    shutil.copyfile(path / filename, cached)
