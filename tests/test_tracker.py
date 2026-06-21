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
    
    cal, p, h = get_goal(temp_db)
    assert cal == 2000
    assert p is None

def test_goal_setting_with_protein(temp_db):
    conn = get_db(temp_db)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO daily_goal (id, calorie_goal, protein_goal) VALUES (1, 1800, 120.5)")
    conn.commit()
    conn.close()
    
    cal, p, h = get_goal(temp_db)
    assert cal == 1800
    assert p == 120.5

def test_harmonized_cli_feedback(temp_db, capsys):
    import argparse
    from scripts.tracker import cmd_add, cmd_update, cmd_delete
    
    # Set goal first
    conn = get_db(temp_db)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO daily_goal (id, calorie_goal, protein_goal) VALUES (1, 1800, 120)")
    conn.commit()
    conn.close()
    
    # Add first entry
    add_args = argparse.Namespace(
        database=str(temp_db),
        food_name="Breakfast",
        calories=350,
        protein=20.0,
        carbs=30.0,
        fat=10.0,
        meal="breakfast",
        date="2026-06-15"
    )
    cmd_add(add_args)
    captured = capsys.readouterr()
    assert "Added Entry 1: +350 (350/1800)\n" in captured.out
    
    # Add second entry
    add_args2 = argparse.Namespace(
        database=str(temp_db),
        food_name="Lunch",
        calories=600,
        protein=30.0,
        carbs=50.0,
        fat=15.0,
        meal="lunch",
        date="2026-06-15"
    )
    cmd_add(add_args2)
    captured = capsys.readouterr()
    assert "Added Entry 2: +600 (950/1800)\n" in captured.out
    
    # Update first entry
    update_args = argparse.Namespace(
        database=str(temp_db),
        id=1,
        name=None,
        cal=400,
        p=None,
        c=None,
        f=None,
        meal=None
    )
    cmd_update(update_args)
    captured = capsys.readouterr()
    assert "Changed Entry 1: 350->400 (1000/1800)\n" in captured.out
    
    # Delete first entry
    delete_args = argparse.Namespace(
        database=str(temp_db),
        id=1
    )
    cmd_delete(delete_args)
    captured = capsys.readouterr()
    assert "Deleted Entry 1: -400 (600/1800)\n" in captured.out


def test_search_command(temp_db, capsys):
    import argparse
    from scripts.tracker import cmd_add, cmd_search
    
    # 1. Add some entries for search testing
    # Entry 1: Oatmeal (logged 2x)
    add_args1 = argparse.Namespace(
        database=str(temp_db),
        food_name="Oatmeal with blueberries",
        calories=350,
        protein=12.0,
        carbs=50.0,
        fat=5.0,
        meal="breakfast",
        date="2026-06-14"
    )
    cmd_add(add_args1)
    
    add_args2 = argparse.Namespace(
        database=str(temp_db),
        food_name="Oatmeal with blueberries",
        calories=350,
        protein=12.0,
        carbs=50.0,
        fat=5.0,
        meal="breakfast",
        date="2026-06-15"
    )
    cmd_add(add_args2)
    
    # Entry 2: Chicken Salad (logged 1x)
    add_args3 = argparse.Namespace(
        database=str(temp_db),
        food_name="Grilled chicken salad",
        calories=450,
        protein=40.0,
        carbs=10.0,
        fat=15.0,
        meal="lunch",
        date="2026-06-15"
    )
    cmd_add(add_args3)
    
    # Clear capture
    capsys.readouterr()
    
    # 2. Test exact/substring search
    search_args_sub = argparse.Namespace(
        database=str(temp_db),
        query="oat",
        limit=5
    )
    cmd_search(search_args_sub)
    captured = capsys.readouterr()
    assert "Found 1 similar registered food(s):" in captured.out
    assert "Oatmeal with blueberries (350 kcal) - breakfast" in captured.out
    assert "Logged 2x (last used: 2026-06-15)" in captured.out
    assert "Log command: python scripts/tracker.py add \"Oatmeal with blueberries\" 350 12.0 50.0 5.0 --meal breakfast" in captured.out

    # 3. Test fuzzy search (e.g. typing "otmel")
    search_args_fuzzy = argparse.Namespace(
        database=str(temp_db),
        query="otmel",
        limit=5
    )
    cmd_search(search_args_fuzzy)
    captured = capsys.readouterr()
    assert "Found 1 similar registered food(s):" in captured.out
    assert "Oatmeal with blueberries (350 kcal) - breakfast" in captured.out

    # 4. Test no results found
    search_args_none = argparse.Namespace(
        database=str(temp_db),
        query="pizza",
        limit=5
    )
    cmd_search(search_args_none)
    captured = capsys.readouterr()
    assert "No similar registered foods found for 'pizza'" in captured.out


def test_stats_today(temp_db, capsys):
    import argparse
    from scripts.tracker import cmd_add, cmd_goal, cmd_weight, cmd_waist, cmd_stats_day, cmd_stats_week, cmd_stats_trend, cmd_stats_weight, cmd_stats_waist

    # 1. Set goal
    goal_args = argparse.Namespace(
        database=str(temp_db),
        calories=1800,
        protein=100.0,
        height=180.0
    )
    cmd_goal(goal_args)

    # 2. Add some entries
    # Monday 2026-06-15
    cmd_add(argparse.Namespace(
        database=str(temp_db), food_name="Egg", calories=100, protein=10.0, carbs=1.0, fat=8.0, meal="breakfast", date="2026-06-15", today=None
    ))
    # Tuesday 2026-06-16
    cmd_add(argparse.Namespace(
        database=str(temp_db), food_name="Chicken", calories=500, protein=50.0, carbs=0.0, fat=10.0, meal="lunch", date="2026-06-16", today=None
    ))
    # Wednesday 2026-06-17
    cmd_add(argparse.Namespace(
        database=str(temp_db), food_name="Fish", calories=400, protein=40.0, carbs=2.0, fat=12.0, meal="dinner", date="2026-06-17", today=None
    ))
    # Thursday 2026-06-18
    cmd_add(argparse.Namespace(
        database=str(temp_db), food_name="Steak", calories=800, protein=60.0, carbs=0.0, fat=40.0, meal="dinner", date="2026-06-18", today=None
    ))

    # Log weights
    cmd_weight(argparse.Namespace(database=str(temp_db), kg=80.0, date="2026-06-15", today=None))
    cmd_weight(argparse.Namespace(database=str(temp_db), kg=79.5, date="2026-06-17", today=None))
    cmd_weight(argparse.Namespace(database=str(temp_db), kg=79.0, date="2026-06-19", today=None))

    # Log waists
    cmd_waist(argparse.Namespace(database=str(temp_db), cm=90.0, date="2026-06-15", today=None))
    cmd_waist(argparse.Namespace(database=str(temp_db), cm=89.5, date="2026-06-17", today=None))
    cmd_waist(argparse.Namespace(database=str(temp_db), cm=89.0, date="2026-06-19", today=None))

    # Clear capture
    capsys.readouterr()

    # 3. Test stats day --today 2026-06-16
    day_args = argparse.Namespace(database=str(temp_db), date=None, today="2026-06-16")
    cmd_stats_day(day_args)
    captured = capsys.readouterr()
    assert "DAY BREAKDOWN: 2026-06-16" in captured.out
    assert "Chicken" in captured.out

    # 4. Test stats week --today 2026-06-17 (Wednesday)
    # The week containing June 17 has Monday=June 15, Sunday=June 21.
    # It should only show logs up to June 17. June 18 (Steak) should be ignored.
    week_args = argparse.Namespace(database=str(temp_db), date=None, weeks=1, compact=False, today="2026-06-17")
    cmd_stats_week(week_args)
    captured = capsys.readouterr()
    # Wednesday 2026-06-17 should be visible, Thursday 2026-06-18 should be UNLOGGED
    assert "Wednesday  | 2026-06-17 | 400" in captured.out
    assert "Thursday   | 2026-06-18 | -" in captured.out
    # Total should only sum up to Wednesday (100+500+400 = 1000)
    assert "Total: 1000 / 12600 kcal" in captured.out

    # 5. Test stats trend --today 2026-06-17
    trend_args = argparse.Namespace(database=str(temp_db), days=30, today="2026-06-17")
    cmd_stats_trend(trend_args)
    captured = capsys.readouterr()
    # Average of last 7 days including up to June 17:
    # Entries: June 15 (100 kcal), June 16 (500 kcal), June 17 (400 kcal)
    # Total calories = 1000. Under rolling trend, the rolling average for June 17 should be calculated.
    assert "Last  7 Days:" in captured.out

    # 6. Test stats weight --today 2026-06-17
    weight_args = argparse.Namespace(database=str(temp_db), days=30, entries=None, today="2026-06-17")
    cmd_stats_weight(weight_args)
    captured = capsys.readouterr()
    # Weight on June 19 (79.0) should NOT be shown
    assert "2026-06-17: 79.5 kg" in captured.out
    assert "2026-06-19" not in captured.out

    # 7. Test stats waist --today 2026-06-17
    waist_args = argparse.Namespace(database=str(temp_db), days=30, entries=None, today="2026-06-17")
    cmd_stats_waist(waist_args)
    captured = capsys.readouterr()
    # Waist on June 19 (89.0) should NOT be shown
    assert "2026-06-17: 89.5 cm" in captured.out
    assert "2026-06-19" not in captured.out


def test_stats_weight_and_waist_entries(temp_db, capsys):
    import argparse
    from scripts.tracker import cmd_weight, cmd_waist, cmd_stats_weight, cmd_stats_waist, entries_type
    import pytest

    # Log 6 weights/waists
    dates = ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14", "2026-06-15"]
    weights = [80.0, 79.8, 79.5, 79.6, 79.2, 79.0]
    for d, w in zip(dates, weights):
        cmd_weight(argparse.Namespace(database=str(temp_db), kg=w, date=d, today=None))
        cmd_waist(argparse.Namespace(database=str(temp_db), cm=90.0 - (80.0 - w), date=d, today=None))

    # Clear capture
    capsys.readouterr()

    # Case 1: Default (neither entries nor days specified -> entries=5)
    args_def = argparse.Namespace(database=str(temp_db), entries=None, days=None, today="2026-06-15")
    cmd_stats_weight(args_def)
    out = capsys.readouterr().out
    assert "WEIGHT TRENDS (LAST 5 ENTRIES)" in out
    assert "2026-06-15: 79.0 kg" in out
    assert "2026-06-11: 79.8 kg" in out
    assert "2026-06-10" not in out # The 6th entry should be excluded

    # Case 2: Explicit entries (-N 3)
    args_n3 = argparse.Namespace(database=str(temp_db), entries=3, days=None, today="2026-06-15")
    cmd_stats_weight(args_n3)
    out = capsys.readouterr().out
    assert "WEIGHT TRENDS (LAST 3 ENTRIES)" in out
    assert "2026-06-15: 79.0 kg" in out
    assert "2026-06-13: 79.6 kg" in out
    assert "2026-06-12" not in out

    # Case 3: Explicit entries "all" (-N all)
    args_all = argparse.Namespace(database=str(temp_db), entries="all", days=None, today="2026-06-15")
    cmd_stats_weight(args_all)
    out = capsys.readouterr().out
    assert "WEIGHT TRENDS (ALL ENTRIES)" in out
    assert "2026-06-15: 79.0 kg" in out
    assert "2026-06-10: 80.0 kg" in out

    # Case 4: Only days specified (--days 3 -> should not limit entries count)
    args_days3 = argparse.Namespace(database=str(temp_db), entries=None, days=3, today="2026-06-15")
    cmd_stats_weight(args_days3)
    out = capsys.readouterr().out
    assert "WEIGHT TRENDS (LAST 3 DAYS)" in out
    assert "2026-06-15: 79.0 kg" in out
    assert "2026-06-12: 79.5 kg" in out
    assert "2026-06-11" not in out

    # Case 5: Both entries and days specified (-N 2 --days 5)
    args_both = argparse.Namespace(database=str(temp_db), entries=2, days=5, today="2026-06-15")
    cmd_stats_weight(args_both)
    out = capsys.readouterr().out
    assert "WEIGHT TRENDS (LAST 2 ENTRIES OVER LAST 5 DAYS)" in out
    assert "2026-06-15: 79.0 kg" in out
    assert "2026-06-14: 79.2 kg" in out
    assert "2026-06-13" not in out

    # Case 6: Custom entries validator validation
    assert entries_type("all") == "all"
    assert entries_type("ALL") == "all"
    assert entries_type("5") == 5
    with pytest.raises(argparse.ArgumentTypeError):
        entries_type("0")
    with pytest.raises(argparse.ArgumentTypeError):
        entries_type("-1")
    with pytest.raises(argparse.ArgumentTypeError):
        entries_type("abc")

