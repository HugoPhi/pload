"""One terminal language for every pload command.

Keep presentation decisions here so commands cannot invent their own colours,
symbols, tables, or prompt behaviour.  Rich owns output; Questionary owns
interactive input.  Both automatically degrade when output is redirected.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from contextlib import contextmanager

import questionary
from prompt_toolkit.styles import Style as PromptStyle
from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

ACCENT = "cyan"
SUCCESS = "green"
WARNING = "yellow"
DANGER = "red"
MUTED = "dim"

PROMPT_STYLE = PromptStyle.from_dict(
    {
        "qmark": "fg:#22d3ee bold",
        "question": "bold",
        "answer": "fg:#34d399 bold",
        "pointer": "fg:#22d3ee bold",
        "highlighted": "fg:#22d3ee bold",
        "selected": "fg:#34d399",
        "instruction": "fg:#7c8499",
        "text": "",
        "disabled": "fg:#7c8499 italic",
    }
)
PLAIN_PROMPT_STYLE = PromptStyle.from_dict(
    {name: "" for name in (
        "qmark", "question", "answer", "pointer", "highlighted",
        "selected", "instruction", "text", "disabled",
    )}
)


def _prompt_style():
    return PLAIN_PROMPT_STYLE if os.environ.get("NO_COLOR") is not None else PROMPT_STYLE


def _color_system():
    return None if os.environ.get("NO_COLOR") is not None else "auto"


class ArgumentParser(argparse.ArgumentParser):
    """Argparse with the same compact error language as the rest of pload."""

    def error(self, message):
        suggestion = None
        if "invalid choice:" in message and " (choose from " in message:
            summary, choices = message.split(" (choose from ", 1)
            candidates = [
                item.strip().strip("'\"")
                for item in choices.rstrip(")").split(",")
            ]
            invalid = re.findall(r"invalid choice: '([^']+)'", summary)
            if invalid:
                matches = difflib.get_close_matches(
                    invalid[0], candidates, n=1, cutoff=0.5,
                )
                suggestion = matches[0] if matches else None
            message = summary
        error(message)
        if suggestion:
            console(stderr=True).print(f"[dim]Did you mean '{suggestion}'?[/]")
        console(stderr=True).print(f"[dim]Try '{self.prog} -h' for help.[/]")
        raise SystemExit(2)


def console(*, stderr=False):
    return Console(stderr=stderr, highlight=False, color_system=_color_system())


def is_interactive():
    return sys.stdin.isatty() and sys.stdout.isatty()


def table(*columns, expand=False):
    """Build the compact table used throughout pload."""
    result = Table(
        box=box.SIMPLE_HEAD,
        header_style="bold cyan",
        show_edge=False,
        pad_edge=False,
        expand=expand,
    )
    for heading, style, kwargs in columns:
        result.add_column(heading, style=style, **kwargs)
    return result


def heading(title, subtitle=None, *, output=None):
    output = output or console()
    output.print()
    output.print(Text(title, style="bold cyan"))
    if subtitle:
        output.print(Text(subtitle, style="dim"))


def logo(*, output=None):
    """Render the single pload wordmark used by landing and setup screens."""
    output = output or console()
    output.print(Text(
        """   ____  _                 _
  |  _ \\| | ___   __ _  __| |
  | |_) | |/ _ \\ / _` |/ _` |
  |  __/| | (_) | (_| | (_| |
  |_|   |_|\\___/ \\__,_|\\__,_|""",
        style="bold cyan",
    ))


def success(message, *, detail=None, output=None):
    output = output or console()
    output.print(Text.assemble(("✓ ", "bold green"), (message, "white")))
    if detail:
        output.print(f"  [dim]{detail}[/]")


def info(message, *, output=None):
    (output or console()).print(Text.assemble(("• ", "cyan"), (message, "white")))


def warning(message, *, output=None):
    (output or console(stderr=True)).print(
        Text.assemble(("! ", "bold yellow"), (message, "yellow"))
    )


def error(message, *, output=None):
    (output or console(stderr=True)).print(
        Text.assemble(("error: ", "bold red"), (message, "red"))
    )


@contextmanager
def status(message):
    output = console(stderr=True)
    if output.is_terminal and os.environ.get("PLOAD_NO_PROGRESS") is None:
        with output.status(f"[cyan]{message}[/]", spinner="dots", spinner_style="cyan") as live:
            yield lambda value: live.update(f"[cyan]{value}[/]")
    else:
        output.print(f"[dim]{message}[/]")
        yield lambda value: None


def select(message, choices, *, default=None, instruction="↑/↓ move • enter select"):
    """Choose with normal cursor keys, with a numbered fallback for tests/pipes."""
    normalized = [
        item if isinstance(item, questionary.Choice) else questionary.Choice(str(item), value=item)
        for item in choices
    ]
    if is_interactive():
        return questionary.select(
            message,
            choices=normalized,
            default=default,
            instruction=instruction,
            pointer="❯",
            qmark="?",
            style=_prompt_style(),
            use_shortcuts=False,
            use_arrow_keys=True,
        ).unsafe_ask()

    default_index = 0
    values = [item.value for item in normalized]
    if default in values:
        default_index = values.index(default)
    print(f"\n{message}")
    for index, item in enumerate(normalized, 1):
        suffix = " (default)" if index - 1 == default_index else ""
        print(f"  {index}) {item.title}{suffix}")
    while True:
        answer = input(f"Choose [1-{len(normalized)}] [{default_index + 1}]: ").strip()
        if not answer:
            return normalized[default_index].value
        if answer.isdigit() and 1 <= int(answer) <= len(normalized):
            return normalized[int(answer) - 1].value


def text(message, *, default=""):
    if is_interactive():
        return questionary.text(
            message,
            default=str(default),
            qmark="?",
            style=_prompt_style(),
        ).unsafe_ask().strip()
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or str(default)


def confirm(message, *, default=False):
    if is_interactive():
        return questionary.confirm(
            message,
            default=default,
            qmark="?",
            style=_prompt_style(),
        ).unsafe_ask()
    suffix = "Y/n" if default else "y/N"
    answer = input(f"{message} [{suffix}]: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}
