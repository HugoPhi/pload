# Declarative environments

The `1.1` pre-release replaces the transport-oriented snapshot experiment with
one portable environment configuration. Users describe the desired state; pload
discovers resources, chooses a deterministic plan and materializes that state.

```console
pload describe v2 -o pload.toml
pload apply pload.toml
```

`describe` is the bridge for an existing environment. For a new project, the
same file may be written by hand with exact `NAME==VERSION` dependencies and a
`compatible` policy, then locked more strictly after it has been materialized.

## One file, two responsibilities

`pload.toml` contains both:

- **specification** — the Python, dependencies, target platform and policy the
  user wants;
- **lock** — exact package versions, wheel identities, SHA-256 hashes, compatible
  tags and logical resource locations discovered by pload.

The file is the control plane. Python runtimes and wheel bytes remain in caches,
indexes or content-addressed repositories and are the data plane. Credentials are
never stored in the file; SSH uses the existing SSH agent/configuration.

```toml
schema = 1
name = "llm-training"

[environment]
python = "3.12.7"
implementation = "cpython"
system = "Linux"
machine = "x86_64"
dependencies = ["numpy==2.1.3", "torch==2.5.0+cu121"]

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

`describe` writes the lock entries automatically. URLs containing embedded
credentials or query-string tokens are rejected; authentication belongs to the
machine, not a shareable environment description.

## Complete `pload.toml` field reference

The file has seven logical parts. `describe` normally writes all lock-related
fields, but the same schema can be reviewed or authored by hand. Unknown TOML
fields are reserved for future schema versions and should not be relied upon.

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
| `dependencies` | array of strings | `[]` | Complete desired application package set. Every entry must be an exact `NAME==VERSION` pin. When `[[package]]` lock entries exist, the two sections must describe the same normalized names and versions. pip, setuptools and wheel bootstrap packages are intentionally omitted by `describe`. |

The environment section is desired state, not a command sequence. Paths to a
source virtual environment are never stored here, so the configuration remains
portable. The current schema describes one target platform and one exact Python
version; use separate files for different targets until multi-target locks exist.

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

### `[[package]]`: one locked package

There is one array entry for every application dependency:

| Field | Type | Required | Meaning |
| --- | --- | --- | --- |
| `name` | string | yes | Distribution name from installed metadata. Comparison is normalized according to Python package-name rules, so `python_dateutil` and `python-dateutil` identify the same project. |
| `version` | string | yes | Exact installed version, including a local suffix such as `+cu121` when present. |
| `sources` | array of strings | no | Logical `[sources.NAME]` entries allowed to satisfy this package. Each referenced source must exist. `describe -s PACKAGE=URL` creates a package-specific source when installed metadata cannot reliably reveal it. |
| `artifact` | array of tables | no | Exact wheel identities accepted for this package. Exact policy needs at least one reachable artifact route; compatible policy may omit artifacts and re-resolve the pinned version. |

If `[[package]]` is entirely omitted, pload synthesizes package records from
`environment.dependencies`. That form is useful only for compatible online
resolution because it contains no exact artifact identity.

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

`implementation`, `system`, `machine`, `capabilities`, `repositories` and
`[[package]]` are filled or omitted according to the defaults described above.
For durable sharing, prefer `pload describe` so exact package and artifact lock
entries are generated and validated automatically.

## Describe an existing environment

```console
pload describe v2
pload describe /project/.venv -o project.pload.toml
pload describe /project/.venv/bin/python -o project.pload.toml
```

The default `exact` mode obtains one wheel for every application package,
computes its SHA-256, places it in the shared cache and automatically publishes
it to the first configured local/SSH artifact repository. The repository is
embedded in the resulting configuration as a logical resource provider.

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

The planner inventories:

1. installed and discoverable Python interpreters;
2. the pload wheel cache;
3. an `artifacts/` directory beside the configuration;
4. content-addressed local and SSH repositories named in the file;
5. package indexes named in the file;
6. target OS, architecture and Python implementation.

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
transfer one object. The TOML contains the checksum and logical repository name;
the user does not run upload/download commands. A missing or unreachable provider
is simply removed from the candidate set, and apply tries the next valid route.

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
