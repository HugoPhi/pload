# Maintenance plan

Changes are developed on a release branch and merged to `main` only after the
release checklist passes. Each stable merge receives a matching annotated tag.

## Pre-release testing

Every release candidate is assigned a PEP 440 pre-release version such as
`1.1.0a1`, `1.1.0b1` or `1.1.0rc1`; development builds must never present
themselves as the current stable version.

Before a pre-release is promoted or merged as a stable release:

1. Build and run the full cross-platform CI matrix.
2. Install the pre-release into the maintainer's private pload runtime on macOS.
3. Preserve the existing `PLOAD_HOME`, environment registry, caches and managed
   environments while replacing only the application runtime.
4. Verify `pload --version`, the welcome page, help, Python discovery, environment
   listing, and the new feature's primary workflow on that Mac.
5. Keep the version as a pre-release until the maintainer explicitly accepts it.

## 0.4.x: portable foundation

- Centralize filesystem and interpreter resolution.
- Preserve the established command vocabulary while removing install-time
  shell-profile mutation.
- Test Python 3.8 through the current stable Python on Linux, macOS, and Windows.
- Publish wheels and source distributions from the same metadata.

## 0.5.x: declarative projects

- Provide a guided private-runtime installer and configurable managed-Python
  downloads without requiring pyenv.
- Introduce an optional `pload.toml` for interpreter, environment path, index,
  and dependency declarations.
- Add non-interactive sync and diagnostics commands.
- Define migration behavior for legacy `~/venvs` installations.

## 0.6.x: interpreter discovery

- Discover and classify Python installations from the operating system, PATH,
  uv, pyenv, Conda, mise, asdf, Homebrew, and Windows Python Launcher.
- Resolve version requests only after probing the real interpreter version.
- Keep discovery filterable and deterministic across platforms.

## 1.0.x: stable interface

- Freeze CLI and configuration compatibility guarantees.
- Document recovery, backup, and upgrade behavior.
- Require a clean cross-platform matrix and installation smoke test before
  every stable merge.

## Stable release checklist

1. Run unit and end-to-end tests on Linux, macOS, and Windows.
2. Build both wheel and source archive, then install each in a clean environment.
3. Verify activation in Bash, Zsh, Fish, and PowerShell.
4. Update the changelog and remove the `Unreleased` marker.
5. Merge the release branch to `main` without rewriting published history.
6. Create an annotated `vX.Y.Z` tag and publish from that tag.
