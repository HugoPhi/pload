from pload.resource_plan import PlanSelection


def _route(method):
    return {
        "method": method, "location": "/" + method, "status": "ready",
        "cost": [0], "estimated_seconds": 1,
    }


def test_route_selection_supports_navigation_state_undo_and_reset():
    plan = {
        "python": {"status": "ready"}, "ready": True,
        "packages": [{
            "name": "demo", "version": "1", "selected": _route("cache"),
            "alternatives": [_route("environment-copy"), _route("index-exact")],
        }],
    }
    selection = PlanSelection(plan)

    selection.select(0, 2)
    assert plan["packages"][0]["selected"]["method"] == "index-exact"
    assert [item["method"] for item in plan["packages"][0]["alternatives"]] == [
        "cache", "environment-copy",
    ]
    assert selection.undo() is True
    assert plan["packages"][0]["selected"]["method"] == "cache"
    assert selection.undo() is False

    selection.select(0, 1)
    selection.reset()
    assert plan["packages"][0]["selected"]["method"] == "cache"
    assert selection.undo() is True
    assert plan["packages"][0]["selected"]["method"] == "environment-copy"
