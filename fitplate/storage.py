"""Single-user local persistence for the interface preview."""

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from fitplate.nutrition.service import enrich_meal


def connect():
    from fitplate.visitors import workspace_directory
    directory = workspace_directory()
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(directory / "fitplate.sqlite3", timeout=10)
    connection.execute("CREATE TABLE IF NOT EXISTS meals (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL)")
    connection.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    return connection


def save_meal(meal):
    meal = enrich_meal(meal)
    with connect() as db:
        db.execute("INSERT INTO meals VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (meal["id"], json.dumps(meal, allow_nan=False), datetime.now(timezone.utc).isoformat()))


def list_meals():
    with connect() as db:
        rows = db.execute("SELECT payload FROM meals ORDER BY created_at DESC").fetchall()
    return [json.loads(row[0]) for row in rows]


def delete_meal(meal_id):
    with connect() as db:
        db.execute("DELETE FROM meals WHERE id = ?", (meal_id,))


def read_settings():
    with connect() as db:
        row = db.execute("SELECT payload FROM settings WHERE key = 'profile'").fetchone()
    return json.loads(row[0]) if row else {"name": "", "focus": "Build consistent habits", "preferences": "", "allergies": "", "energy": None, "protein": None, "carbs": None, "fat": None}


def save_settings(profile):
    with connect() as db:
        db.execute("INSERT INTO settings VALUES ('profile', ?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload", (json.dumps(profile),))


def read_language():
    with connect() as db:
        row=db.execute("SELECT payload FROM settings WHERE key='ui_language'").fetchone()
    try:
        value=json.loads(row[0]) if row else 'en'
    except (TypeError,ValueError):
        value='en'
    return value if value in ('en','zh-Hans','zh-Hant') else 'en'


def save_language(value):
    if value not in ('en','zh-Hans','zh-Hant'):
        raise ValueError('Unsupported interface language')
    with connect() as db:
        db.execute("INSERT INTO settings VALUES ('ui_language',?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",(json.dumps(value),))


def read_body_profile():
    from fitplate.coaching import validate_profile
    with connect() as db:
        row=db.execute("SELECT payload FROM settings WHERE key='body_training'").fetchone()
    return validate_profile(json.loads(row[0]) if row else {})


def save_body_profile(value):
    from fitplate.coaching import validate_profile
    value=validate_profile(value)
    with connect() as db:
        db.execute("INSERT INTO settings VALUES ('body_training',?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload",(json.dumps(value,allow_nan=False),))

