import sqlite3
import pytest
from pathlib import Path
from datetime import date, timedelta
from scripts.tracker import init_db, get_db, get_goal, get_valid_meal_types, validate_meal_type

@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_health_data.db"
    init_db(db_file)
    return db_file

def test_database_init(temp_db):
    conn = get_db(temp_db)
    # Check if all tables exist
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = [t['name'] for t in tables]
    
    assert "entries" in table_names
    assert "daily_goal" in table_names
    assert "weight_log" in table_names
    assert "body_measurements" in table_names
    assert "day_notes" in table_names
    assert "meal_types" in table_names
    
    # Check if 'completed' column exists in day_notes
    columns = conn.execute("PRAGMA table_info(day_notes)").fetchall()
    col_names = [c['name'] for c in columns]
    assert "completed" in col_names
    
    conn.close()

def test_meal_types_seeding(temp_db):
    valid_meals = get_valid_meal_types(temp_db)
    assert "breakfast" in valid_meals
    assert "lunch" in valid_meals
    assert "dinner" in valid_meals
    assert "snack" in valid_meals

def test_goal_setting_calorie_only(temp_db):
    conn = get_db(temp_db)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO daily_goal (id, calorie_goal, protein_goal) VALUES (1, 2000, NULL)")
    conn.commit()
    conn.close()
    
    cal, p = get_goal(temp_db)
    assert cal == 2000
    assert p is None

def test_goal_setting_with_protein(temp_db):
    conn = get_db(temp_db)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO daily_goal (id, calorie_goal, protein_goal) VALUES (1, 1800, 120.5)")
    conn.commit()
    conn.close()
    
    cal, p = get_goal(temp_db)
    assert cal == 1800
    assert p == 120.5
