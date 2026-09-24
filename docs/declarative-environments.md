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
storage—remain providers behind `describe`, `plan` and `apply`. The experimental
format was never part of a stable release and is intentionally not carried forward.
