"""Resolve exact wheel graphs using index metadata, never distribution bodies."""

import hashlib
import json
import platform
import sys
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import compat32
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import InvalidWheelFilename, canonicalize_name, parse_wheel_filename
from packaging.version import InvalidVersion, Version
from resolvelib import BaseReporter, Resolver
from resolvelib.resolvers import ResolutionImpossible

from pload.errors import PloadError

MAX_INDEX_BYTES = 16 * 1024 * 1024
MAX_METADATA_BYTES = 8 * 1024 * 1024


def _read_url(url, accept, maximum):
    request = Request(url, headers={"Accept": accept, "User-Agent": "pload-metadata/1"})
    try:
        with urlopen(request, timeout=30) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > maximum:
                raise PloadError(f"metadata response is too large: {url}")
            content = response.read(maximum + 1)
            if len(content) > maximum:
                raise PloadError(f"metadata response is too large: {url}")
            return content, response.headers.get_content_type()
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise PloadError(f"cannot read package metadata from {url}: {exc}") from exc


class _SimpleHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.files = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        values = dict(attrs)
        href = values.get("href")
        if not href:
            return
        metadata = values.get("data-core-metadata")
        if metadata is None:
            metadata = values.get("data-dist-info-metadata")
        self.files.append({
            "url": href,
            "filename": unquote(urlsplit(href).path.rsplit("/", 1)[-1]),
            "hashes": _fragment_hashes(urlsplit(href).fragment),
            "requires-python": values.get("data-requires-python"),
            "core-metadata": _metadata_hashes(metadata),
            "yanked": "data-yanked" in values,
            "size": None,
        })


def _fragment_hashes(fragment):
    if "=" not in fragment:
        return {}
    algorithm, value = fragment.split("=", 1)
    return {algorithm.lower(): value}


def _metadata_hashes(value):
    if value is None or value is False:
        return None
    if value is True or str(value).lower() == "true":
        return {}
    if isinstance(value, dict):
        return value
    return _fragment_hashes(str(value))


@dataclass(frozen=True)
class MetadataCandidate:
    name: str
    version: Version
    source: str
    artifact_url: str
    filename: str
    sha256: str
    size: int
    metadata_sha256: str


class MetadataIndex:
    def __init__(self, sources, supported_tags, python_version, fetch=None):
        self.sources = sources
        self.supported_tags = set(supported_tags)
        self.python_version = Version(python_version)
        self.fetch = fetch or _read_url
        self.project_cache = {}
        self.dependency_cache = {}

    def candidates(self, name):
        key = canonicalize_name(name)
        if key in self.project_cache:
            return self.project_cache[key]
        by_version = {}
        metadata_missing = []
        source_errors = []
        for source_name, base_url in self.sources:
            project_url = base_url.rstrip("/") + "/" + key + "/"
            try:
                body, content_type = self.fetch(
                    project_url,
                    "application/vnd.pypi.simple.v1+json, text/html;q=0.2",
                    MAX_INDEX_BYTES,
                )
            except PloadError as exc:
                source_errors.append(f"{source_name}: {exc}")
                continue
            if content_type == "application/vnd.pypi.simple.v1+json" or body.lstrip().startswith(b"{"):
                try:
                    files = json.loads(body.decode("utf-8"))["files"]
                except (KeyError, TypeError, ValueError, UnicodeDecodeError) as exc:
                    raise PloadError(f"invalid Simple API response for {name}") from exc
            else:
                parser = _SimpleHTML()
                try:
                    parser.feed(body.decode("utf-8"))
                except UnicodeDecodeError as exc:
                    raise PloadError(f"invalid Simple API HTML response for {name}") from exc
                files = parser.files
            for record in files:
                filename = record.get("filename", "")
                try:
                    project, version, _, tags = parse_wheel_filename(filename)
                except (InvalidWheelFilename, InvalidVersion):
                    continue
                if canonicalize_name(project) != key or not tags.intersection(self.supported_tags):
                    continue
                if record.get("yanked"):
                    continue
                requires_python = record.get("requires-python")
                if requires_python:
                    try:
                        if not SpecifierSet(requires_python).contains(self.python_version):
                            continue
                    except InvalidSpecifier:
                        continue
                sha256 = (record.get("hashes") or {}).get("sha256")
                raw_metadata = record.get("core-metadata")
                if raw_metadata is None:
                    raw_metadata = record.get("dist-info-metadata")
                metadata_hashes = _metadata_hashes(raw_metadata)
                if not sha256:
                    continue
                if metadata_hashes is None:
                    metadata_missing.append(filename)
                    continue
                url = urljoin(project_url, record["url"])
                candidate = MetadataCandidate(
                    name=key, version=version, source=source_name,
                    artifact_url=url.split("#", 1)[0], filename=filename,
                    sha256=sha256, size=int(record.get("size") or 0),
                    metadata_sha256=metadata_hashes.get("sha256", ""),
                )
                current = by_version.get(version)
                if current is None or (candidate.size or sys.maxsize) < (current.size or sys.maxsize):
                    by_version[version] = candidate
        if not by_version and metadata_missing:
            raise PloadError(
                f"index has compatible files for {name}, but does not expose independent "
                "core metadata; refusing to download a wheel during plan. Add a "
                "metadata-capable source such as https://pypi.org/simple"
            )
        if not by_version and source_errors:
            raise PloadError(
                f"no configured index could provide metadata for {name}: "
                + "; ".join(source_errors)
            )
        result = sorted(by_version.values(), key=lambda item: item.version, reverse=True)
        self.project_cache[key] = result
        return result

    def dependencies(self, candidate, marker_environment):
        if candidate in self.dependency_cache:
            return self.dependency_cache[candidate]
        url = candidate.artifact_url + ".metadata"
        body, _ = self.fetch(url, "application/octet-stream", MAX_METADATA_BYTES)
        if candidate.metadata_sha256:
            actual = hashlib.sha256(body).hexdigest()
            if actual != candidate.metadata_sha256:
                raise PloadError(f"core metadata checksum mismatch for {candidate.filename}")
        message = BytesParser(policy=compat32).parsebytes(body)
        if canonicalize_name(message.get("Name", "")) != candidate.name:
            raise PloadError(f"core metadata name mismatch for {candidate.filename}")
        if message.get("Version") != str(candidate.version):
            raise PloadError(f"core metadata version mismatch for {candidate.filename}")
        requirements = []
        for value in message.get_all("Requires-Dist", []):
            try:
                requirement = Requirement(value)
            except InvalidRequirement as exc:
                raise PloadError(f"invalid Requires-Dist in {candidate.filename}: {value}") from exc
            if requirement.url:
                raise PloadError(
                    f"{candidate.filename} uses a direct-URL dependency that cannot be planned"
                )
            if requirement.marker and not requirement.marker.evaluate(marker_environment):
                continue
            requirements.append(requirement)
        self.dependency_cache[candidate] = requirements
        return requirements


class _Provider:
    def __init__(self, index, marker_environment):
        self.index = index
        self.marker_environment = marker_environment

    def identify(self, requirement_or_candidate):
        return canonicalize_name(requirement_or_candidate.name)

    def get_preference(self, identifier, resolutions, candidates, information, backtrack_causes):
        return (identifier not in resolutions, identifier)

    def find_matches(self, identifier, requirements, incompatibilities):
        constraints = list(requirements[identifier])
        rejected = set(incompatibilities[identifier])
        return [
            candidate for candidate in self.index.candidates(identifier)
            if candidate not in rejected
            and all(requirement.specifier.contains(candidate.version) for requirement in constraints)
        ]

    @staticmethod
    def is_satisfied_by(requirement, candidate):
        return requirement.specifier.contains(candidate.version)

    def get_dependencies(self, candidate):
        return self.index.dependencies(candidate, self.marker_environment)


def resolve_metadata(requirements, sources, environment, supported_tags, fetch=None):
    """Return exact packages and wheel metadata without fetching any wheel body."""
    parsed = [Requirement(value) for value in requirements]
    marker_environment = default_environment()
    python = environment["python"]
    marker_environment.update({
        "python_full_version": python,
        "python_version": ".".join(python.split(".")[:2]),
        "implementation_name": environment.get("implementation", "cpython"),
        "platform_system": environment.get("system") or platform.system(),
        "platform_machine": environment.get("machine") or platform.machine(),
        "extra": "",
    })
    index = MetadataIndex(sources, supported_tags, python, fetch=fetch)
    try:
        result = Resolver(_Provider(index, marker_environment), BaseReporter()).resolve(parsed)
    except ResolutionImpossible as exc:
        raise PloadError("dependency constraints cannot be resolved from index metadata") from exc
    packages = []
    for name, candidate in sorted(result.mapping.items()):
        packages.append({
            "name": name, "version": str(candidate.version),
            "sources": [candidate.source],
            "artifact": [{
                "filename": candidate.filename, "sha256": candidate.sha256,
                "tags": [str(tag) for tag in parse_wheel_filename(candidate.filename)[3]],
                "repositories": [], "url": candidate.artifact_url,
                "size": candidate.size,
                "metadata_sha256": candidate.metadata_sha256,
            }],
        })
    return packages
