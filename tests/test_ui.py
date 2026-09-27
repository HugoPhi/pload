from questionary import Choice

from pload import ui
from pload.cli import choose_declarative_routes


def test_select_has_numbered_fallback_when_terminal_ui_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr(ui, "is_interactive", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt: "2")

    selected = ui.select(
        "Choose a source",
        [Choice("Local cache", value="cache"), Choice("PyPI", value="index")],
        default="cache",
    )

    assert selected == "index"
    assert "1) Local cache (default)" in capsys.readouterr().out


def test_route_chooser_only_visits_direct_packages_and_supports_backtracking(monkeypatch):
    plan = {
        "python": {"status": "available"},
        "packages": [
            {
                "name": "torch",
                "version": "2.8.0",
                "direct": True,
                "selected": {
                    "method": "index",
                    "location": "https://pypi.org/simple",
                    "status": "available",
                    "estimated_seconds": 10.0,
                },
                "alternatives": [{
                    "method": "cache",
                    "location": "/cache/torch.whl",
                    "status": "available",
                    "estimated_seconds": 0.1,
                }],
            },
            {
                "name": "typing-extensions",
                "version": "4.15.0",
                "direct": False,
                "selected": {
                    "method": "cache",
                    "location": "/cache/typing_extensions.whl",
                    "status": "available",
                    "estimated_seconds": 0.1,
                },
                "alternatives": [],
            },
        ],
    }
    answers = iter([("route", 1), ("save", None)])
    prompts = []

    def choose(message, choices, **kwargs):
        prompts.append((message, choices))
        return next(answers)

    monkeypatch.setattr("pload.cli.ui.select", choose)

    assert choose_declarative_routes(plan) == "save"
    assert plan["packages"][0]["selected"]["method"] == "cache"
    assert plan["packages"][1]["selected"]["method"] == "cache"
    assert len(prompts) == 2
    assert all("typing-extensions" not in message for message, _ in prompts)


def test_no_color_disables_rich_ansi_sequences(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    output = ui.console()

    assert output.color_system is None
    assert ui._prompt_style() is ui.PLAIN_PROMPT_STYLE


def test_symbols_fall_back_for_legacy_windows_encodings():
    assert ui.glyph("✓", "[ok]", encoding="cp1252") == "[ok]"
    assert ui.glyph("❯", ">", encoding="cp1252") == ">"
    assert ui.glyph("✓", "[ok]", encoding="utf-8") == "✓"
