import pytest


@pytest.fixture(autouse=True)
def legacy_contract_fixture(request, tmp_path, monkeypatch):
    """Frozen compatibility tests use historical data, never the production food table."""
    if request.path.name not in {"test_nutrition_edge_cases.py", "test_nutrition_rules.py"}:
        return
    import csv
    import json
    from pathlib import Path
    from fitplate.nutrition import calculator
    rows = json.loads((Path(__file__).parent / "fixtures/legacy_foods.json").read_text(encoding="utf-8"))
    path = tmp_path / "compatibility.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    database = calculator.FoodDatabase(path)
    monkeypatch.setattr(calculator, "DEFAULT_DB", database)
    monkeypatch.setattr(request.module, "DEFAULT_DB", database, raising=False)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("FITPLATE_DATA_DIR", str(tmp_path))
    from fitplate import visitors
    monkeypatch.setattr(visitors,'ensure_visitor',lambda:None)
    token=visitors._identity.set(None)
    yield
    visitors._identity.reset(token)


@pytest.fixture(autouse=True)
def offline_agent(monkeypatch):
    from fitplate import agent
    from fitplate.domain import fresh_draft, update_draft

    def respond(text, draft=None, **kwargs):
        updated, _ = update_draft(draft or fresh_draft(), text)
        return {'intent': 'meal', 'reply': 'Please review your draft.', 'draft': updated, 'usage': []}

    monkeypatch.setattr(agent, 'respond', respond)

