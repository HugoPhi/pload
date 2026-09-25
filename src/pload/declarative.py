"""Declarative environment manifests and resource-driven materialization."""

import hashlib
import json
import os
import platform
import re
import shlex
import shutil
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import compatible_tags, cpython_tags, platform_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the Python 3.8 CI job
    import tomli as tomllib

from pload.errors import PloadError
from pload.managers.platform import PythonNotFoundError
from pload.managers.pyversion import PythonManager
from pload.managers.venv import VenvManager
from pload.snapshots import RepositoryManager, digest, execute, probe, public_index, safe_name

PIN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+!-]*)")
WHEEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+!-]*\.whl")
SHA256 = re.compile(r"[0-9a-f]{64}")


def normalized_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def _parse_dependency(value):
    if not isinstance(value, str) or not value.strip():
        raise PloadError("environment.dependencies must contain package requirements")
    try:
        requirement = Requirement(value)
    except InvalidRequirement as exc:
        raise PloadError(f"invalid dependency requirement: {value}") from exc
    if requirement.url:
        raise PloadError("direct-URL dependencies are not portable; declare an index source")
    if requirement.marker:
        raise PloadError("dependency environment markers are not supported in schema 1")
    return requirement


def _normalized_machine(value):
    aliases = {
        "amd64": "x86_64", "x64": "x86_64",
        "aarch64": "arm64", "arm64": "arm64",
    }
    normalized = str(value).lower()
    return aliases.get(normalized, normalized)


def _target_wheel_tags(environment):
    """Return wheel tags installable on the requested runtime on this host."""
    if (environment.get("system")
            and environment["system"].lower() != platform.system().lower()):
        return set()
    if (environment.get("machine")
            and _normalized_machine(environment["machine"])
            != _normalized_machine(platform.machine())):
        return set()
    try:
        version = tuple(int(part) for part in environment["python"].split(".")[:2])
    except (KeyError, TypeError, ValueError):
        return set()
    if len(version) != 2:
        return set()
    platforms = list(platform_tags())
    implementation = environment.get("implementation", "cpython").lower()
    interpreter = f"cp{version[0]}{version[1]}" if implementation == "cpython" else None
    result = set(compatible_tags(
        python_version=version, interpreter=interpreter, platforms=platforms,
    ))
    if implementation == "cpython":
        result.update(cpython_tags(python_version=version, platforms=platforms))
    return result


def _artifact_is_compatible(artifact, supported_tags):
    try:
        wheel_tags = parse_wheel_filename(artifact["filename"])[3]
    except (InvalidWheelFilename, KeyError, TypeError):
        return False
    return bool(wheel_tags.intersection(supported_tags))


def manifest_digest(data):
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _quoted(value):
    return json.dumps(str(value), ensure_ascii=False)


def _array(values):
    return "[" + ", ".join(_quoted(item) for item in values) + "]"


def dump_manifest(data):
    """Serialize only the user-authored environment declaration."""
    environment = data["environment"]
    policy = data["policy"]
    lines = [
        f"schema = {data['schema']}",
        f"name = {_quoted(data['name'])}",
        "",
        "[environment]",
        f"python = {_quoted(environment['python'])}",
        f"implementation = {_quoted(environment.get('implementation', 'cpython'))}",
        f"system = {_quoted(environment.get('system', ''))}",
        f"machine = {_quoted(environment.get('machine', ''))}",
        f"dependencies = {_array(environment.get('dependencies', []))}",
        "",
        "[policy]",
        f"reproducibility = {_quoted(policy.get('reproducibility', 'exact'))}",
        f"network = {_quoted(policy.get('network', 'allow'))}",
        f"source_build = {_quoted(policy.get('source_build', 'fallback'))}",
        "publish_missing_artifacts = " +
        ("true" if policy.get("publish_missing_artifacts", True) else "false"),
    ]
    repositories = policy.get("repositories", [])
    if repositories:
        lines.append(f"repositories = {_array(repositories)}")
    capabilities = data.get("capabilities", {})
    if capabilities:
        lines += ["", "[capabilities]"]
        for key, value in sorted(capabilities.items()):
            lines.append(f"{key} = {_array(value)}")
    for name, source in sorted(data.get("sources", {}).items()):
        lines += [
            "",
            f"[sources.{_quoted(name)}]",
            f"kind = {_quoted(source['kind'])}",
            f"url = {_quoted(source['url'])}",
        ]
    for name, repository in sorted(data.get("repositories", {}).items()):
        lines += [
            "",
            f"[repositories.{_quoted(name)}]",
            f"kind = {_quoted(repository['kind'])}",
            f"location = {_quoted(repository['location'])}",
        ]
    return "\n".join(lines) + "\n"


def lock_path(manifest_path):
    """Return the pload-managed lock beside a user configuration."""
    return Path(manifest_path).parent / ".pload_lock.toml"


def configuration_digest(data):
    return hashlib.sha256(dump_manifest(data).encode("utf-8")).hexdigest()


def dump_lock(manifest_path, data):
    """Serialize resolver output separately from the user configuration."""
    lines = [
        "schema = 1",
        f"configuration = {_quoted(Path(manifest_path).name)}",
        f"configuration_sha256 = {_quoted(configuration_digest(data))}",
        "",
        "[environment]",
        f"dependencies = {_array(data.get('resolved_dependencies', []))}",
    ]
    for package in data.get("package", []):
        lines += [
            "",
            "[[package]]",
            f"name = {_quoted(package['name'])}",
            f"version = {_quoted(package['version'])}",
        ]
        if package.get("sources"):
            lines.append(f"sources = {_array(package['sources'])}")
        for artifact in package.get("artifact", []):
            lines += [
                "",
                "[[package.artifact]]",
                f"filename = {_quoted(artifact['filename'])}",
                f"sha256 = {_quoted(artifact['sha256'])}",
                f"tags = {_array(artifact.get('tags', []))}",
                f"repositories = {_array(artifact.get('repositories', []))}",
            ]
    return "\n".join(lines) + "\n"


def load_lock(manifest_path, configuration):
    """Load a current sidecar lock; stale locks are ignored and regenerated."""
    path = lock_path(manifest_path)
    if not path.is_file():
        return path, None, False
    try:
        with path.open("rb") as stream:
            lock = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PloadError(f"cannot read environment lock {path}: {exc}") from exc
    if lock.get("schema") != 1:
        raise PloadError(f"unsupported environment lock schema in {path}")
    packages = lock.setdefault("package", [])
    environment = lock.setdefault("environment", {})
    environment.setdefault("dependencies", [])
    for package in packages:
        package.setdefault("sources", [])
        package.setdefault("artifact", [])
    current = (
        lock.get("configuration") == Path(manifest_path).name
        and lock.get("configuration_sha256") == configuration_digest(configuration)
    )
    if current:
        combined = dict(configuration)
        combined["package"] = packages
        validate_manifest(combined)
    return path, lock, current


def load_manifest(path):
    path = Path(path).expanduser().resolve()
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PloadError(f"cannot read environment configuration {path}: {exc}") from exc
    data.setdefault("sources", {})
    data.setdefault("repositories", {})
    data.setdefault("capabilities", {})
    data.setdefault("package", [])
    environment = data.setdefault("environment", {})
    environment.setdefault("implementation", "cpython")
    environment.setdefault("system", "")
    environment.setdefault("machine", "")
    environment.setdefault("dependencies", [])
    policy = data.get("policy")
    if isinstance(policy, dict):
        policy.setdefault("reproducibility", "exact")
        policy.setdefault("network", "allow")
        policy.setdefault("source_build", "fallback")
        policy.setdefault("publish_missing_artifacts", True)
        policy.setdefault("repositories", [])
    for package in data["package"]:
        package.setdefault("sources", [])
        package.setdefault("artifact", [])
    validate_manifest(data)
    return path, data


def validate_manifest(data):
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise PloadError("unsupported environment configuration schema")
    safe_name(data.get("name"))
    environment = data.get("environment")
    policy = data.get("policy")
    if not isinstance(environment, dict) or not environment.get("python"):
        raise PloadError("environment.python is required")
    if not isinstance(policy, dict):
        raise PloadError("a [policy] section is required")
    if policy.get("reproducibility", "exact") not in {"exact", "compatible"}:
        raise PloadError("policy.reproducibility must be exact or compatible")
    if policy.get("network", "allow") not in {"allow", "offline"}:
        raise PloadError("policy.network must be allow or offline")
    if policy.get("source_build", "fallback") not in {"fallback", "forbid"}:
        raise PloadError("policy.source_build must be fallback or forbid")
    if not isinstance(policy.get("publish_missing_artifacts", True), bool):
        raise PloadError("policy.publish_missing_artifacts must be true or false")
    policy_repositories = policy.get("repositories", [])
    if (not isinstance(policy_repositories, list)
            or any(not isinstance(name, str) for name in policy_repositories)):
        raise PloadError("policy.repositories must be an array of repository names")
    dependencies = environment.get("dependencies", [])
    if not isinstance(dependencies, list):
        raise PloadError("environment.dependencies must be an array of package requirements")
    requirements = [_parse_dependency(item) for item in dependencies]
    dependency_names = [normalized_name(item.name) for item in requirements]
    if len(dependency_names) != len(set(dependency_names)):
        raise PloadError("environment.dependencies contains duplicate package requirements")
    seen = set()
    for name, source in data.get("sources", {}).items():
        safe_name(name)
        if source.get("kind") != "index" or not source.get("url"):
            raise PloadError(f"source {name} must be a Python package index")
        parsed = urlsplit(source["url"])
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise PloadError(f"source {name} must use an HTTP(S) URL")
        if public_index(source["url"]) != source["url"]:
            raise PloadError(f"source {name} must not contain credentials or query parameters")
    capabilities = data.get("capabilities", {})
    if not isinstance(capabilities, dict) or any(
        not isinstance(values, list) or any(not isinstance(value, str) for value in values)
        for values in capabilities.values()
    ):
        raise PloadError("capabilities must contain arrays of strings")
    for package in data.get("package", []):
        if not isinstance(package, dict):
            raise PloadError("invalid package lock entry")
        pin = f"{package.get('name', '')}=={package.get('version', '')}"
        if not PIN.fullmatch(pin):
            raise PloadError(f"invalid locked package: {pin}")
        key = normalized_name(package["name"])
        if key in seen:
            raise PloadError(f"duplicate locked package: {package['name']}")
        seen.add(key)
        for source_name in package.get("sources", []):
            if source_name not in data.get("sources", {}):
                raise PloadError(
                    f"locked package {package['name']} references unknown source {source_name}"
                )
        for artifact in package.get("artifact", []):
            if (not WHEEL.fullmatch(artifact.get("filename", ""))
                    or not SHA256.fullmatch(artifact.get("sha256", ""))):
                raise PloadError(f"invalid artifact for {package['name']}")
            for repository_name in artifact.get("repositories", []):
                if repository_name not in data.get("repositories", {}):
                    raise PloadError(
                        f"artifact {artifact['filename']} references unknown repository "
                        f"{repository_name}"
                    )
    # A dependency edit can intentionally make the existing package lock stale.
    # Planning reconciles and rewrites it; validation only checks each section's
    # shape and internal safety.
    for name, repository in data.get("repositories", {}).items():
        safe_name(name)
        kind = repository.get("kind")
        location = repository.get("location")
        if kind == "ssh":
            RepositoryManager.ssh_location(location)
        elif kind == "local":
            if not location:
                raise PloadError(f"repository {name} has no location")
        else:
            raise PloadError(f"repository {name} must be local or ssh")
    unknown_policy_repositories = set(policy_repositories).difference(
        data.get("repositories", {})
    )
    if unknown_policy_repositories:
        raise PloadError(
            "policy.repositories references unknown repositories: "
            + ", ".join(sorted(unknown_policy_repositories))
        )
    return data


def _wheel_tags(filename):
    parts = filename[:-4].rsplit("-", 3)
    return ["-".join(parts[-3:])] if len(parts) == 4 else []


def _wheel_identity(filename):
    parts = Path(filename).name[:-4].split("-") if str(filename).endswith(".whl") else []
    if len(parts) < 5:
        return None, None
    return normalized_name(parts[0]), parts[1]


class ArtifactRepository:
    """Content-addressed local and SSH artifact access."""

    SSH_OPTIONS = (
        "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=4",
    )

    @staticmethod
    def _local_root(spec, base):
        root = Path(spec["location"]).expanduser()
        if not root.is_absolute():
            root = base / root
        return root.resolve()

    @classmethod
    def contains(cls, spec, checksum, base):
        return checksum in cls.contains_many(spec, [checksum], base)

    @classmethod
    def contains_many(cls, spec, checksums, base):
        checksums = sorted(set(checksums))
        if spec["kind"] == "local":
            root = cls._local_root(spec, base) / "objects"
            return {
                checksum for checksum in checksums
                if (root / checksum).is_file() and digest(root / checksum) == checksum
            }
        host, root = RepositoryManager.ssh_location(spec["location"])
        object_root = root + "/objects"
        checks = "; ".join(
            f"test -f {shlex.quote(object_root + '/' + checksum)} && printf '%s\\n' "
            f"{shlex.quote(checksum)} || true"
            for checksum in checksums
        )
        return set(execute(
            ["ssh", *cls.SSH_OPTIONS, host, checks], timeout=75,
        ).splitlines())

    @classmethod
    def publish(cls, spec, source, checksum, base):
        cls.publish_many(spec, [(source, checksum)], base)

    @classmethod
    def publish_many(cls, spec, artifacts, base):
        """Publish multiple objects with one SSH query and one transfer."""
        artifacts = [(Path(source), checksum) for source, checksum in artifacts]
        if not artifacts:
            return
        for source, checksum in artifacts:
            if digest(source) != checksum:
                raise PloadError("artifact changed before publication")
        if spec["kind"] == "local":
            for source, checksum in artifacts:
                target = cls._local_root(spec, base) / "objects" / checksum
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists() and digest(target) != checksum:
                    raise PloadError("repository object checksum mismatch")
                if not target.exists():
                    temporary = target.with_name(target.name + "." + uuid.uuid4().hex)
                    shutil.copyfile(source, temporary)
                    temporary.replace(target)
            return
        host, root = RepositoryManager.ssh_location(spec["location"])
        checksums = sorted({checksum for _, checksum in artifacts})
        object_root = root + "/objects"
        checks = "; ".join(
            f"test -f {shlex.quote(object_root + '/' + checksum)} && printf '%s\\n' "
            f"{shlex.quote(checksum)} || true"
            for checksum in checksums
        )
        existing = set(execute(
            ["ssh", *cls.SSH_OPTIONS, host,
             f"mkdir -p {shlex.quote(object_root)}; {checks}"],
            timeout=75,
        ).splitlines())
        missing = [(source, checksum) for source, checksum in artifacts
                   if checksum not in existing]
        if missing:
            pending_name = ".upload-" + uuid.uuid4().hex
            remote_pending = root + "/" + pending_name
            with tempfile.TemporaryDirectory(prefix="pload-publish-") as temporary:
                stage = Path(temporary)
                for source, checksum in missing:
                    staged = stage / checksum
                    try:
                        os.link(source, staged)
                    except OSError:
                        shutil.copyfile(source, staged)
                execute(
                    ["ssh", *cls.SSH_OPTIONS, host,
                     f"mkdir -p {shlex.quote(remote_pending)}"],
                    timeout=75,
                )
                execute(
                    ["scp", "-q", *cls.SSH_OPTIONS,
                     *[str(stage / checksum) for _, checksum in missing],
                     host + ":" + remote_pending + "/"],
                    timeout=300,
                )
            commands = []
            for _, checksum in missing:
                pending = remote_pending + "/" + checksum
                target = object_root + "/" + checksum
                commands.append(
                    f"test \"$(sha256sum {shlex.quote(pending)} | cut -d' ' -f1)\" = "
                    f"{shlex.quote(checksum)}"
                )
                commands.append(f"mv -n {shlex.quote(pending)} {shlex.quote(target)}")
                commands.append(f"rm -f {shlex.quote(pending)}")
            commands.append(f"rmdir {shlex.quote(remote_pending)}")
            execute(
                ["ssh", *cls.SSH_OPTIONS, host, " && ".join(commands)],
                timeout=75,
            )
        verify = " && ".join(
            f"test \"$(sha256sum {shlex.quote(object_root + '/' + checksum)} "
            f"| cut -d' ' -f1)\" = {shlex.quote(checksum)}"
            for checksum in checksums
        )
        execute(["ssh", *cls.SSH_OPTIONS, host, verify], timeout=75)

    @classmethod
    def fetch(cls, spec, checksum, destination, base):
        cls.fetch_many(spec, [(checksum, destination)], base)

    @classmethod
    def fetch_many(cls, spec, artifacts, base):
        """Fetch multiple content-addressed objects through one SFTP session."""
        artifacts = [(checksum, Path(destination)) for checksum, destination in artifacts]
        if not artifacts:
            return
        for _, destination in artifacts:
            destination.parent.mkdir(parents=True, exist_ok=True)
        if spec["kind"] == "local":
            root = cls._local_root(spec, base) / "objects"
            for checksum, destination in artifacts:
                temporary = destination.with_name(
                    destination.name + "." + uuid.uuid4().hex
                )
                shutil.copyfile(root / checksum, temporary)
                if digest(temporary) != checksum:
                    temporary.unlink(missing_ok=True)
                    raise PloadError("retrieved artifact checksum mismatch")
                temporary.replace(destination)
            return
        host, root = RepositoryManager.ssh_location(spec["location"])
        with tempfile.TemporaryDirectory(prefix="pload-fetch-") as temporary:
            stage = Path(temporary)
            commands = []
            for checksum, _ in artifacts:
                commands.append(
                    f"get {root}/objects/{checksum} {stage / checksum}"
                )
            execute(
                ["sftp", "-q", "-b", "-", *cls.SSH_OPTIONS, host],
                timeout=300, input_text="\n".join(commands) + "\n",
            )
            for checksum, destination in artifacts:
                downloaded = stage / checksum
                if not downloaded.is_file() or digest(downloaded) != checksum:
                    raise PloadError("retrieved artifact checksum mismatch")
                temporary_destination = destination.with_name(
                    destination.name + "." + uuid.uuid4().hex
                )
                shutil.copyfile(downloaded, temporary_destination)
                temporary_destination.replace(destination)

class DeclarativeEnvironmentManager:
    def __init__(self, config):
        self.config = config
        self.cache = config.home / "cache" / "wheels"

    def describe(
        self, source, output, name=None, mode="exact", repository=None, sources=None,
        progress=None,
    ):
        venvs = VenvManager(self.config)
        candidate = Path(source).expanduser()
        if candidate.is_file():
            interpreter = candidate.resolve()
            inferred_name = interpreter.parent.parent.name or "environment"
        else:
            environment = venvs.resolve_existing(source)
            interpreter = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            inferred_name = environment.name
        runtime = probe(interpreter)
        if runtime.get("conda"):
            raise PloadError("native Conda environments require a future Conda provider")
        packages = sorted(runtime.pop("packages"), key=lambda item: item["name"].lower())
        accelerators = runtime.pop("accelerators", [])
        pins = [f"{item['name']}=={item['version']}" for item in packages]
        if any(not PIN.fullmatch(pin) for pin in pins):
            raise PloadError("the environment contains package metadata that cannot be locked")
        output = Path(output).expanduser().resolve()
        repositories = {
            key: {"kind": value["kind"], "location": value["location"]}
            for key, value in self.config.settings.get("repositories", {}).items()
            if value.get("kind") in {"local", "ssh"}
        }
        selected_repository = repository
        if selected_repository and selected_repository not in repositories:
            raise PloadError(f"unknown artifact repository: {selected_repository}")
        if not selected_repository and repositories:
            selected_repository = min(repositories)
        index = public_index(self.config.settings.get("pip_index") or "https://pypi.org/simple")
        parsed_index = urlsplit(index)
        if parsed_index.scheme not in {"http", "https"} or not parsed_index.netloc:
            raise PloadError("configured package index must use an HTTP(S) URL")
        source_overrides = {}
        declared_sources = {"default": {"kind": "index", "url": index}}
        installed_names = {normalized_name(item["name"]) for item in packages}
        for assignment in sources or []:
            package_name, separator, url = assignment.partition("=")
            package_name = normalized_name(package_name.strip())
            url = public_index(url.strip())
            if not separator or not package_name or not url:
                raise PloadError("package sources must use PACKAGE=INDEX_URL")
            parsed_source = urlsplit(url)
            if parsed_source.scheme not in {"http", "https"} or not parsed_source.netloc:
                raise PloadError("package source must use an HTTP(S) URL")
            if package_name not in installed_names:
                raise PloadError(f"package source does not match an installed package: {package_name}")
            source_name = "package-" + package_name
            source_overrides[package_name] = (source_name, url)
            declared_sources[source_name] = {"kind": "index", "url": url}
        data = {
            "schema": 1,
            "name": name or inferred_name,
            "environment": {
                "python": runtime.get("python"),
                "implementation": runtime.get("implementation", "cpython"),
                "system": runtime.get("system", ""),
                "machine": runtime.get("machine", ""),
                "dependencies": pins,
            },
            "policy": {
                "reproducibility": mode,
                "network": "allow",
                "source_build": "fallback",
                "publish_missing_artifacts": True,
                "repositories": [selected_repository] if selected_repository else [],
            },
            "sources": declared_sources,
            "repositories": repositories,
            "capabilities": {
                "nvidia_driver": sorted({
                    version for item in accelerators if item.get("kind") == "nvidia"
                    for version in item.get("driver_versions", [])
                }),
            },
            "package": [],
        }
        self.cache.mkdir(parents=True, exist_ok=True)
        publication = []
        with tempfile.TemporaryDirectory(prefix="pload-describe-") as temporary:
            wheel_dir = Path(temporary)
            for index_number, installed in enumerate(packages, 1):
                if progress:
                    progress(
                        f"[{index_number}/{len(packages)}] Locking "
                        f"{installed['name']}=={installed['version']}"
                    )
                source_name, package_index = source_overrides.get(
                    normalized_name(installed["name"]), ("default", index)
                )
                record = {
                    "name": installed["name"], "version": installed["version"],
                    "sources": [source_name], "artifact": [],
                }
                if mode == "exact":
                    wheel = self._obtain_wheel(
                        interpreter, installed, wheel_dir, package_index
                    )
                    checksum = digest(wheel)
                    cached = self.cache / wheel.name
                    if cached.exists() and digest(cached) != checksum:
                        raise PloadError(f"conflicting cached artifact: {wheel.name}")
                    if not cached.exists():
                        shutil.copyfile(wheel, cached)
                    locations = []
                    if selected_repository:
                        publication.append((cached, checksum))
                    artifact = {
                        "filename": wheel.name, "sha256": checksum,
                        "tags": _wheel_tags(wheel.name), "repositories": locations,
                    }
                    record["artifact"].append(artifact)
                data["package"].append(record)
        if selected_repository and publication:
            if progress:
                progress(
                    f"Publishing {len(publication)} locked artifacts to "
                    f"{selected_repository}"
                )
            ArtifactRepository.publish_many(
                repositories[selected_repository], publication, output.parent,
            )
            for package in data["package"]:
                for artifact in package.get("artifact", []):
                    artifact["repositories"].append(selected_repository)
        validate_manifest(data)
        output.parent.mkdir(parents=True, exist_ok=True)
        self._write_manifest(output, data)
        data["resolved_dependencies"] = pins
        self._write_lock(output, data)
        return output

    def _obtain_wheel(self, interpreter, installed, wheel_dir, index):
        expected_name = normalized_name(installed["name"])
        expected_version = installed["version"]
        direct_checksum = None
        if installed.get("direct_url"):
            try:
                provenance = json.loads(installed["direct_url"])
                archive = provenance.get("archive_info", {})
                direct_checksum = archive.get("hashes", {}).get("sha256")
                if not direct_checksum and archive.get("hash", "").startswith("sha256="):
                    direct_checksum = archive["hash"].split("=", 1)[1]
            except (TypeError, ValueError):
                pass
        for wheel in self.cache.glob("*.whl"):
            if (_wheel_identity(wheel.name) == (expected_name, expected_version)
                    and (not direct_checksum or digest(wheel) == direct_checksum)):
                return wheel
        if installed.get("direct_url"):
            raise PloadError(
                f"cannot lock direct installation {installed['name']}=={installed['version']}; "
                "place its original SHA-matching wheel in the pload cache"
            )
        command = [
            str(interpreter), "-m", "pip", "download", "--only-binary=:all:",
            "--no-deps", "--dest", str(wheel_dir), "--index-url", index,
            f"{installed['name']}=={installed['version']}",
        ]
        try:
            execute(command)
        except PloadError as exc:
            raise PloadError(
                f"cannot lock an exact wheel for {installed['name']}=={installed['version']}; "
                "use --mode compatible only if re-resolution is acceptable"
            ) from exc
        matches = [
            wheel for wheel in wheel_dir.glob("*.whl")
            if _wheel_identity(wheel.name) == (expected_name, expected_version)
        ]
        if len(matches) != 1:
            raise PloadError(f"download did not produce one exact wheel for {installed['name']}")
        return matches[0]

    def _load_state(self, manifest_path):
        path, data = load_manifest(manifest_path)
        legacy_packages = list(data.get("package", []))
        _, lock, current = load_lock(path, data)
        if current:
            data["package"] = lock.get("package", [])
            data["resolved_dependencies"] = lock["environment"].get("dependencies", [])
        elif legacy_packages:
            # Versions before 1.1.0a8 embedded resolver output in pload.toml.
            # Keep it long enough to migrate it into the sidecar without a download.
            data["package"] = legacy_packages
            data["resolved_dependencies"] = [
                f"{item['name']}=={item['version']}" for item in legacy_packages
            ]
        else:
            data["package"] = []
            data["resolved_dependencies"] = []
        return path, data, current, bool(legacy_packages)

    def _lock_requested_dependencies(
        self, path, data, lock_current=False, legacy=False, offline=False,
        progress=None,
    ):
        requested = list(data["environment"].get("dependencies", []))
        if not requested:
            return None
        requirements = [_parse_dependency(value) for value in requested]
        locked = {
            normalized_name(package["name"]): package["version"]
            for package in data.get("package", [])
        }
        satisfies_requests = all(
            normalized_name(requirement.name) in locked
            and (not requirement.specifier or requirement.specifier.contains(
                locked[normalized_name(requirement.name)]
            ))
            for requirement in requirements
        )
        if data.get("package") and satisfies_requests and (lock_current or legacy):
            resolved = [
                f"{package['name']}=={package['version']}"
                for package in sorted(
                    data["package"], key=lambda item: normalized_name(item["name"])
                )
            ]
            data["resolved_dependencies"] = resolved
            if legacy:
                self._write_manifest(path, data)
                self._write_lock(path, data)
                return {
                    "updated": True, "migrated": True,
                    "path": str(lock_path(path)),
                    "requested": requested, "resolved": resolved,
                }
            return None

        network_allowed = (
            data["policy"].get("network", "allow") == "allow" and not offline
        )
        if not network_allowed:
            raise PloadError(
                "unlocked dependencies require one online resolution before offline planning"
            )
        try:
            interpreter = self.config.get_python_path(data["environment"]["python"])
        except PythonNotFoundError:
            PythonManager(self.config).install_python(data["environment"]["python"])
            interpreter = self.config.get_python_path(data["environment"]["python"])
        self._check_runtime(interpreter, data["environment"])

        sources = data.get("sources", {})
        if not sources:
            index = public_index(
                self.config.settings.get("pip_index") or "https://pypi.org/simple"
            )
            data["sources"] = {"default": {"kind": "index", "url": index}}
            sources = data["sources"]
        source_names = sorted(sources, key=lambda name: (name != "default", name))
        primary = sources[source_names[0]]["url"]

        self.cache.mkdir(parents=True, exist_ok=True)
        known_repositories = {
            (artifact["filename"], artifact["sha256"]): artifact.get("repositories", [])
            for package in data.get("package", [])
            for artifact in package.get("artifact", [])
        }
        with tempfile.TemporaryDirectory(prefix="pload-lock-") as temporary:
            destination = Path(temporary)
            command = [
                str(interpreter), "-m", "pip", "download",
                "--disable-pip-version-check", "--only-binary=:all:",
                "--dest", str(destination), "--find-links", str(self.cache),
                "--index-url", primary,
            ]
            for source_name in source_names[1:]:
                command += ["--extra-index-url", sources[source_name]["url"]]
            try:
                if progress:
                    progress(
                        "Configuration changed; resolving dependencies for Python "
                        f"{data['environment']['python']}"
                    )
                execute(command + requested)
            except PloadError as exc:
                raise PloadError(
                    "cannot resolve unlocked dependencies to compatible wheels for "
                    f"Python {data['environment']['python']}"
                ) from exc

            wheels = sorted(destination.glob("*.whl"), key=lambda item: item.name.lower())
            if not wheels:
                raise PloadError("dependency resolution did not produce any wheels")
            records = []
            for wheel in wheels:
                try:
                    package_name, package_version, _, wheel_tags = parse_wheel_filename(
                        wheel.name
                    )
                except InvalidWheelFilename as exc:
                    raise PloadError(f"resolver produced an invalid wheel: {wheel.name}") from exc
                checksum = digest(wheel)
                cached = self.cache / wheel.name
                if cached.is_file() and digest(cached) != checksum:
                    raise PloadError(f"conflicting cached artifact: {wheel.name}")
                if not cached.exists():
                    shutil.copyfile(wheel, cached)
                records.append({
                    "name": str(package_name),
                    "version": str(package_version),
                    "sources": source_names,
                    "artifact": [{
                        "filename": wheel.name,
                        "sha256": checksum,
                        "tags": sorted(str(tag) for tag in wheel_tags),
                        "repositories": known_repositories.get(
                            (wheel.name, checksum), []
                        ),
                    }],
                })

        locked = {normalized_name(item["name"]): item["version"] for item in records}
        for value in requested:
            requirement = _parse_dependency(value)
            version = locked.get(normalized_name(requirement.name))
            if version is None or (requirement.specifier
                                   and not requirement.specifier.contains(version)):
                raise PloadError(f"resolver did not satisfy dependency requirement: {value}")
        records.sort(key=lambda item: normalized_name(item["name"]))
        resolved = [f"{item['name']}=={item['version']}" for item in records]
        data["package"] = records
        data["resolved_dependencies"] = resolved
        validate_manifest(data)
        self._write_lock(path, data)
        return {
            "updated": True, "path": str(lock_path(path)),
            "requested": requested, "resolved": resolved,
        }

    @staticmethod
    def _write_manifest(path, data):
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(dump_manifest(data), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _write_lock(path, data):
        destination = lock_path(path)
        temporary = destination.with_name(destination.name + ".tmp")
        temporary.write_text(dump_lock(path, data), encoding="utf-8")
        temporary.replace(destination)

    def plan(self, manifest_path, offline=False, progress=None):
        path, data, current, legacy = self._load_state(manifest_path)
        lock = self._lock_requested_dependencies(
            path, data, lock_current=current, legacy=legacy, offline=offline,
            progress=progress,
        )
        policy = data["policy"]
        network_allowed = policy.get("network", "allow") == "allow" and not offline
        repositories = data.get("repositories", {})
        packages = self._locked_packages(data)
        preferred_repositories = policy.get("repositories", [])
        supported_tags = _target_wheel_tags(data["environment"])
        try:
            python = str(self.config.get_python_path(data["environment"]["python"]))
            python_action = {"method": "reuse-python", "location": python, "status": "ready"}
        except PythonNotFoundError:
            python_action = {
                "method": "install-python", "location": data["environment"]["python"],
                "status": "network" if network_allowed else "unavailable",
            }
        repository_checksums = {}
        for package in packages:
            for artifact in package.get("artifact", []):
                if not _artifact_is_compatible(artifact, supported_tags):
                    continue
                repo_names = dict.fromkeys(
                    artifact.get("repositories", []) + preferred_repositories
                )
                for repo_name in repo_names:
                    if repo_name in repositories:
                        repository_checksums.setdefault(repo_name, set()).add(
                            artifact["sha256"]
                        )
        repository_objects = {}
        for repo_name, checksums in repository_checksums.items():
            if progress:
                progress(f"Checking artifact repository {repo_name}")
            try:
                repository_objects[repo_name] = ArtifactRepository.contains_many(
                    repositories[repo_name], checksums, path.parent,
                )
            except PloadError:
                repository_objects[repo_name] = set()
        plans = []
        for package in packages:
            candidates = []
            rejections = []
            for artifact in package.get("artifact", []):
                if not _artifact_is_compatible(artifact, supported_tags):
                    rejections.append({
                        "artifact": artifact["filename"],
                        "reason": (
                            f"incompatible with {data['environment']['implementation']} "
                            f"{data['environment']['python']} on "
                            f"{data['environment'].get('system') or platform.system()} "
                            f"{data['environment'].get('machine') or platform.machine()}"
                        ),
                    })
                    continue
                cached = self.cache / artifact["filename"]
                adjacent = path.parent / "artifacts" / artifact["filename"]
                if cached.is_file() and digest(cached) == artifact["sha256"]:
                    candidates.append(self._candidate(
                        "cache", cached, "ready", (0, 0, 0, 0), artifact
                    ))
                if adjacent.is_file() and digest(adjacent) == artifact["sha256"]:
                    candidates.append(self._candidate(
                        "configuration-artifact", adjacent, "ready", (0, 0, 0, 1), artifact
                    ))
                repo_names = dict.fromkeys(
                    artifact.get("repositories", []) + preferred_repositories
                )
                for repo_name in repo_names:
                    spec = repositories.get(repo_name)
                    if (spec and artifact["sha256"]
                            in repository_objects.get(repo_name, set())):
                        candidates.append(self._candidate(
                            "repository", repo_name, "remote", (0, 0, 1, repo_name), artifact
                        ))
                if network_allowed:
                    for source_name in package.get("sources", []):
                        source = data.get("sources", {}).get(source_name)
                        if source and source.get("kind") == "index":
                            candidates.append(self._candidate(
                                "index-exact", source_name, "network",
                                (0, 0, 2, source_name), artifact,
                            ))
            if policy.get("reproducibility") == "compatible" and network_allowed:
                source_name = (package.get("sources") or ["default"])[0]
                candidates.append(self._candidate(
                    "index-resolve", source_name, "network", (1, 1, 2, source_name)
                ))
            candidates.sort(key=lambda item: item["cost"])
            plans.append({
                "name": package["name"], "version": package["version"],
                "selected": candidates[0] if candidates else None,
                "alternatives": candidates[1:],
                "rejections": rejections,
            })
        ready = (python_action["status"] != "unavailable"
                 and all(item["selected"] for item in plans))
        return {"path": str(path), "name": data["name"], "python": python_action,
                "packages": plans, "ready": ready, "lock": lock}

    @staticmethod
    def _candidate(method, location, status, cost, artifact=None):
        result = {"method": method, "location": str(location), "status": status,
                  "cost": list(cost)}
        if artifact:
            result["artifact"] = artifact
        return result

    @staticmethod
    def _locked_packages(data):
        if data.get("package"):
            return data["package"]
        result = []
        for pin in data["environment"].get("dependencies", []):
            match = PIN.fullmatch(pin)
            result.append({"name": match.group(1), "version": match.group(2),
                           "sources": ["default"], "artifact": []})
        return result

    def apply(self, manifest_path, name=None, offline=False, progress=None):
        path, data, _, _ = self._load_state(manifest_path)
        plan = self.plan(path, offline=offline)
        if plan.get("lock"):
            path, data, _, _ = self._load_state(path)
        unavailable = [item for item in plan["packages"] if not item["selected"]]
        if unavailable:
            details = []
            for item in unavailable:
                label = f"{item['name']}=={item['version']}"
                if item.get("rejections"):
                    label += f" ({item['rejections'][0]['reason']})"
                details.append(label)
            raise PloadError("no valid reproduction route for: " + ", ".join(details))
        if plan["python"]["method"] == "install-python":
            if plan["python"]["status"] == "unavailable":
                raise PloadError("required Python is unavailable while offline")
            PythonManager(self.config).install_python(data["environment"]["python"])
        interpreter = self.config.get_python_path(data["environment"]["python"])
        self._check_runtime(interpreter, data["environment"])
        target_name = name or data["name"]
        expected_state = manifest_digest(data)
        try:
            existing = VenvManager(self.config).resolve_existing(target_name)
        except PloadError:
            existing = None
        if existing:
            marker = existing / ".pload-manifest.sha256"
            if marker.is_file() and marker.read_text(encoding="utf-8").strip() == expected_state:
                return existing
            raise PloadError(f"environment {target_name!r} exists with different state")
        artifacts = []
        locked_files = []
        compatible = []
        self.cache.mkdir(parents=True, exist_ok=True)
        repository_fetches = {}
        for package_plan in plan["packages"]:
            selected = package_plan["selected"]
            artifact = selected.get("artifact")
            if artifact and selected["method"] == "repository":
                cached = self.cache / artifact["filename"]
                if not (cached.is_file() and digest(cached) == artifact["sha256"]):
                    repository_fetches.setdefault(selected["location"], []).append(
                        (artifact["sha256"], cached)
                    )
        for repo_name, fetches in repository_fetches.items():
            if progress:
                progress(f"Fetching {len(fetches)} artifacts from {repo_name}")
            try:
                ArtifactRepository.fetch_many(
                    data["repositories"][repo_name], fetches, path.parent,
                )
            except PloadError as exc:
                if progress:
                    progress(f"Batch fetch failed; trying fallback routes: {exc}")
        with tempfile.TemporaryDirectory(prefix="pload-apply-") as temporary:
            stage = Path(temporary)
            for index_number, package_plan in enumerate(plan["packages"], 1):
                if progress:
                    progress(
                        f"[{index_number}/{len(plan['packages'])}] Preparing "
                        f"{package_plan['name']}=={package_plan['version']}"
                    )
                selected = package_plan["selected"]
                artifact = selected.get("artifact")
                if artifact:
                    routes = [selected] + package_plan["alternatives"]
                    failures = []
                    acquired = None
                    for route in routes:
                        route_artifact = route.get("artifact")
                        if not route_artifact:
                            continue
                        cached = self.cache / route_artifact["filename"]
                        try:
                            if not (cached.is_file()
                                    and digest(cached) == route_artifact["sha256"]):
                                self._acquire(path, data, package_plan, route, cached, stage)
                            if digest(cached) != route_artifact["sha256"]:
                                raise PloadError("checksum mismatch")
                        except (OSError, PloadError) as exc:
                            failures.append(f"{route['method']}: {exc}")
                            continue
                        acquired = (cached, route_artifact)
                        break
                    if not acquired:
                        detail = failures[-1] if failures else "no artifact route"
                        raise PloadError(
                            f"cannot acquire {package_plan['name']}=={package_plan['version']}: {detail}"
                        )
                    cached, artifact = acquired
                    artifacts.append(cached.resolve().as_uri() + "#sha256=" + artifact["sha256"])
                    locked_files.append((cached, artifact["sha256"]))
                else:
                    compatible.append(package_plan)
            if (locked_files
                    and data["policy"].get("publish_missing_artifacts", True)):
                for repo_name in data["policy"].get("repositories", []):
                    if progress:
                        progress(
                            f"Publishing {len(locked_files)} locked artifacts to {repo_name}"
                        )
                    ArtifactRepository.publish_many(
                        data["repositories"][repo_name], locked_files, path.parent,
                    )
            venvs = VenvManager(self.config)
            if progress:
                progress(f"Creating environment {target_name}")
            env = venvs.create_venv(
                version=str(interpreter), name=target_name,
                description=f"Applied from {path.name}",
            )
            try:
                pip = self.config.get_pip_command(env)
                if artifacts:
                    execute(pip + ["install", "--no-index", "--no-deps"] + artifacts,
                            capture=False)
                for package_plan in compatible:
                    source_name = package_plan["selected"]["location"]
                    source = data.get("sources", {}).get(source_name, {})
                    command = pip + ["install", "--no-deps"]
                    if data["policy"].get("source_build") == "forbid":
                        command += ["--only-binary=:all:"]
                    if source.get("url"):
                        command += ["--index-url", source["url"]]
                    execute(command + [
                        f"{package_plan['name']}=={package_plan['version']}"
                    ], capture=False)
                requirements = stage / "requirements.txt"
                requirements.write_text(
                    "".join(
                        f"{item['name']}=={item['version']}\n" for item in plan["packages"]
                    ),
                    encoding="utf-8",
                )
                execute(pip + ["install", "--no-index", "--no-deps", "-r",
                               str(requirements)])
                execute(pip + ["check"], capture=False)
                if progress:
                    progress("Verified exact requirements and dependency consistency")
                (env / ".pload-manifest.sha256").write_text(
                    expected_state + "\n", encoding="utf-8"
                )
                return env
            except (OSError, PloadError):
                venvs.remove_venv(target_name)
                raise

    def _acquire(self, path, data, package, selected, destination, stage):
        artifact = selected["artifact"]
        if selected["method"] == "configuration-artifact":
            shutil.copyfile(selected["location"], destination)
        elif selected["method"] == "repository":
            ArtifactRepository.fetch(
                data["repositories"][selected["location"]], artifact["sha256"],
                destination, path.parent,
            )
        elif selected["method"] == "index-exact":
            source = data["sources"][selected["location"]]
            download = stage / normalized_name(package["name"])
            download.mkdir(exist_ok=True)
            execute([
                str(self.config.get_python_path(data["environment"]["python"])),
                "-m", "pip", "download", "--only-binary=:all:", "--no-deps",
                "--dest", str(download), "--index-url", source["url"],
                f"{package['name']}=={package['version']}",
            ])
            candidate = download / artifact["filename"]
            if not candidate.is_file():
                raise PloadError(f"index did not provide locked artifact {artifact['filename']}")
            shutil.copyfile(candidate, destination)
        else:
            raise PloadError(f"unsupported acquisition method: {selected['method']}")

    @staticmethod
    def _check_runtime(interpreter, expected):
        actual = probe(interpreter)
        if actual.get("implementation") != expected.get("implementation"):
            raise PloadError("Python implementation does not satisfy the configuration")
        if actual.get("python") != expected.get("python"):
            raise PloadError(
                f"Python version mismatch: need {expected.get('python')}, got {actual.get('python')}"
            )
        for key in ("system", "machine"):
            if expected.get(key) and actual.get(key) != expected.get(key):
                raise PloadError(
                    f"target {key} mismatch: need {expected.get(key)}, got {actual.get(key)}"
                )
