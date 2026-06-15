#!/usr/bin/env python3
"""
Consolidated Calorie Tracker CLI for local calorie and weight tracking.
"""

import sqlite3
import sys
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path

# Height from USER.md (Patrik's baseline is 180cm)
HEIGHT_CM = 180.0
HEIGHT_M = HEIGHT_CM / 100.0

def get_db(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path):
    conn = get_db(db_path)
    c = conn.cursor()
    
    # Food entries
    c.execute('''
        CREATE TABLE IF NOT EXISTS entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            food_name TEXT NOT NULL,
            calories INTEGER NOT NULL,
            protein REAL,
            carbs REAL,
            fat REAL,
            meal_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Daily goals
    c.execute('''
        CREATE TABLE IF NOT EXISTS daily_goal (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            calorie_goal INTEGER NOT NULL,
            protein_goal REAL
        )
    ''')
    
    # Weight log (kg)
    c.execute('''
        CREATE TABLE IF NOT EXISTS weight_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            weight_kg REAL NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Body measurements (cm)
    c.execute('''
        CREATE TABLE IF NOT EXISTS body_measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            waist_cm REAL,
            hips_cm REAL,
            neck_cm REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Daily notes/annotations
    c.execute('''
        CREATE TABLE IF NOT EXISTS day_notes (
            date TEXT PRIMARY KEY,
            tracking_quality TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Dynamic meal types table
    c.execute('''
        CREATE TABLE IF NOT EXISTS meal_types (
            type TEXT PRIMARY KEY
        )
    ''')
    
    # Migration: Check if day_notes has 'completed' column
    c.execute("PRAGMA table_info(day_notes)")
    columns = [row['name'] for row in c.fetchall()]
    if 'completed' not in columns:
        c.execute("ALTER TABLE day_notes ADD COLUMN completed INTEGER DEFAULT 0")
        
    # Migration: Check if daily_goal has 'height_cm' column
    c.execute("PRAGMA table_info(daily_goal)")
    goal_columns = [row['name'] for row in c.fetchall()]
    if 'height_cm' not in goal_columns:
        c.execute("ALTER TABLE daily_goal ADD COLUMN height_cm REAL DEFAULT 180.0")
        
    # Seed default meal types if table is empty
    c.execute("SELECT COUNT(*) FROM meal_types")
    if c.fetchone()[0] == 0:
        default_meals = [
            ('breakfast',), ('lunch',), ('dinner',), ('snack',),
            ('fika',), ('drink',), ('dessert',), ('evening',), ('other',)
        ]
        c.executemany("INSERT INTO meal_types (type) VALUES (?)", default_meals)
        
    # Define SQL Views for stats calculations
    c.execute("DROP VIEW IF EXISTS v_daily_summary")
    c.execute('''
        CREATE VIEW v_daily_summary AS
        SELECT 
            d.date,
            COALESCE(e.total_cal, 0) as total_cal,
            COALESCE(e.total_p, 0) as total_p,
            COALESCE(e.entry_count, 0) as entry_count,
            n.tracking_quality as completeness,
            COALESCE(n.completed, 0) as completed
        FROM (
            SELECT date FROM entries
            UNION
            SELECT date FROM day_notes
        ) d
        LEFT JOIN (
            SELECT 
                date,
                SUM(calories) as total_cal,
                SUM(protein) as total_p,
                COUNT(*) as entry_count
            FROM entries
            GROUP BY date
        ) e ON d.date = e.date
        LEFT JOIN day_notes n ON d.date = n.date
    ''')
    
    c.execute("DROP VIEW IF EXISTS v_daily_rolling_trends")
    c.execute('''
        CREATE VIEW v_daily_rolling_trends AS
        SELECT 
            date,
            total_cal,
            total_p,
            AVG(total_cal) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as rolling_7_cal,
            AVG(total_p) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) as rolling_7_p,
            AVG(total_cal) OVER (ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) as rolling_30_cal,
            AVG(total_p) OVER (ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) as rolling_30_p,
            AVG(total_cal) OVER (ORDER BY date ROWS BETWEEN 89 PRECEDING AND CURRENT ROW) as rolling_90_cal,
            AVG(total_p) OVER (ORDER BY date ROWS BETWEEN 89 PRECEDING AND CURRENT ROW) as rolling_90_p
        FROM v_daily_summary
    ''')
    
    # BMI and WHtR resolved dynamically from the daily_goal table
    c.execute("DROP VIEW IF EXISTS v_weight_summary")
    c.execute('''
        CREATE VIEW v_weight_summary AS
        SELECT 
            date,
            weight_kg,
            ROUND(weight_kg / ( ( (SELECT COALESCE(height_cm, 180.0) FROM daily_goal WHERE id = 1) / 100.0 ) * ( (SELECT COALESCE(height_cm, 180.0) FROM daily_goal WHERE id = 1) / 100.0 ) ), 1) as bmi,
            ROUND(weight_kg - LAG(weight_kg) OVER (ORDER BY date), 1) as change_kg
        FROM weight_log
    ''')
    
    c.execute("DROP VIEW IF EXISTS v_waist_summary")
    c.execute('''
        CREATE VIEW v_waist_summary AS
        SELECT 
            date,
            waist_cm,
            ROUND(waist_cm / (SELECT COALESCE(height_cm, 180.0) FROM daily_goal WHERE id = 1), 2) as whtr,
            ROUND(waist_cm - LAG(waist_cm) OVER (ORDER BY date), 1) as change_cm
        FROM body_measurements
        WHERE waist_cm IS NOT NULL
    ''')
    
    conn.commit()
    conn.close()

def get_valid_meal_types(db_path):
    conn = get_db(db_path)
    rows = conn.execute("SELECT type FROM meal_types").fetchall()
    conn.close()
    return {row['type'] for row in rows}

def validate_meal_type(db_path, meal_type):
    valid_types = get_valid_meal_types(db_path)
    if meal_type not in valid_types:
        print(f"Error: Invalid meal type '{meal_type}'. Valid types: {', '.join(sorted(valid_types))}")
        sys.exit(1)

def get_goal(db_path):
    conn = get_db(db_path)
    row = conn.execute("SELECT calorie_goal, protein_goal, height_cm FROM daily_goal WHERE id = 1").fetchone()
    conn.close()
    if row:
        return row['calorie_goal'], row['protein_goal'], row['height_cm']
    return None, None, 180.0

# ----------------- Configuration & Logging -----------------

def cmd_goal(args):
    conn = get_db(args.database)
    c = conn.cursor()
    
    # Keep existing height if not provided
    row = c.execute("SELECT height_cm FROM daily_goal WHERE id = 1").fetchone()
    existing_height = row['height_cm'] if row else 180.0
    height = args.height if args.height is not None else existing_height
    
    c.execute('''
        INSERT OR REPLACE INTO daily_goal (id, calorie_goal, protein_goal, height_cm)
        VALUES (1, ?, ?, ?)
    ''', (args.calories, args.protein, height))
    conn.commit()
    conn.close()
    
    p_str = f" | {args.protein}g protein" if args.protein is not None else ""
    print(f"Daily goal set: {args.calories} kcal{p_str} | Height: {height} cm")

def cmd_add(args):
    validate_meal_type(args.database, args.meal)
    entry_date = args.date or date.today().isoformat()
    
    conn = get_db(args.database)
    c = conn.cursor()
    c.execute('''
        INSERT INTO entries (date, food_name, calories, protein, carbs, fat, meal_type)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (entry_date, args.food_name, args.calories, args.protein, args.carbs, args.fat, args.meal))
    entry_id = c.lastrowid
    conn.commit()
    
    # Fetch today's totals from view
    totals = c.execute('SELECT total_cal FROM v_daily_summary WHERE date = ?', (entry_date,)).fetchone()
    conn.close()
    
    total_cal = totals['total_cal'] if totals else args.calories
    
    goal_cal, _, _ = get_goal(args.database)
    goal_str = f"/{goal_cal}" if goal_cal else ""
    
    # Print harmonized Added Entry output
    print(f"Added Entry {entry_id}: +{args.calories} ({total_cal}{goal_str})")

def cmd_list(args):
    entry_date = args.date or date.today().isoformat()
    conn = get_db(args.database)
    rows = conn.execute('''
        SELECT id, strftime('%H:%M', created_at) as t, meal_type, food_name, calories, protein
        FROM entries WHERE date = ? ORDER BY created_at
    ''', (entry_date,)).fetchall()
    conn.close()
    
    if not rows:
        print(f"No entries found for {entry_date}")
        return
        
    print(f"Entries for {entry_date}:")
    for r in rows:
        time_str = r['t'] if r['t'] else "??:??"
        p_str = f" | {r['protein']:.1f}g P" if r['protein'] is not None else ""
        print(f"  [{r['id']}] {time_str} [{r['meal_type']}] {r['food_name']}: {r['calories']} kcal{p_str}")

def cmd_update(args):
    conn = get_db(args.database)
    c = conn.cursor()
    
    row = c.execute("SELECT * FROM entries WHERE id = ?", (args.id,)).fetchone()
    if not row:
        print(f"Error: Entry {args.id} not found.")
        conn.close()
        sys.exit(1)
        
    # Use existing values if flags not provided
    name = args.name if args.name is not None else row['food_name']
    calories = args.cal if args.cal is not None else row['calories']
    protein = args.p if args.p is not None else row['protein']
    carbs = args.c if args.c is not None else row['carbs']
    fat = args.f if args.f is not None else row['fat']
    meal_type = args.meal if args.meal is not None else row['meal_type']
    
    if args.meal is not None:
        validate_meal_type(args.database, meal_type)
        
    c.execute('''
        UPDATE entries
        SET food_name = ?, calories = ?, protein = ?, carbs = ?, fat = ?, meal_type = ?
        WHERE id = ?
    ''', (name, calories, protein, carbs, fat, meal_type, args.id))
    conn.commit()
    
    # Fetch date totals from view
    entry_date = row['date']
    totals = c.execute('SELECT total_cal FROM v_daily_summary WHERE date = ?', (entry_date,)).fetchone()
    conn.close()
    
    total_cal = totals['total_cal'] if totals else 0
    goal_cal, _, _ = get_goal(args.database)
    goal_str = f"/{goal_cal}" if goal_cal else ""
    
    # Print harmonized Changed Entry output
    print(f"Changed Entry {args.id}: {row['calories']}->{calories} ({total_cal}{goal_str})")

def cmd_delete(args):
    conn = get_db(args.database)
    c = conn.cursor()
    row = c.execute("SELECT date, calories FROM entries WHERE id = ?", (args.id,)).fetchone()
    if not row:
        print(f"Error: Entry {args.id} not found.")
        conn.close()
        sys.exit(1)
        
    c.execute("DELETE FROM entries WHERE id = ?", (args.id,))
    conn.commit()
    
    # Fetch date totals from view
    entry_date = row['date']
    totals = c.execute('SELECT total_cal FROM v_daily_summary WHERE date = ?', (entry_date,)).fetchone()
    conn.close()
    
    total_cal = totals['total_cal'] if totals else 0
    goal_cal, _, _ = get_goal(args.database)
    goal_str = f"/{goal_cal}" if goal_cal else ""
    
    # Print harmonized Deleted Entry output
    print(f"Deleted Entry {args.id}: -{row['calories']} ({total_cal}{goal_str})")

def cmd_complete(args):
    conn = get_db(args.database)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO day_notes (date, tracking_quality, completed)
        VALUES (?, ?, 1)
    ''', (args.date, args.completeness))
    conn.commit()
    conn.close()
    print(f"Day {args.date} marked as completed (completeness: {args.completeness})")

def cmd_check_complete(args):
    target_date = args.date or date.today().isoformat()
    conn = get_db(args.database)
    row = conn.execute("SELECT completeness, completed FROM v_daily_summary WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    
    if row and row['completeness'] == 'full' and row['completed'] == 1:
        print(f"Day {target_date} is fully complete.")
        sys.exit(0)
    else:
        q = row['completeness'] if row else "unlogged"
        print(f"Day {target_date} is NOT fully complete (status: {q}).")
        sys.exit(1)

def cmd_weight(args):
    target_date = args.date or date.today().isoformat()
    conn = get_db(args.database)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO weight_log (date, weight_kg)
        VALUES (?, ?)
    ''', (target_date, args.kg))
    conn.commit()
    conn.close()
    print(f"Weight logged: {args.kg} kg on {target_date}")

def cmd_waist(args):
    target_date = args.date or date.today().isoformat()
    conn = get_db(args.database)
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO body_measurements (date, waist_cm)
        VALUES (?, ?)
    ''', (target_date, args.cm))
    conn.commit()
    conn.close()
    print(f"Waist logged: {args.cm} cm on {target_date}")

# ----------------- Statistics & Reports -----------------

def cmd_stats_day(args):
    target_date = args.date or date.today().isoformat()
    conn = get_db(args.database)
    goal_cal, goal_p, _ = get_goal(args.database)
    
    entries = conn.execute('''
        SELECT id, strftime('%H:%M', created_at) as t, meal_type, food_name, calories, protein
        FROM entries WHERE date = ? ORDER BY created_at
    ''', (target_date,)).fetchall()
    
    # Query aggregated daily totals from view
    totals = conn.execute('''
        SELECT total_cal, total_p, completeness
        FROM v_daily_summary WHERE date = ?
    ''', (target_date,)).fetchone()
    
    note = conn.execute("SELECT notes FROM day_notes WHERE date = ?", (target_date,)).fetchone()
    conn.close()
    
    print("-" * 60)
    print(f"DAY BREAKDOWN: {target_date}")
    if totals and totals['completeness']:
        notes_str = f" | Note: {note['notes']}" if (note and note['notes']) else ""
        print(f"Status: {totals['completeness'].upper()}{notes_str}")
    print("-" * 60)
    
    if not entries:
        print("No entries logged for this day.")
        return
        
    for e in entries:
        time_str = e['t'] if e['t'] else "??:??"
        p_str = f", {e['protein']:.0f}g P" if e['protein'] is not None else ""
        print(f"  [{e['id']}] {time_str} [{e['meal_type']}] {e['food_name']}: {e['calories']} kcal{p_str}")
        
    print("-" * 60)
    total_cal = totals['total_cal'] if totals else 0
    total_p = totals['total_p'] if totals else 0
    
    if goal_cal:
        diff = total_cal - goal_cal
        sign = "+" if diff >= 0 else ""
        print(f"Total: {total_cal} / {goal_cal} kcal ({sign}{diff} kcal) | {total_p:.1f}g Protein")
    else:
        print(f"Total: {total_cal} kcal | {total_p:.1f}g Protein")
    if goal_p:
        diff_p = total_p - goal_p
        sign_p = "+" if diff_p >= 0 else ""
        print(f"Protein: {total_p:.1f} / {goal_p} g ({sign_p}{diff_p:.1f} g)")
    print("-" * 60)

def cmd_stats_week(args):
    target_date_str = args.date or date.today().isoformat()
    target_date = date.fromisoformat(target_date_str)
    
    # Calculate Monday and Sunday of target week
    monday = target_date - timedelta(days=target_date.weekday())
    sunday = monday + timedelta(days=6)
    
    conn = get_db(args.database)
    goal_cal, goal_p, _ = get_goal(args.database)
    
    # Build list of weeks to display
    weeks_to_process = []
    for w_idx in range(args.weeks - 1, -1, -1):
        w_mon = monday - timedelta(weeks=w_idx)
        w_sun = w_mon + timedelta(days=6)
        weeks_to_process.append((w_mon, w_sun))
        
    for w_mon, w_sun in weeks_to_process:
        # Load daily summaries for the 7 days of the week in a single query from view
        summary_rows = conn.execute('''
            SELECT date, total_cal, total_p, completeness, completed, entry_count
            FROM v_daily_summary
            WHERE date BETWEEN ? AND ?
            ORDER BY date
        ''', (w_mon.isoformat(), w_sun.isoformat())).fetchall()
        
        summary_map = {r['date']: r for r in summary_rows}
        
        days = []
        for i in range(7):
            d = w_mon + timedelta(days=i)
            d_str = d.isoformat()
            
            row = summary_map.get(d_str)
            
            kcal = row['total_cal'] if row else 0
            protein = row['total_p'] if row else 0
            entry_count = row['entry_count'] if row else 0
            completed_val = row['completed'] if row else 0
            
            status = "unlogged"
            if row and row['completeness']:
                status = row['completeness']
            elif entry_count > 0:
                status = "partial"
                
            days.append({
                "date": d,
                "date_str": d_str,
                "day_name": d.strftime("%A"),
                "kcal": kcal,
                "protein": protein,
                "completeness": status,
                "completed": completed_val,
                "has_data": entry_count > 0
            })
            
        # Calculate Averages
        completed_days = [d for d in days if d['completed'] == 1]
        completed_avg = sum(d['kcal'] for d in completed_days) / len(completed_days) if completed_days else 0
        
        today_date = date.today()
        
        mon_to_yesterday = [d for d in days if d['date'] < today_date]
        yesterday_avg = sum(d['kcal'] for d in mon_to_yesterday) / len(mon_to_yesterday) if mon_to_yesterday else 0
        
        mon_to_today = [d for d in days if d['date'] <= today_date]
        today_avg = sum(d['kcal'] for d in mon_to_today) / len(mon_to_today) if mon_to_today else 0
        
        # Budgets
        weekly_total = sum(d['kcal'] for d in days)
        weekly_target = goal_cal * 7 if goal_cal else 0
        
        # Calculate active elapsed days for average display
        if today_date > w_sun:
            elapsed_days = 7
        elif today_date < w_mon:
            elapsed_days = 0
        else:
            elapsed_days = (today_date - w_mon).days + 1
            
        avg_cal = weekly_total / elapsed_days if elapsed_days > 0 else 0
        
        # Starting Now: budget including today
        rem_days_now = [d for d in days if d['date'] >= today_date]
        days_left_now = len(rem_days_now)
        if goal_cal:
            logged_before_today = sum(d['kcal'] for d in days if d['date'] < today_date)
            remaining_target_now = weekly_target - logged_before_today - sum(d['kcal'] for d in days if d['date'] == today_date)
            budget_now = remaining_target_now / days_left_now if days_left_now > 0 else 0
        else:
            budget_now = 0
            
        # Starting Tomorrow: budget excluding today
        rem_days_tomorrow = [d for d in days if d['date'] > today_date]
        days_left_tomorrow = len(rem_days_tomorrow)
        if goal_cal and days_left_tomorrow > 0:
            logged_up_to_today = sum(d['kcal'] for d in days if d['date'] <= today_date)
            remaining_target_tomorrow = weekly_target - logged_up_to_today
            budget_tomorrow = remaining_target_tomorrow / days_left_tomorrow
        else:
            budget_tomorrow = None
            
        # Format budgets
        budg_today = f"{budget_now:.0f} kcal/d" if days_left_now > 0 else "Week over"
        budg_tom = f"{budget_tomorrow:.0f} kcal/d" if (budget_tomorrow is not None) else "Week over"
        
        # Display Stats
        if args.compact:
            diff_cal = weekly_total - weekly_target
            diff_sign = "+" if diff_cal >= 0 else ""
            
            if goal_cal:
                target_str = f"/{weekly_target}"
                diff_str = f" ({diff_sign}{diff_cal} kcal)"
                avg_str = f", daily average {avg_cal:.0f}/{goal_cal} kcal"
            else:
                target_str = ""
                diff_str = ""
                avg_str = f", daily average {avg_cal:.0f} kcal"
                
            print(f"Week {w_mon} to {w_sun}: Total {weekly_total}{target_str} kcal{diff_str}{avg_str}")
        else:
            print("\n" + "=" * 70)
            print(f"WEEK SUMMARY: {w_mon} to {w_sun}")
            print("=" * 70)
            diff_cal = weekly_total - weekly_target
            diff_sign = "+" if diff_cal >= 0 else ""
            
            if goal_cal:
                print(f"Total: {weekly_total} / {weekly_target} kcal ({diff_sign}{diff_cal} kcal)")
            else:
                print(f"Total: {weekly_total} kcal")
                
            print(f"Averages:")
            print(f"  Completed: {completed_avg:.0f} kcal ({len(completed_days)}d)")
            if mon_to_yesterday:
                print(f"  Mon-Yesterday: {yesterday_avg:.0f} kcal")
            print(f"  Mon-Today: {today_avg:.0f} kcal")
            print(f"Budgets:")
            print(f"  Today: {budg_today} | Tomorrow: {budg_tom}")
            
            # Print breakdown table
            print("-" * 70)
            print(f"{'Day':<10} | {'Date':<10} | {'Kcal':<6} | {'Protein':<8} | {'Target Diff':<11} | {'Completeness':<12}")
            print("-" * 70)
            for d in days:
                kcal_str = f"{d['kcal']}" if d['has_data'] or d['kcal'] > 0 else "-"
                p_str = f"{d['protein']:.0f}g" if (d['has_data'] or d['protein'] > 0) else "-"
                
                diff_str = "-"
                if goal_cal and (d['has_data'] or d['kcal'] > 0):
                    diff = d['kcal'] - goal_cal
                    diff_str = f"{'+' if diff >= 0 else ''}{diff}"
                    
                print(f"{d['day_name'][:10]:<10} | {d['date_str']:<10} | {kcal_str:<6} | {p_str:<8} | {diff_str:<11} | {d['completeness'].upper():<12}")
            print("=" * 70)
        
    conn.close()

def cmd_stats_trend(args):
    conn = get_db(args.database)
    
    print("-" * 60)
    print("MACRONUTRIENT TRENDS (ROLLING AVERAGES)")
    print("-" * 60)
    
    # Query rolling averages directly from v_daily_rolling_trends up to today
    row = conn.execute('''
        SELECT rolling_7_cal, rolling_7_p, 
               rolling_30_cal, rolling_30_p, 
               rolling_90_cal, rolling_90_p
        FROM v_daily_rolling_trends
        WHERE date <= date('now')
        ORDER BY date DESC LIMIT 1
    ''').fetchone()
    
    conn.close()
    
    if not row:
        print("No trend data available.")
        print("-" * 60)
        return
        
    for days, suffix in [(7, '7'), (30, '30'), (90, '90')]:
        cal = row[f'rolling_{suffix}_cal']
        p = row[f'rolling_{suffix}_p']
        
        cal_val = f"{cal:.0f} kcal" if cal is not None else "No data"
        p_val = f" | {p:.1f}g Protein" if p is not None else ""
        print(f"Last {days:2d} Days: {cal_val}{p_val}")
        
    print("-" * 60)

def cmd_stats_weight(args):
    conn = get_db(args.database)
    # Query directly from weight view
    rows = conn.execute('''
        SELECT date, weight_kg, bmi, change_kg FROM v_weight_summary
        WHERE date >= date('now', ?)
        ORDER BY date DESC
    ''', (f'-{args.days} days',)).fetchall()
    conn.close()
    
    print("-" * 60)
    print(f"WEIGHT TRENDS (LAST {args.days} DAYS)")
    print("-" * 60)
    
    if not rows:
        print("No weight logs found.")
        return
        
    for r in rows:
        ch_str = f" ({r['change_kg']:+.1f} kg)" if r['change_kg'] is not None else ""
        print(f"  {r['date']}: {r['weight_kg']:.1f} kg | BMI: {r['bmi']:.1f}{ch_str}")
        
    if len(rows) >= 2:
        change = rows[0]['weight_kg'] - rows[-1]['weight_kg']
        print("-" * 60)
        print(f"Total Change: {change:+.1f} kg (from {rows[-1]['weight_kg']:.1f} to {rows[0]['weight_kg']:.1f})")
    print("-" * 60)

def cmd_stats_waist(args):
    conn = get_db(args.database)
    # Query directly from waist view
    rows = conn.execute('''
        SELECT date, waist_cm, whtr, change_cm FROM v_waist_summary
        WHERE date >= date('now', ?)
        ORDER BY date DESC
    ''', (f'-{args.days} days',)).fetchall()
    conn.close()
    
    print("-" * 60)
    print(f"WAIST TRENDS (LAST {args.days} DAYS)")
    print("-" * 60)
    
    if not rows:
        print("No waist logs found.")
        return
        
    for r in rows:
        ch_str = f" ({r['change_cm']:+.1f} cm)" if r['change_cm'] is not None else ""
        print(f"  {r['date']}: {r['waist_cm']:.1f} cm | WHtR: {r['whtr']:.2f}{ch_str}")
        
    if len(rows) >= 2:
        change = rows[0]['waist_cm'] - rows[-1]['waist_cm']
        print("-" * 60)
        print(f"Total Change: {change:+.1f} cm (from {rows[-1]['waist_cm']:.1f} to {rows[0]['waist_cm']:.1f})")
    print("-" * 60)

# ----------------- CLI Main parsing -----------------

def main():
    parser = argparse.ArgumentParser(description="Consolidated Calorie Tracker CLI")
    parser.add_argument("--database", default="./health_data.db", help="Path to SQLite database file")
    
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # goal command
    p_goal = subparsers.add_parser("goal", help="Set daily calorie & protein goals")
    p_goal.add_argument("calories", type=int, help="Calorie goal (kcal)")
    p_goal.add_argument("protein", type=float, nargs="?", default=None, help="Protein goal (grams, optional)")
    p_goal.add_argument("--height", type=float, default=None, help="Height in cm (optional, defaults to keeping current or 180.0)")
    
    # add command
    p_add = subparsers.add_parser("add", help="Add a food entry")
    p_add.add_argument("food_name", help="Description of food consumed")
    p_add.add_argument("calories", type=int, help="Calories in entry (kcal)")
    p_add.add_argument("protein", type=float, nargs="?", default=None, help="Protein in grams")
    p_add.add_argument("carbs", type=float, nargs="?", default=None, help="Carbohydrates in grams")
    p_add.add_argument("fat", type=float, nargs="?", default=None, help="Fat in grams")
    p_add.add_argument("--meal", required=True, help="Meal type (breakfast, lunch, dinner, etc.)")
    p_add.add_argument("--date", help="Date YYYY-MM-DD (defaults to today)")
    
    # list command
    p_list = subparsers.add_parser("list", help="List food entries for a date")
    p_list.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD (defaults to today)")
    
    # update command
    p_upd = subparsers.add_parser("update", help="Update a food entry by ID")
    p_upd.add_argument("id", type=int, help="Entry ID to update")
    p_upd.add_argument("--name", help="New description")
    p_upd.add_argument("--cal", type=int, help="New calories")
    p_upd.add_argument("--p", type=float, help="New protein")
    p_upd.add_argument("--c", type=float, help="New carbs")
    p_upd.add_argument("--f", type=float, help="New fat")
    p_upd.add_argument("--meal", help="New meal type")
    
    # delete command
    p_del = subparsers.add_parser("delete", help="Delete a food entry by ID")
    p_del.add_argument("id", type=int, help="Entry ID to delete")
    
    # complete command
    p_comp = subparsers.add_parser("complete", help="Mark a day's tracking as completed")
    p_comp.add_argument("date", help="Date YYYY-MM-DD")
    p_comp.add_argument("--completeness", default="full", choices=["full", "partial", "minimal"], help="Completeness quality level")
    p_comp.add_argument("--notes", help="Optional daily notes")
    
    # check-complete command
    p_check = subparsers.add_parser("check-complete", help="Check day completeness status")
    p_check.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD")
    
    # weight command
    p_w = subparsers.add_parser("weight", help="Log body weight")
    p_w.add_argument("kg", type=float, help="Weight in kg")
    p_w.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD")
    
    # waist command
    p_wa = subparsers.add_parser("waist", help="Log waist circumference")
    p_wa.add_argument("cm", type=float, help="Waist circumference in cm")
    p_wa.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD")
    
    # stats command group
    p_stats = subparsers.add_parser("stats", help="Get statistics and reports")
    s_sub = p_stats.add_subparsers(dest="stats_command", required=True)
    
    # stats day
    s_day = s_sub.add_parser("day", help="Show daily breakdown")
    s_day.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD")
    
    # stats week
    s_week = s_sub.add_parser("week", help="Show weekly averages and breakdown")
    s_week.add_argument("date", nargs="?", default=None, help="Date YYYY-MM-DD")
    s_week.add_argument("--weeks", type=int, default=1, help="Number of weeks to show (default: 1)")
    s_week.add_argument("--compact", action="store_true", help="Print a single-line compact summary for each week")
    
    # stats trend
    s_trend = s_sub.add_parser("trend", help="Show macronutrient rolling averages")
    s_trend.add_argument("--days", type=int, default=30, help="Number of days to look back")
    
    # stats weight
    s_w = s_sub.add_parser("weight", help="Show weight logs and changes")
    s_w.add_argument("--days", type=int, default=30, help="Number of days to look back")
    
    # stats waist
    s_wa = s_sub.add_parser("waist", help="Show waist logs and changes")
    s_wa.add_argument("--days", type=int, default=30, help="Number of days to look back")
    
    args = parser.parse_args()
    
    # Ensure database folder exists and is initialized
    db_path = Path(args.database).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db(db_path)
    
    if args.command == "goal":
        cmd_goal(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "complete":
        cmd_complete(args)
    elif args.command == "check-complete":
        cmd_check_complete(args)
    elif args.command == "weight":
        cmd_weight(args)
    elif args.command == "waist":
        cmd_waist(args)
    elif args.command == "stats":
        if args.stats_command == "day":
            cmd_stats_day(args)
        elif args.stats_command == "week":
            cmd_stats_week(args)
        elif args.stats_command == "trend":
            cmd_stats_trend(args)
        elif args.stats_command == "weight":
            cmd_stats_weight(args)
        elif args.stats_command == "waist":
            cmd_stats_waist(args)

if __name__ == "__main__":
    main()
