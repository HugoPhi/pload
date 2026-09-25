# Declarative environments

The `1.2` preview treats reproduction as resource scheduling, not as a sequence
of commands the user must design. You carry one small `pload.toml`; pload
resolves exact versions, inventories available resources, saves an auditable
route for every package, and executes exactly those routes.

```text
pload.toml (intent)
       │
       ▼
metadata-only resolution ──► .pload_lock.toml (exact graph and wheel identities)
       │
       ▼
local/remote inventory ─────► .pload_plan.toml (one chosen route per package)
       │
       ▼
pload apply ────────────────► environment matching the lock
```

The normal workflow is:

```console
pload plan pload.toml       # resolve metadata, inventory and choose routes
pload apply pload.toml      # execute only the saved plan
```

In a terminal, `plan` opens a route chooser. A number selects a route; Enter or
`n` moves forward, `p` goes back, `u` undoes, `r` restores the fastest choices,
`s` saves, and `a` saves then applies. Use `pload plan --no-ui` in CI. Use
`--json` for machine-readable inspection.

## Three files, one user-owned file

- `pload.toml` is portable user intent. This is the only file users edit.
- `.pload_lock.toml` is pload-managed exact resolution data.
- `.pload_plan.toml` is pload-managed execution data bound to that exact config
  and lock.

The two dotfiles exist because a request such as `torch` does not identify one
version, dependency closure, wheel build, or byte sequence. The lock records
those facts; the plan records where each exact artifact will come from. Editing
`pload.toml` invalidates both through SHA-256 bindings. Deleting either managed
file is safe: the next online `plan` regenerates it, although a new resolution
may differ if an index changed.

`plan` may request Simple API project pages and independent `<wheel>.metadata`
files. It never requests a wheel body, invokes `pip download`, copies packages,
or populates a cache. If an index does not expose independent Core Metadata,
planning stops and suggests adding a metadata-capable source. `apply` never
re-resolves, changes route, or publishes artifacts when a selected route fails.

## Complete `pload.toml` reference

```toml
schema = 1
name = "training"

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
source_build = "forbid"
publish_missing_artifacts = false
repositories = ["lab"]

[sources.pypi]
kind = "index"
url = "https://pypi.org/simple"

[sources.mirror]
kind = "index"
url = "https://pypi.tuna.tsinghua.edu.cn/simple"

[repositories.lab]
kind = "ssh"
location = "frpxiaoxin:/home/tibless/pload-cloud"
```

### Top level

| Field | Type | Meaning |
| --- | --- | --- |
| `schema` | integer, required | Configuration format; currently `1`. |
| `name` | string, required | Default environment name used by `apply`. Allowed characters are letters, numbers, dots, underscores and hyphens. |

### `[environment]`

| Field | Default | Meaning |
| --- | --- | --- |
| `python` | required | Exact target Python, including patch version. |
| `implementation` | `"cpython"` | Required interpreter implementation. |
| `system` | empty | Optional hard `platform.system()` constraint. |
| `machine` | empty | Optional hard `platform.machine()` constraint. Common aliases such as `AMD64`/`x86_64` and `aarch64`/`arm64` are normalized. |
| `dependencies` | `[]` | Direct requirements: names, ranges, or exact pins. Direct URLs and environment markers are rejected in schema 1. Transitive packages stay out of this user file. |

An unpinned entry is intentional. During `plan`, pload selects the newest
compatible dependency graph using only index metadata, then writes exact
versions and wheel identities to the managed lock.

### `[capabilities]`

Every capability is an array of strings. `nvidia_driver` records observed
driver versions for audit and future scheduling. pload does not install CUDA
drivers. CUDA-enabled Python wheels can still be cached locally or remotely and
reused exactly, which avoids repeatedly downloading large special builds.

### `[policy]`

| Field | Default | Meaning |
| --- | --- | --- |
| `reproducibility` | `"exact"` | `exact` requires a locked wheel hash or a verified environment-copy route. `compatible` may install the locked version from an index when no exact artifact is known. |
| `network` | `"allow"` | `offline` forbids index access and Python installation; local and configured SSH resources remain usable. CLI `--offline` can only make policy stricter. |
| `source_build` | `"fallback"` | In compatible mode, `forbid` disallows source distributions. Exact wheel routes never build source. |
| `publish_missing_artifacts` | `false` recommended | Retained for schema-1 compatibility but ignored by `apply`. Upload is always explicit through `pload remote add`. |
| `repositories` | `[]` | Repositories to search while planning. Every name must have a matching repository table. This never authorizes upload. |

### `[sources.NAME]`

| Field | Meaning |
| --- | --- |
| `kind` | Must be `"index"`. |
| `url` | Public HTTP(S) Simple API base URL. Credentials and query tokens are rejected from portable files. |

Sources are searched for compatible wheel metadata. A mirror may serve wheel
files but omit PEP 658/714 Core Metadata; in that case add a metadata-capable
source such as PyPI. pload will not hide this limitation by downloading wheels
during analysis.

### `[repositories.NAME]`

| Field | Meaning |
| --- | --- |
| `kind` | `"local"` or `"ssh"`. |
| `location` | Local path, or `HOST:/absolute/path` using normal OpenSSH configuration. |

Objects live at `objects/<sha256>` and searchable package records at
`packages/<normalized-name>/<version>/<wheel>.json`. Credentials remain in the
host's SSH agent/config, never in TOML.

Configure providers separately, then back up selected packages explicitly:

```console
pload repo add lab frpxiaoxin:/home/tibless/pload-cloud -t ssh
pload remote add torch --from v10 --remote lab
pload remote add numpy==2.1.0 -f ./project/.venv -r lab
```

`remote add` reuses a matching original wheel when possible. If it is absent,
the command may fetch that exact installed version from `--index`; this is an
explicit storage operation, unlike `plan` and `apply`.

## Managed lock reference

`.pload_lock.toml` contains:

| Field | Meaning |
| --- | --- |
| `schema` | Managed lock format, currently `1`. |
| `configuration` | Sibling user configuration filename. |
| `configuration_sha256` | Canonical digest that makes edited configs stale. |
| `[environment].dependencies` | Complete exact transitive closure. |
| `[[package]].name/version` | One exact resolved distribution. |
| `[[package]].sources` | Source that supplied its metadata. |
| `[[package.artifact]].filename` | Exact compatible wheel filename. |
| `sha256` | Required wheel body identity. |
| `tags` | Python/ABI/platform compatibility tags. |
| `url` | Exact artifact URL selected from the Simple API. |
| `size` | Advertised artifact bytes when the index supplies it. |
| `metadata_sha256` | Hash of the independently fetched Core Metadata when supplied. |
| `repositories` | Known repositories containing the object; policy repositories are also checked by hash. |

Resolution honors `Requires-Python`, wheel tags, `Requires-Dist`, dependency
markers, yanked releases, hashes and target Python/platform. A repository
without independent metadata is reported as blocked instead of causing an
analysis-time wheel download.

## Managed plan reference

`.pload_plan.toml` stores configuration and lock hashes, the Python action,
readiness, and one route for every locked package:

```toml
schema = 1
configuration = "pload.toml"
configuration_sha256 = "..."
lock_sha256 = "..."
name = "training"
ready = true

[[package]]
name = "numpy"
version = "2.2.1"
method = "external-cache"
location = "/Users/me/Library/Caches/pip/.../numpy-2.2.1.whl"
status = "ready"
estimated_seconds = 0.2

[package.artifact]
filename = "numpy-2.2.1-cp312-cp312-macosx_14_0_arm64.whl"
sha256 = "..."
url = "https://files.pythonhosted.org/..."
```

| Method | Meaning |
| --- | --- |
| `cache` | Exact SHA-matching wheel in pload's cache. |
| `configuration-artifact` | Exact wheel under the configuration's `artifacts/`. |
| `external-cache` | Exact wheel in configured or common pip/uv cache roots. |
| `environment-copy` | Exact installed distribution from a compatible pload environment, guarded by its `RECORD` fingerprint. Packages with files outside site-packages are excluded. |
| `repository` | SHA-addressed object from a local/SSH store. |
| `index-exact` | Exact locked URL, downloaded only during apply and verified by SHA-256. |
| `index-resolve` | Compatible-mode fallback for the already locked version. |

Automatic ranking minimizes expected time: existing bytes first, compatible
local environments next, repositories next, and indexes last. The chooser can
override it. If the chosen resource changes or disappears, `apply` stops and
asks for a new plan; it never tries another candidate.

## Current boundaries

- Wheel reuse requires matching Python, ABI, OS and architecture tags.
- Environment copying additionally requires exact Python implementation,
  version, OS, architecture and an unchanged installed `RECORD` fingerprint.
- Conda native libraries, system packages and GPU drivers are context, not
  installed by the schema-1 executor.
- Source builds, editable installs and arbitrary direct URLs cannot currently
  provide the same byte-for-byte guarantees as locked wheels.
- Index authentication is machine configuration; portable TOML never embeds
  secrets.

These boundaries are reported explicitly. They are never converted into an
unplanned download, fallback route, upload, or silent partial environment.
