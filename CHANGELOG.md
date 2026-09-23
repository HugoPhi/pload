# Changelog

## 0.4.0 - Unreleased

### Added

- Fully relocatable data, environment, and state roots through CLI options and
  `PLOAD_HOME`, `PLOAD_VENVS_DIR`, and `PLOAD_STATE_DIR`.
- Independent `--project-dir` and `--venv-dir` options for local environments.
- Explicit-path environment creation and interpreter selection.
- Side-effect-free shell integration for Bash, Zsh, Fish, and PowerShell.
- Automated tests and multi-platform continuous integration.

### Changed

- pyenv is optional; the current interpreter is used when no version is given.
- Packaging uses `pyproject.toml` and builds both wheels and source archives.
- Package installation no longer edits shell profiles.
- Expected failures now return concise messages instead of Python tracebacks.

### Fixed

- Missing color method during dependency installation.
- Crashes when pyenv, state files, or environment directories do not exist.
- Hard-coded Homebrew and home-directory paths.
- Inconsistent project metadata and license declaration.

