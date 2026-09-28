from pload import ui


def print_environment_table(environments):
    table = ui.table(
        ("ID", "bold cyan", {"width": 4, "no_wrap": True}),
        ("NAME", "bold", {"width": 16, "overflow": "ellipsis", "no_wrap": True}),
        ("PYTHON", "yellow", {"width": 8, "no_wrap": True}),
        ("DESCRIPTION", "", {"width": 18, "overflow": "ellipsis", "no_wrap": True}),
        ("PATH", "dim", {"min_width": 12, "ratio": 1,
                          "overflow": "ellipsis", "no_wrap": True}),
        expand=True,
    )
    for item in environments:
        table.add_row(
            item.get("id", "-"),
            item.get("name", "-"),
            item.get("python", "unknown"),
            item.get("description") or "—",
            item.get("path", "-"),
        )
    ui.console().print(table)


def print_python_table(runtimes):
    table = ui.table(
        ("ID", "bold cyan", {"width": 5, "no_wrap": True}),
        ("ALIAS", "cyan", {"width": 20, "overflow": "ellipsis", "no_wrap": True}),
        ("VERSION", "green", {"width": 10, "no_wrap": True}),
        ("TYPE", "yellow", {"width": 10, "no_wrap": True}),
        ("PATH", "dim", {"min_width": 14, "ratio": 1,
                          "overflow": "ellipsis", "no_wrap": True}),
        expand=True,
    )
    for runtime in runtimes:
        table.add_row(
            runtime.id or "-",
            runtime.alias or "-",
            runtime.version,
            runtime.source,
            str(runtime.path),
        )
    ui.console().print(table)
