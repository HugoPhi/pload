from rich import box
from rich.console import Console
from rich.table import Table


def _console():
    return Console(highlight=False)


def print_environment_table(environments):
    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="blue")
    table.add_column("ID", style="bold green", no_wrap=True)
    table.add_column("NAME", style="bold", no_wrap=True)
    table.add_column("PYTHON", style="yellow", no_wrap=True)
    table.add_column("DESCRIPTION")
    table.add_column("PATH", style="dim", overflow="fold")
    for item in environments:
        table.add_row(
            item.get("id", "-"),
            item.get("name", "-"),
            item.get("python", "unknown"),
            item.get("description") or "—",
            item.get("path", "-"),
        )
    _console().print(table)


def print_python_table(runtimes):
    table = Table(box=box.ROUNDED, header_style="bold cyan", border_style="blue")
    table.add_column("ID", style="bold green", no_wrap=True)
    table.add_column("ALIAS", style="bold cyan", no_wrap=True)
    table.add_column("VERSION", style="bold green", no_wrap=True)
    table.add_column("TYPE", style="yellow", no_wrap=True)
    table.add_column("PATH", style="dim", overflow="fold")
    for runtime in runtimes:
        table.add_row(
            runtime.id or "-",
            runtime.alias or "-",
            runtime.version,
            runtime.source,
            str(runtime.path),
        )
    _console().print(table)
