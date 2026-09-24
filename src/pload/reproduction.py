"""Build deterministic, explainable package restoration plans."""

import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def normalized_name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def parse_package_source(value):
    name, separator, url = value.partition("=")
    if not separator or not name.strip() or not url.strip():
        raise ValueError("package source must be PACKAGE=URL")
    kind = "index"
    for prefix in ("index:", "source:"):
        if url.startswith(prefix):
            kind = prefix[:-1]
            url = url[len(prefix):]
            break
    return normalized_name(name.strip()), {"kind": kind, "url": safe_source(url.strip())}


def safe_source(url):
    parsed = urlsplit(url)
    return urlunsplit((
        parsed.scheme, parsed.netloc.rsplit("@", 1)[-1], parsed.path, "", parsed.fragment,
    ))


def file_digest(path):
    checksum = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def wheel_identity(filename):
    """Return normalized distribution/version from a valid-looking wheel name."""
    parts = Path(filename).name[:-4].split("-") if str(filename).endswith(".whl") else []
    if len(parts) < 5:
        return None, None
    return normalized_name(parts[0]), parts[1]


def candidate(method, location, score, availability, reason, artifact=None):
    result = {
        "method": method,
        "location": str(location),
        "score": score,
        "availability": availability,
        "reason": reason,
    }
    if artifact:
        result["artifact"] = artifact
    return result


class ReproductionPlanner:
    """Rank reproducibility before bandwidth, installation cost and convenience.

    Scores are deliberately spaced so a more reproducible exact artifact always
    wins over an online resolution. They rank known options; pip remains the final
    compatibility check for wheel tags and build requirements.
    """

    def __init__(self, snapshot_path, data, cache=None, links=None):
        self.path = Path(snapshot_path)
        self.data = data
        self.cache = Path(cache) if cache else None
        self.links = [Path(item) for item in links or []]

    def plan(self, offline=False, portable=False, index=None, sources=None):
        overrides = {}
        try:
            for item in sources or []:
                name, source = parse_package_source(item)
                overrides.setdefault(name, []).append(source)
        except ValueError as exc:
            raise ValueError(f"invalid reproduction source: {exc}") from exc
        plans = []
        for package in self.data.get("packages", []):
            options = self._candidates(package, portable, index, overrides)
            if offline:
                options = [item for item in options if item["availability"] == "ready"]
            options.sort(key=lambda item: (-item["score"], item["method"], item["location"]))
            plans.append({
                "name": package["name"],
                "version": package["version"],
                "selected": options[0] if options else None,
                "alternatives": options[1:],
            })
        return plans

    def _candidates(self, package, portable, index, overrides):
        options = []
        artifacts = package.get("artifacts", [])
        for artifact in artifacts:
            filename = artifact.get("file", "")
            universal = filename.endswith("-none-any.whl")
            if portable and not universal:
                continue
            bundled = self.path / filename
            if bundled.is_file():
                options.append(candidate(
                    "snapshot-wheel", bundled, 100, "ready",
                    "checksum-pinned artifact stored with the snapshot", artifact,
                ))
            for method, directory, score in self._artifact_directories():
                cached = directory / Path(filename).name
                if cached.is_file() and file_digest(cached) == artifact.get("sha256"):
                    options.append(candidate(
                        method, cached, score, "ready",
                        "local exact wheel avoids a network download", artifact,
                    ))
        # Even an unbundled package may already exist in a wheel directory.
        expected_name = normalized_name(package["name"])
        expected_version = package["version"]
        if not artifacts:
            for method, directory, score in self._artifact_directories():
                if not directory.is_dir():
                    continue
                for wheel in directory.glob("*.whl"):
                    name, version = wheel_identity(wheel.name)
                    if name == expected_name and version == expected_version:
                        if portable and not wheel.name.endswith("-none-any.whl"):
                            continue
                        options.append(candidate(
                            method, wheel, score - 5, "ready",
                            "matching local wheel; hash will be recorded before installation",
                        ))
        package_sources = overrides.get(expected_name, [])
        recorded_sources = [item for item in package.get("sources", []) if item]
        online = []
        for package_source in package_sources:
            if package_source["kind"] == "source":
                options.append(candidate(
                    "source-repository", package_source["url"], 38, "build",
                    "explicit upstream source; requires a reproducible build toolchain",
                ))
            else:
                online.append(("package-index", package_source["url"], 75,
                               "explicit package-specific index"))
        if index:
            online.append(("requested-index", index, 68, "index selected for this plan"))
        for source in recorded_sources:
            source = source if isinstance(source, dict) else {"kind": "index", "url": source}
            if source.get("kind") == "source":
                options.append(candidate(
                    "source-repository", source["url"], 35, "build",
                    "upstream source recorded when the snapshot was created",
                ))
            else:
                online.append(("recorded-index", source["url"], 65,
                               "index recorded when the snapshot was created"))
        if not online:
            options.append(candidate(
                "pip-default-index", "pip configuration / default index", 55, "network",
                "fallback to pip's configured index when no index provenance was recorded",
            ))
            options.append(candidate(
                "pip-default-source-build", "pip configuration / default index", 20, "build",
                "last-resort source build using pip's configured index",
            ))
        for method, location, score, reason in online:
            options.append(candidate(method, location, score, "network", reason))
            options.append(candidate(
                "source-build", location, score - 35, "build",
                "fallback when no compatible wheel exists; requires compiler/build dependencies",
            ))
        # Remove repeated candidates while preserving the highest score.
        unique = {}
        for item in options:
            key = (item["method"], item["location"])
            if key not in unique or unique[key]["score"] < item["score"]:
                unique[key] = item
        return list(unique.values())

    def _artifact_directories(self):
        result = []
        if self.cache:
            result.append(("shared-cache", self.cache, 92))
        result.extend(("find-links", item, 85) for item in self.links)
        return result


def summarize_plan(plans):
    counts = {"ready": 0, "network": 0, "build": 0, "unavailable": 0}
    for item in plans:
        selected = item["selected"]
        counts[selected["availability"] if selected else "unavailable"] += 1
    return counts
