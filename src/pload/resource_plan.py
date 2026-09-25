"""Persistent, auditable acquisition plans produced without acquiring packages."""

import hashlib
import json
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.8
    import tomli as tomllib

from pload.errors import PloadError


def plan_path(configuration_path):
    return Path(configuration_path).parent / ".pload_plan.toml"


def file_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _quoted(value):
    return json.dumps(str(value), ensure_ascii=False)


def dump_plan(configuration_path, configuration_sha256, lock_sha256, plan):
    python = plan["python"]
    lines = [
        "schema = 1",
        f"configuration = {_quoted(Path(configuration_path).name)}",
        f"configuration_sha256 = {_quoted(configuration_sha256)}",
        f"lock_sha256 = {_quoted(lock_sha256)}",
        f"name = {_quoted(plan['name'])}",
        f"ready = {'true' if plan['ready'] else 'false'}",
        "",
        "[python]",
        f"method = {_quoted(python['method'])}",
        f"location = {_quoted(python['location'])}",
        f"status = {_quoted(python['status'])}",
    ]
    for package in plan.get("packages", []):
        selected = package.get("selected") or {}
        rejection = (package.get("rejections") or [{}])[0]
        reason = rejection.get("reason", "no resource satisfies the configuration")
        lines += [
            "",
            "[[package]]",
            f"name = {_quoted(package['name'])}",
            f"version = {_quoted(package['version'])}",
            f"method = {_quoted(selected.get('method', 'unavailable'))}",
            f"location = {_quoted(selected.get('location', ''))}",
            f"status = {_quoted(selected.get('status', 'unavailable'))}",
            f"estimated_seconds = {float(selected.get('estimated_seconds', 0.0))}",
        ]
        if not selected:
            lines.append(f"reason = {_quoted(reason)}")
        if selected.get("fingerprint"):
            lines.append(f"fingerprint = {_quoted(selected['fingerprint'])}")
        artifact = selected.get("artifact")
        if artifact:
            lines += [
                "",
                "[package.artifact]",
                f"filename = {_quoted(artifact['filename'])}",
                f"sha256 = {_quoted(artifact['sha256'])}",
            ]
            if artifact.get("url"):
                lines.append(f"url = {_quoted(artifact['url'])}")
            if artifact.get("size") is not None:
                lines.append(f"size = {int(artifact['size'])}")
            if artifact.get("metadata_sha256"):
                lines.append(
                    f"metadata_sha256 = {_quoted(artifact['metadata_sha256'])}"
                )
    return "\n".join(lines) + "\n"


def write_plan(configuration_path, configuration_sha256, lock_sha256, plan):
    destination = plan_path(configuration_path)
    temporary = destination.with_name(destination.name + ".tmp")
    temporary.write_text(
        dump_plan(configuration_path, configuration_sha256, lock_sha256, plan),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination


def load_plan(configuration_path, configuration_sha256, lock_sha256):
    path = plan_path(configuration_path)
    try:
        with path.open("rb") as stream:
            data = tomllib.load(stream)
    except FileNotFoundError as exc:
        raise PloadError(
            f"acquisition plan is missing; run 'pload plan {Path(configuration_path).name}'"
        ) from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise PloadError(f"cannot read acquisition plan {path}: {exc}") from exc
    if data.get("schema") != 1:
        raise PloadError("unsupported acquisition plan schema")
    if (
        data.get("configuration") != Path(configuration_path).name
        or data.get("configuration_sha256") != configuration_sha256
        or data.get("lock_sha256") != lock_sha256
    ):
        raise PloadError("acquisition plan is stale; run pload plan again")
    packages = data.get("package", [])
    if not isinstance(packages, list):
        raise PloadError("invalid acquisition plan packages")
    return path, data
