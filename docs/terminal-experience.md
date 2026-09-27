# Terminal experience

pload uses one interaction language across installation, environment creation,
planning, configuration, and destructive actions. The goal is predictable
behaviour, not decoration.

## Interaction model

- A normal command prints a compact result and exits. It never opens a full
  screen interface unexpectedly.
- A command that needs a choice uses `↑`/`↓` and Enter. The active row is
  prefixed with `❯`; the recommended value is selected initially.
- Package planning keeps navigation commands out of the source list. Use the
  visible first-letter shortcuts: `p` previous, `n` next, `u` undo, `r` reset,
  `s` save, `a` apply, and `q` quit.
- `pload new` is guided when no creation options are supplied. Every guided
  operation also has flags for scripts and automation.
- Destructive actions use a conventional `y/N` confirmation. `--yes` is the
  explicit non-interactive alternative.
- `Ctrl-C` cancels without a traceback.

## Visual language

| Treatment | Meaning |
| --- | --- |
| cyan | current focus, headings, and resources |
| green / `✓` | completed successfully |
| yellow / `!` | warning or required attention |
| red / `error:` | command failure |
| dim text | paths, provenance, and secondary explanation |

Tables are compact and border-light so rows remain readable at normal terminal
widths. Progress animation appears only on a TTY. `NO_COLOR=1` disables colour,
and `PLOAD_NO_PROGRESS=1` replaces spinners with plain text.

## Output contract

Primary results remain suitable for copying or piping. JSON modes write only
JSON to stdout. Progress and diagnostics use stderr where a command exposes
machine-readable output. Redirected input uses explicit flags or numbered
fallbacks instead of emitting terminal control sequences.

## Design references

The design follows [Atuin's compact keyboard-driven interaction](https://docs.atuin.sh/main/reference/search/),
[uv's concise help and TTY-aware progress](https://docs.astral.sh/uv/getting-started/help/),
[GitHub CLI's explicit prompt and accessibility controls](https://cli.github.com/manual/gh_help_environment),
[Cargo's automatic terminal capability detection](https://doc.rust-lang.org/cargo/reference/config.html#termprogresswhen),
and the human-first principles of the [Command Line Interface Guidelines](https://clig.dev/).
pload intentionally uses these conventions without turning every command into
a full-screen TUI.
