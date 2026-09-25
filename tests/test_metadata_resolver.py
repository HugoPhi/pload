import hashlib
import json

import pytest
from packaging.tags import Tag

from pload.errors import PloadError
from pload.metadata_resolver import resolve_metadata


def _project(filename, checksum, metadata_checksum, size=100):
    return json.dumps({
        "meta": {"api-version": "1.1"},
        "name": filename.split("-", 1)[0],
        "files": [{
            "filename": filename,
            "url": "https://files.invalid/" + filename,
            "hashes": {"sha256": checksum},
            "requires-python": ">=3.8",
            "core-metadata": {"sha256": metadata_checksum},
            "yanked": False,
            "size": size,
        }],
        "versions": [filename.split("-")[1]],
    }).encode()


def test_resolver_reads_only_project_pages_and_core_metadata():
    root_metadata = (
        b"Metadata-Version: 2.1\nName: root-demo\nVersion: 1.0\n"
        b"Requires-Dist: child-demo>=2\n\n"
    )
    child_metadata = b"Metadata-Version: 2.1\nName: child-demo\nVersion: 2.1\n\n"
    root_wheel = "root_demo-1.0-py3-none-any.whl"
    child_wheel = "child_demo-2.1-py3-none-any.whl"
    responses = {
        "https://index.invalid/simple/root-demo/": _project(
            root_wheel, "a" * 64, hashlib.sha256(root_metadata).hexdigest(),
        ),
        "https://index.invalid/simple/child-demo/": _project(
            child_wheel, "b" * 64, hashlib.sha256(child_metadata).hexdigest(),
        ),
        "https://files.invalid/" + root_wheel + ".metadata": root_metadata,
        "https://files.invalid/" + child_wheel + ".metadata": child_metadata,
    }
    requested = []

    def fetch(url, accept, maximum):
        requested.append(url)
        return responses[url], (
            "application/vnd.pypi.simple.v1+json"
            if url.endswith("/") else "application/octet-stream"
        )

    packages = resolve_metadata(
        ["root-demo>=1"], [("default", "https://index.invalid/simple")],
        {"python": "3.12.1", "implementation": "cpython",
         "system": "Linux", "machine": "x86_64"},
        {Tag("py3", "none", "any")}, fetch=fetch,
    )

    assert [(item["name"], item["version"]) for item in packages] == [
        ("child-demo", "2.1"), ("root-demo", "1.0"),
    ]
    assert all(url.endswith(("/", ".metadata")) for url in requested)
    assert not any(url.endswith(".whl") for url in requested)


def test_resolver_refuses_to_download_wheel_when_metadata_is_unavailable():
    wheel = "root_demo-1.0-py3-none-any.whl"
    project = json.loads(_project(wheel, "a" * 64, "b" * 64))
    project["files"][0].pop("core-metadata")
    requested = []

    def fetch(url, accept, maximum):
        requested.append(url)
        return json.dumps(project).encode(), "application/vnd.pypi.simple.v1+json"

    with pytest.raises(PloadError, match="refusing to download a wheel during plan"):
        resolve_metadata(
            ["root-demo"], [("default", "https://index.invalid/simple")],
            {"python": "3.12.1", "implementation": "cpython",
             "system": "Linux", "machine": "x86_64"},
            {Tag("py3", "none", "any")}, fetch=fetch,
        )
    assert requested == ["https://index.invalid/simple/root-demo/"]
