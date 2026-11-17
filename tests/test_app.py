from pathlib import Path

from streamlit.testing.v1 import AppTest

from fitplate.storage import list_meals

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception


def test_pages_render_and_targets_save():
    app = AppTest.from_file(APP, default_timeout=20).run()
    assert not app.exception
    click(app, "Meal records")
    click(app, "Goals & insights")
    next(field for field in app.number_input if field.label == "Protein target (g)").set_value(120)
    click(app, "Save targets")
    click(app, "Conversation")


def test_goals_tolerates_previous_summary_shape(monkeypatch):
    from fitplate.nutrition import service

    def previous_summary(meals, day):
        return {"totals": dict.fromkeys(("energy", "protein", "carbs", "fat")),
                "meal_count": 0, "incomplete_meals": 0, "computed_items": 0}

    monkeypatch.setattr(service, "daily_summary", previous_summary)
    app = AppTest.from_file(APP, default_timeout=20).run()
    click(app, "Goals & insights")
    assert not app.exception
    intake_metrics=[metric for metric in app.metric if metric.label in ('Energy','Protein','Carbs','Fat')]
    assert len(intake_metrics) == 4
    assert all(metric.value == "—" for metric in intake_metrics)


def test_confirmation_flow_requires_portions_and_saves_once():
    app = AppTest.from_file(APP, default_timeout=20).run()
    click(app, "Try a lunch example")
    assert list_meals() == []
    click(app, "Save meal")
    assert app.error
    for field, value in zip([field for field in app.number_input if field.label.startswith("Portion")], (150, 120, 80)):
        field.set_value(value)
    next(field for field in app.checkbox if field.label == "I reviewed the estimated portions and recipe assumptions").check()
    click(app, "Save meal")
    assert len(list_meals()) == 1
    click(app, "Meal records")
    click(app, "Edit meal")
    next(field for field in app.number_input if field.label == "Portion 1").set_value(125)
    next(field for field in app.checkbox if field.label == "I reviewed the estimated portions and recipe assumptions").check()
    click(app, "Save meal")
    assert len(list_meals()) == 1
    assert list_meals()[0]["items"][0]["quantity"] == 125


def test_custom_food_and_cancel():
    app = AppTest.from_file(APP, default_timeout=20).run()
    click(app, "Add food manually")
    next(field for field in app.text_input if field.label == "Food name 1").set_value("Lentil soup")
    next(field for field in app.number_input if field.label == "Portion 1").set_value(250)
    click(app, "Update draft")
    click(app, "Discard draft")
    assert list_meals() == []


def test_mobile_navigation_controls_the_same_page():
    app = AppTest.from_file(APP, default_timeout=20).run()
    next(field for field in app.selectbox if field.label == "Navigate").select("Goals").run()
    assert not app.exception
    assert any(button.label == "Save targets" for button in app.button)


def test_failed_ai_call_preserves_the_editable_draft(monkeypatch):
    from copy import deepcopy
    from fitplate import agent
    from fitplate.model_client import ServiceError

    app = AppTest.from_file(APP, default_timeout=20).run()
    click(app, "Try a lunch example")
    snapshot = deepcopy(app.session_state['draft'])

    def fail(*args, **kwargs):
        raise ServiceError('The AI service is temporarily unavailable.')

    monkeypatch.setattr(agent, 'respond', fail)
    app.chat_input[0].set_value('Make the chicken 200 g').run()
    assert not app.exception
    assert app.session_state['draft'] == snapshot
    assert list_meals() == []
    assert app.error

