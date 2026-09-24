# Reproducible environments and artifact reuse

This document describes the experimental next-version feature set on
`experiment/reproduction-planner`. The published 1.0.0 does not include these
commands yet.

## What “reproducible” means

pload separates reproducibility into three practical levels:

| Level | Stored information | Result |
| --- | --- | --- |
| Recipe | Exact package names/versions, Python version, implementation, OS, architecture and libc | Re-resolve the same versions from an index; availability may change |
| Artifact | Recipe plus SHA-256 checked wheels | Reinstall the same package files on a compatible platform, including offline |
| External context | GPU driver version and similar host facts | Explain compatibility requirements; pload records these facts but does not install drivers |

A Python environment is not universally portable. Binary wheels can depend on
the Python ABI, OS, CPU architecture, libc, GPU runtime and external system
libraries. pload therefore records the context, verifies hashes, and requires an
explicit `--portable` choice before re-resolving pins on another platform.

`pip freeze` alone is a recipe, not a lock of artifacts. pload excludes the
bootstrap packages pip, setuptools and wheel, rejects incomplete native Conda
exports, and refuses editable/VCS sources until they have been built into a wheel.

## Capture an environment

```console
pload export analysis-2026-09 -e v1
pload export analysis-offline -e v1 -b all
pload export training-cu121 -e v2 -b torch,torchvision \
  -s torch=https://download.pytorch.org/whl/cu121 \
  -s torchvision=https://download.pytorch.org/whl/cu121
```

The first command creates a recipe. The second also stores every application
wheel. The third stores expensive/special PyTorch wheels and remembers their
package-specific source. `-f DIR` can supply an already downloaded wheel; it is
repeatable. Direct/local wheel installations require the original archive and a
matching installation hash.

Each immutable snapshot contains:

```text
PLOAD_HOME/snapshots/analysis-offline/
├── requirements.txt     exact interoperable package pins
├── snapshot.json        runtime, package sources, candidates and checksums
└── wheels/              selected or complete binary artifacts
```

The snapshot records an NVIDIA driver version when `nvidia-smi` is available.
The driver itself is outside the package environment and is not copied or
installed. CUDA-related Python wheels, including large packages from slow or
special indexes, can be included in `wheels/` and uploaded to an SSH repository.

## Inspect the reproduction plan

```console
pload plan training-cu121
pload plan training-cu121 -a
pload plan training-cu121 -o
pload plan training-cu121 -p \
  -s torch=https://download.pytorch.org/whl/cu124
pload plan custom-package \
  -s custom-package=source:https://github.com/example/custom-package.git
pload plan training-cu121 -j > plan.json
```

The table shows one selected method per package. `-a` shows fallbacks; `-o`
restricts planning to ready local artifacts; `-p` plans a new platform and skips
platform-specific bundled wheels. JSON output is intended for automation.
`PACKAGE=URL` means a package index; prefix the URL with `source:` to describe
an upstream repository/archive that must be built. Repeating a package records
multiple choices rather than overwriting the earlier source.

The first experimental scoring model is deterministic:

| Priority | Method | Why |
| ---: | --- | --- |
| 100 | SHA-256 checked wheel inside the snapshot | Exact bytes, already local |
| 92 | Exact wheel in the shared pload cache | Same artifact without transfer |
| 80–85 | Matching wheel from `--find-links` | Reuse a user-supplied archive |
| 75 | Explicit package-specific index | Best online source for special builds |
| 68 | Index selected for this plan | User-selected online fallback |
| 65 | Source recorded during export | Preserves package provenance |
| 55 | pip's configured/default index | Online fallback when provenance was not recorded |
| 20–40 | Source checkout or build from an index | Last resort; compiler and build inputs may vary |

The algorithm optimizes in this order:

1. Exact artifact identity and checksum.
2. Compatibility with the requested platform mode.
3. No network transfer.
4. A package-specific source before a general index.
5. Binary installation before source compilation.

The score ranks known candidates without downloading them. An online wheel can
disappear or lack a compatible tag, and a source build can fail. pip performs the
final wheel-tag and dependency/build check. This keeps planning fast and avoids
downloading a multi-gigabyte CUDA package merely to discover whether it exists.
For a source repository, use an immutable tag or commit in the URL whenever the
source format supports one; a moving branch cannot provide byte-for-byte reproduction.

## Restore

```console
pload restore analysis-offline -n analysis-copy -o
pload restore analysis-2026-09 -n linux-copy -p
pload restore training-cu121 -n training-copy \
  -s torch=https://download.pytorch.org/whl/cu121
pload restore ./requirements.txt -n imported -v 3.12
```

Offline restore requires a snapshot made with `-b all`. Artifacts are verified
before installation. Online restore tries local wheels first, then compatible
binary packages, then lets pip build from source as a last resort. A failed restore
leaves only the newly created environment for inspection; it does not modify an
existing environment.

The default `-g planned` strategy executes the ranked candidates package by package
and automatically advances to the next candidate after a download/build failure.
Afterwards it verifies every exact pin without contacting an index and runs
`pip check`. `-g pip` retains the simpler whole-requirements resolver as a fallback
for comparison during this experiment.

## Cache and cloud repository

```console
pload repo add lab frpxiaoxin:/home/tibless/pload-cloud -t ssh
pload repo push lab training-cu121
pload repo pull lab training-cu121
pload repo ls
```

`PLOAD_HOME/cache/wheels` is shared by export, restore and `pload new`. SSH uses
existing OpenSSH configuration and stores wheel objects by SHA-256. Snapshots use
hard links to identical objects, so repeated environments do not upload or store
the same large CUDA wheel again. Pull verifies the manifest and reuses an identical
local cached wheel before transferring it.

A local directory uses `-t local`. A Git/GitHub repository uses `-t git` and stores
recipes only; large wheels belong in SSH/local storage. Git credentials, SSH keys
and commit identity remain managed by the existing tools. pload stores no passwords
or tokens, and strips credentials/query parameters from recorded index URLs.

## Interoperability

For venv, virtualenv, uv, Poetry or Pipenv, point export at the environment Python:

```console
pload export external -p /project/.venv/bin/python -b all
```

The `requirements.txt` file can be installed by pip and uv. Native lock formats
are not parsed; ask the original tool to export a requirements file first. Native
Conda environments need Conda's export because channels and native libraries are
not represented by pip metadata. A pip-only requirements file from Conda can still
be imported deliberately.

## Current experimental boundaries

- pload records GPU driver context but does not back up or install drivers.
- It caches Python package artifacts, not system libraries, datasets or model files.
- `--portable` re-resolves fixed versions; it cannot promise identical binary behavior.
- The planner does not query every index in advance, so online availability is provisional.
- The SSH store has no catalogue, garbage collector or interrupted-transfer resume yet.
- Remote artifacts are pulled and installed locally; site-packages are not mounted remotely.

These boundaries keep the first version inspectable and dependency-light while
leaving room for a future PEP 751 lock adapter, remote catalogue and richer platform
capability rules.
