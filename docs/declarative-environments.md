# Declarative environments

The `1.1` pre-release replaces the transport-oriented snapshot experiment with
a small portable configuration plus a pload-managed lock. Users describe the
desired state; pload discovers resources, chooses a deterministic plan and
materializes that state.

```console
pload describe v2 -o pload.toml
pload apply pload.toml
```

`describe` is the bridge for an existing environment. For a new project,
`pload.toml` may be written by hand with names, ranges or exact
`NAME==VERSION` requirements; `plan` produces the managed lock.

## Two files, two responsibilities

`pload.toml` is the file a user reads and edits. It contains only the desired
Python, direct dependency requirements, target platform, policies and resource
providers. For example:

```toml
schema = 1
name = "llm-training"

[environment]
python = "3.12.7"
implementation = "cpython"
system = "Linux"
machine = "x86_64"
dependencies = ["numpy>=2,<3", "torch"]

[capabilities]
nvidia_driver = ["550.90.07"]

[policy]
reproducibility = "exact"
network = "allow"
source_build = "fallback"
publish_missing_artifacts = true
repositories = ["lab"]

[sources.default]
kind = "index"
url = "https://pypi.org/simple"

[repositories.lab]
kind = "ssh"
location = "frpxiaoxin:/home/tibless/pload-cloud"
```

`pload plan` writes its decisions to `.pload_lock.toml` in the same directory:

```toml
schema = 1
configuration = "pload.toml"
configuration_sha256 = "..."

[environment]
dependencies = ["numpy==2.1.3", "torch==2.5.0+cu121", "..."]

[[package]]
name = "torch"
version = "2.5.0+cu121"
sources = ["default"]

[[package.artifact]]
filename = "torch-2.5.0+cu121-cp312-cp312-linux_x86_64.whl"
sha256 = "..."
tags = ["cp312-cp312-linux_x86_64"]
repositories = ["lab"]
```

The lock is generated data, not a second user configuration. It records the
complete transitive dependency closure, exact versions, wheel identities,
SHA-256 hashes, compatibility tags and known artifact locations. The
`configuration_sha256` binds it to the current `pload.toml`; editing the user
configuration makes the old lock stale and the next online plan replaces it
atomically. Commit both files when reproducibility matters, but normally edit
only `pload.toml`.

The lock is necessary for **exact** reproduction because a requirement such as
`torch` or even `torch==2.8.0` does not uniquely identify all transitive versions
or a particular wheel build. Package indexes change over time. The filename and
SHA-256 in the lock let pload prove that a cached, cloud-hosted or downloaded
artifact is the same byte sequence chosen originally. Deleting the lock is safe:
the next online `plan` resolves a new one, but the result may differ. Offline
planning cannot regenerate a missing or stale lock.

Python runtimes and wheel bytes remain in caches, indexes or content-addressed
repositories; the two TOML files contain only control information. Credentials
are never stored in either file; SSH uses the existing SSH agent/configuration.
`describe` writes both files automatically. URLs containing embedded
credentials or query-string tokens are rejected; authentication belongs to the
machine, not a shareable environment description.

## Complete `pload.toml` field reference

`pload.toml` has five user-facing logical parts. Unknown TOML fields are reserved
for future schema versions and should not be relied upon. The generated lock
format is documented separately below so it can be audited, not hand-maintained.

### Top-level identity

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `schema` | integer | yes | File-format version. The current and only accepted value is `1`. It is not the pload package version. |
| `name` | string | yes | Default name used by `pload apply`. It must be 1–100 letters, numbers, dots, underscores or hyphens, starting with a letter or number. `apply --name` may override it without changing the file. |

### `[environment]`: desired runtime state

| Field | Type | Default | Meaning and enforcement |
| --- | --- | --- | --- |
| `python` | string | none; required | Exact Python version, currently including the patch component, such as `3.12.7`. The planner reuses a matching discovered interpreter or schedules an installation when network policy allows it. |
| `implementation` | string | `"cpython"` | `sys.implementation.name`, normally `cpython` or `pypy`. `apply` rejects a different implementation. |
| `system` | string | empty | Target `platform.system()`, such as `Linux`, `Darwin` or `Windows`. A non-empty value is a hard compatibility constraint. |
| `machine` | string | empty | Target `platform.machine()`, such as `x86_64`, `AMD64`, `arm64` or `aarch64`. A non-empty value is a hard compatibility constraint. |
| `dependencies` | array of strings | `[]` | Direct package requirements owned by the user. Entries may be names (`numpy`), version constraints (`pandas>=2,<3`) or exact pins (`numpy==2.1.3`). `plan` never replaces this list with transitive dependencies; resolved versions belong to `.pload_lock.toml`. Direct URLs and environment markers are intentionally rejected in schema 1. pip, setuptools and wheel bootstrap packages are omitted by `describe`. |

The environment section is desired state, not a command sequence. Paths to a
source virtual environment are never stored here, so the configuration remains
portable. The current schema describes one target platform and one exact Python
version; use separate files for different targets until multi-target locks exist.

For example, this is a valid initial request:

```toml
dependencies = ["numpy", "pandas>=2,<3"]
```

`pload plan` asks pip under the requested interpreter to resolve these requirements
and their transitive dependencies as compatible wheels. It then atomically writes
exact `NAME==VERSION` results, wheel filenames, SHA-256 hashes and tags to
`.pload_lock.toml`; `pload.toml` remains unchanged. Resolution uses all declared
indexes, with `default` as the primary index. It requires network access once;
`--offline` rejects an unlocked file rather than guessing. A second plan is
read-only and does not run the resolver again.

Editing dependencies after a lock exists is also supported. For example, adding
`"torch"` to a configuration with an existing `.pload_lock.toml` marks that lock
as stale. The next online plan resolves the complete
requested set—including existing exact constraints—rather than rejecting the
file or silently dropping the new package. The resolver receives the pload wheel
cache as a local candidate source, so compatible cached wheels are preferred and
only missing artifacts need index access. The reconciled complete lock replaces
the old one atomically.

Configurations produced by pre-`1.1.0a8` previews may still contain embedded
`[[package]]` tables. The first `plan` migrates those tables to
`.pload_lock.toml` without downloading again and rewrites `pload.toml` in the
clean declaration-only format. Because older previews replaced the original
direct requirements with the complete closure, they cannot always recover which
packages the user originally typed; those exact requirements remain valid and
can be simplified manually afterward.

### `[capabilities]`: observed non-Python context

Each capability is an array of strings. `describe` currently recognizes
`nvidia_driver` and records the driver versions reported by `nvidia-smi`:

```toml
[capabilities]
nvidia_driver = ["550.90.07"]
```

Capabilities are provenance and planning information, not installable Python
artifacts. The current executor does not install, downgrade or require an exact
NVIDIA driver match. CUDA-enabled wheels are locked separately under
`[[package.artifact]]`; drivers and system libraries remain host responsibilities.
Unknown capability keys are preserved by the parser as arrays of strings but do
not affect planning in schema 1.

### `[policy]`: permitted ways to reach the desired state

| Field | Allowed values / type | Default | Meaning |
| --- | --- | --- | --- |
| `reproducibility` | `"exact"` or `"compatible"` | `"exact"` | `exact` requires a declared wheel identity and SHA-256 for every package. `compatible` keeps exact versions but may obtain a new artifact build from an index. |
| `network` | `"allow"` or `"offline"` | `"allow"` | Controls internet index access and automatic Python installation. `offline` still permits configured local and SSH repositories. CLI `--offline` can only make a run stricter; it cannot override an offline file to allow internet access. |
| `source_build` | `"fallback"` or `"forbid"` | `"fallback"` | Applies to compatible re-resolution. `forbid` passes `--only-binary=:all:`; `fallback` allows pip to use an sdist when no wheel exists. Exact mode always installs the locked wheel and never rebuilds it. |
| `publish_missing_artifacts` | boolean | `true` | After `apply` obtains exact wheels, publish their SHA-addressed bytes to every repository named by `policy.repositories`. `false` makes those repositories read-only candidates for this configuration. |
| `repositories` | array of strings | `[]` | Logical repository names preferred for lookup and optional automatic publication. Every name must have a matching `[repositories.NAME]` table. This is a candidate set, not a user-visible upload sequence. |

Command-line `--offline` is intentionally one-way: it prevents a configuration
from unexpectedly using the internet, while a file declaring `network =
"offline"` cannot be weakened accidentally by omitting the flag.

Changing `environment.python` does not make native wheels portable. During
planning, pload parses every locked wheel filename and compares its Python, ABI
and platform tags with the requested runtime. For example, a cached `cp39-cp39`
wheel is rejected for Python 3.8 even when its checksum is valid. Under `exact`,
that makes the plan unavailable; under `compatible`, the planner may select an
explicit `index-resolve / network` route for that package. Universal wheels such
as `py3-none-any` can still be reused. `apply` never silently treats an
incompatible cached wheel as ready.

### `[sources.NAME]`: Python package indexes

`NAME` is a logical identifier used by package locks, for example `default` or
`pytorch-cu121`:

```toml
[sources.pytorch-cu121]
kind = "index"
url = "https://download.pytorch.org/whl/cu121"
```

| Field | Type | Meaning |
| --- | --- | --- |
| `kind` | string | Must be `"index"` in schema 1. |
| `url` | string | HTTP(S) Simple API base URL. Embedded usernames, passwords and query parameters are rejected because this file is intended to be shared. Configure authentication on the machine instead. |

Source names must follow the same safe-name rules as the environment name. A
package lists its allowed source names in `package.sources`. In compatible mode,
the first listed source is the primary resolver source. In exact mode, an index
is accepted only if it returns the declared wheel filename and its bytes match
the declared SHA-256.

### `[repositories.NAME]`: reusable artifact stores

Repositories store immutable bytes by content hash rather than by environment:

```toml
[repositories.lab]
kind = "ssh"
location = "frpxiaoxin:/home/tibless/pload-cloud"

[repositories.shared-disk]
kind = "local"
location = "./pload-artifacts"
```

| Field | Allowed values | Meaning |
| --- | --- | --- |
| `kind` | `"local"` or `"ssh"` | Selects filesystem copying or OpenSSH/SFTP transport. |
| `location` | path or `HOST:/absolute/path` | A local absolute path, a path relative to the TOML file's directory, or an SSH alias/host plus absolute remote directory. SSH paths cannot contain spaces or `..`; `/` itself is rejected. |

The physical layout is `objects/<sha256>`. SSH credentials, host keys, ports,
proxies and jump hosts remain in normal OpenSSH configuration. The remote host
must provide a POSIX shell and `sha256sum`. Repository names referenced by a
policy or artifact must exist in this file. Missing or unreachable providers are
removed from the plan and another valid route is tried.

The TOML control file may itself be versioned in Git or hosted on GitHub. Large
wheel bytes should remain in these content-addressed local/SSH repositories rather
than being committed to Git.

## Complete `.pload_lock.toml` field reference

The lock's top-level `schema` is currently `1`. `configuration` names the sibling
user configuration and `configuration_sha256` identifies its canonical content.
`[environment].dependencies` contains the complete, sorted exact dependency
closure selected by the resolver. These fields let pload distinguish a reusable
lock from one made stale by editing or renaming the configuration.

### `[[package]]`: one resolved package

There is one array entry for every application dependency:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | yes | Distribution name from installed metadata. Comparison is normalized according to Python package-name rules, so `python_dateutil` and `python-dateutil` identify the same project. |
| `version` | string | yes | Exact installed version, including a local suffix such as `+cu121` when present. |
| `sources` | array of strings | no | Logical `[sources.NAME]` entries allowed to satisfy this package. Each referenced source must exist. `describe -s PACKAGE=URL` creates a package-specific source when installed metadata cannot reliably reveal it. |
| `artifact` | array of tables | no | Exact wheel identities accepted for this package. Exact policy needs at least one reachable artifact route; compatible policy may omit artifacts and re-resolve the pinned version. |

Users should not add or remove these records manually. Delete `.pload_lock.toml`
and run `pload plan` when a complete re-resolution is wanted.

### `[[package.artifact]]`: exact wheel identity

An artifact table belongs to the immediately preceding `[[package]]` entry:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `filename` | string | yes | Exact wheel filename, including Python, ABI and platform tags. Source archives are not accepted as exact artifacts. |
| `sha256` | string | yes | Lowercase 64-character SHA-256 digest of the complete wheel. Every cache, repository and index retrieval is checked against it before installation. |
| `tags` | array of strings | no | Wheel compatibility tags extracted from the filename, such as `cp312-cp312-linux_x86_64` or `py3-none-any`. They are recorded for inspection; pip remains the final wheel-compatibility validator. |
| `repositories` | array of strings | no | Repositories known to contain this digest. The planner also checks repositories listed globally in `policy.repositories`, allowing newly cached objects to be reused without rewriting the package entry. |

The schema permits more than one artifact entry for future multi-platform locks,
but schema 1 `describe` emits one artifact for the described target and the
environment's OS/architecture remain hard constraints. A hash proves byte
identity and detects corruption; it does not establish that a repository owner or
package is trustworthy.

### Minimal hand-written compatible configuration

This is the smallest practical file that asks pload to resolve pinned packages
online without claiming byte-for-byte wheel reproducibility:

```toml
schema = 1
name = "analysis"

[environment]
python = "3.12.7"
dependencies = ["numpy==2.1.3", "pandas==2.2.3"]

[policy]
reproducibility = "compatible"
network = "allow"
source_build = "forbid"
publish_missing_artifacts = false

[sources.default]
kind = "index"
url = "https://pypi.org/simple"
```

`implementation`, `system`, `machine`, `capabilities` and `repositories` are
filled or omitted according to the defaults described above. `.pload_lock.toml`
is generated separately. For durable sharing, commit both files and prefer
`pload describe` so exact package and artifact identity is captured rather than
inferred.

## Describe an existing environment

```console
pload describe v2
pload describe /project/.venv -o project.pload.toml
pload describe /project/.venv/bin/python -o project.pload.toml
```

The default `exact` mode obtains one wheel for every application package,
computes its SHA-256, places it in the shared cache and automatically publishes
it to the first configured local/SSH artifact repository. The repository is
declared in `pload.toml`; the artifact-to-repository association is recorded in
`.pload_lock.toml`.

Use a specific configured repository when necessary:

```console
pload describe v2 -r lab
```

Installed metadata does not always preserve the original package index. Record a
dedicated source explicitly for packages such as CUDA-enabled PyTorch; repeat the
option for multiple packages:

```console
pload describe v2 \
  -s torch=https://download.pytorch.org/whl/cu121 \
  -s torchvision=https://download.pytorch.org/whl/cu121
```

If a package has no compatible wheel, exact description stops instead of quietly
claiming reproducibility. `--mode compatible` records exact versions but permits
a future machine to re-resolve their artifacts:

```console
pload describe v2 --mode compatible
```

Compatible mode is useful for exploration, but it is weaker than an artifact lock.

## Plan against available resources

```console
pload plan
pload plan project.pload.toml
pload plan --offline
pload plan --json
```

If no current `.pload_lock.toml` exists, the first online `plan` performs a lock
step before resource selection—even when every direct requirement is pinned. Its
output reports that `.pload_lock.toml` was written. The generated lock contains the
complete wheel dependency closure, so `apply` does not ask pip to resolve
dependencies again. Schema 1 currently requires wheel availability during this
automatic lock step; it does not create a portable exact lock from an sdist.

The planner inventories:

1. installed and discoverable Python interpreters;
2. the pload wheel cache;
3. an `artifacts/` directory beside the configuration;
4. content-addressed local and SSH repositories named in the file;
5. package indexes named in the file;
6. target OS, architecture and Python implementation.

The Python row and package rows describe separate resources. A plan may reuse
every package from cache while still showing `Python: install-python · ... ·
network`; in that case the download is the Python runtime itself. `reuse-python ·
... · ready` means no runtime download is planned.

It first rejects candidates that violate hard requirements. Remaining candidates
are ordered lexicographically by reproducibility loss, compatibility risk,
network acquisition, execution cost and a deterministic tie-breaker. This avoids
fragile arbitrary totals where a cheap but incompatible resource could win merely
by accumulating points.

The current first implementation chooses per-package routes and deduplicates
artifacts by SHA-256. A later global optimizer can combine connections, builds and
downloads across packages without changing the file format.

## Apply desired state

```console
pload apply
pload apply project.pload.toml
pload apply project.pload.toml -n project-copy
pload apply project.pload.toml --offline
```

`apply` performs the internal operations that were previously exposed as export,
push, pull and restore:

1. resolve or install the declared Python;
2. verify implementation, exact Python version, OS and architecture;
3. reuse exact local artifacts;
4. retrieve missing SHA-addressed artifacts from configured repositories;
5. fall back to an index only when policy permits it;
6. verify every artifact before installation;
7. create and register the environment;
8. install exact packages and run `pip check`;
9. record the applied configuration digest inside the environment.

Running `apply` again is idempotent when the environment already carries the same
configuration digest. If the name exists with different state, pload refuses to
overwrite it. Destructive replacement is deliberately not implicit. If package
installation or verification fails, the newly created environment and registry
entry are rolled back; an existing environment is never modified.

## Resource storage

Local and SSH artifact repositories store bytes at:

```text
objects/<sha256>
```

Two configurations referencing the same large CUDA wheel therefore store and
transfer one object. `.pload_lock.toml` contains the checksum and logical
repository name; the user does not run upload/download commands. A missing or
unreachable provider is simply removed from the candidate set, and apply tries
the next valid route.

## Compatibility and boundaries

- Exact locks are platform-specific unless the wheel is universal.
- A different OS, architecture or exact Python patch version currently requires
  a separately described configuration. Multi-target locks are planned.
- Detected NVIDIA driver versions are recorded as capability provenance. Drivers
  and system libraries are not installed by pload and are not backed up as if
  they were Python artifacts.
- CUDA-enabled Python wheels are ordinary locked artifacts and can be cached in
  the content repository. This preserves the large, slow-to-download package even
  though the host driver remains the machine administrator's responsibility.
- Native Conda packages require a future Conda provider; they are not silently
  converted to pip packages.
- Package installation may execute code. Only use configurations and providers
  you trust; checksums prove identity, not trustworthiness.

## Abandoned snapshot experiment

The earlier `export → repo push/pull → restore` interface is not the public model
for 1.1. Its useful internals—probing, hashing, caches and content-addressed SSH
storage—remain providers behind `describe`, `plan` and `apply`. Before a stable
release, the experimental format was abandoned and is intentionally not carried
forward.
