---
name: calorie-tracker
description: Log and track daily calorie intake, macronutrients, body weight, and waist measurements locally in a SQLite database. Provides granular statistics, weekly averages, and future calorie budgets.
metadata: {"openclaw": {"requires": {"bins": ["python"]}}}
---

# Local Calorie Tracker Skill

Track daily calorie intake, macronutrients, body weight, and waist measurements locally using a SQLite database.

## Installation & Setup

This is a standalone, skill-first OpenClaw skill. It runs out-of-the-box using standard Python libraries.

The default SQLite database file is named `health_data.db` and is resolved relative to the current working directory (Cwd) of the running agent. To override the database path, pass the `--database PATH` option to any command.

## Operational Instructions for the Agent

1.  **No Compensatory Entries:** If a food entry was logged incorrectly (e.g. wrong calorie or protein count), do not log a new positive or negative "balancing" or "corrective" entry. Instead, identify the incorrect entry's ID using the `list` or `stats day` command, and run the `update` or `delete` command to fix it.
2.  **No Bogus Logs:** Every logged entry's description must contain only the actual name of the food or drink consumed. Do not store summaries, calorie calculations, or meta-data in the food description (e.g., do not name an entry "1875 kcal, 72g protein" to force-balance a day).
3.  **Standardized Meal Types:** Every logged food entry must have a valid `--meal` type. Allowed types are: `breakfast`, `lunch`, `dinner`, `snack`, `fika`, `drink`, `dessert`, `evening`, and `other`. Valid meal types are loaded and validated dynamically from the database.

## Day Completeness Quality Levels

When marking a day as complete using the `complete` command, use one of the following completeness quality levels:
*   `full`: Default. All meals and drinks consumed for the target day were fully tracked.
*   `partial`: Some meals are missing, or the day relies heavily on rough estimates.
*   `minimal`: Only sporadic entries were logged; most of the day's intake is unknown.

## Interpreting Weekly Averages & Budgets

When reviewing weekly averages using the `stats week` command, use these rules to guide the user:
*   **If Today is Incomplete:** Ignore the Monday-to-Today average (as it will be skewed downwards by today's missing meals). Instead, look at the **Monday-to-Yesterday Average** for a true picture of progress, and use the **Daily Budget Remaining (Starting Tomorrow)** to plan subsequent days.
*   **If Today is Complete:** Focus on the **Monday-to-Today Average** and use the **Daily Budget Remaining (Starting Now)** for any remaining snack/beverage limits.

## CLI Reference

All commands support a global `--database PATH` flag (defaulting to `./health_data.db`).

### 1. Configuration & Logging

*   **Configure Daily Goal & Height:**
    ```bash
    python scripts/tracker.py goal CALORIES [PROTEIN] [--height HEIGHT_CM]
    ```
    Sets target calories, optional protein goals (in grams), and optional height in cm (used dynamically by SQLite views to compute BMI and Waist-to-Height Ratio).
    *Example:* `python scripts/tracker.py goal 1800 120 --height 180.0`

*   **Log Food Entry:**
    ```bash
    python scripts/tracker.py add "food description" CALORIES [protein] [carbs] [fat] --meal TYPE [--date YYYY-MM-DD]
    ```
    *Example:* `python scripts/tracker.py add "Oatmeal with blueberries" 350 12 --meal breakfast`

*   **List Entries by ID:**
    ```bash
    python scripts/tracker.py list [DATE]
    ```
    Lists all entries for `DATE` (defaults to today) with their database IDs. Use this to find IDs for updates/deletions.

*   **Update Food Entry:**
    ```bash
    python scripts/tracker.py update ID [--name NAME] [--cal CALORIES] [--p PROTEIN] [--c CARBS] [--f FAT] [--meal TYPE]
    ```
    Modifies an existing entry by ID. Only the specified flags are updated.

*   **Delete Food Entry:**
    ```bash
    python scripts/tracker.py delete ID
    ```
    Permanently deletes a specific entry.

*   **Mark Day as Complete:**
    ```bash
    python scripts/tracker.py complete DATE [--completeness QUALITY] [--notes NOTES]
    ```
    Sets the completeness status (`full` (default), `partial`, or `minimal`) and marks `completed=1` in the database.

*   **Check Day Completion:**
    ```bash
    python scripts/tracker.py check-complete [DATE]
    ```
    Exits with code `0` if the date is fully completed (`completeness == 'full'` and `completed == 1`), otherwise exits with `1`.

*   **Log Body Weight:**
    ```bash
    python scripts/tracker.py weight KG [DATE]
    ```
    Logs weight for the specified date (defaults to today).

*   **Log Waist Circumference:**
    ```bash
    python scripts/tracker.py waist CM [DATE]
    ```
    Logs waist circumference for the specified date (defaults to today).

### 2. Statistics & Reports

*   **Show Daily Breakdown:**
    ```bash
    python scripts/tracker.py stats day [DATE]
    ```
    Prints the chronological list of entries (with IDs), meal-type breakdowns, and progress compared to daily goals.

*   **Show Weekly Summary:**
    ```bash
    python scripts/tracker.py stats week [DATE] [--weeks N] [--compact]
    ```
    Summarizes the Mon-Sun week containing `DATE` (or N preceding weeks). If `--compact` is passed, it outputs a single-line summary of metrics for each week (including weekly totals and daily averages) instead of printing a daily breakdown table. Displays the completed-day average, Mon-yesterday average, Mon-today average, future daily budget limits, and a breakdown table:
    `Day | Date | Kcal | Protein | Target Diff | Completeness`

*   **Show Macronutrient Trends:**
    ```bash
    python scripts/tracker.py stats trend [--days N]
    ```
    Displays 7-day, 30-day, and 90-day rolling averages of calorie and protein intake (resolved dynamically from rolling trends view).

*   **Show Weight logs:**
    ```bash
    python scripts/tracker.py stats weight [--days N]
    ```
    Displays logged weights, calculates current BMI dynamically using height, and shows weight change from the previous log.

*   **Show Waist logs:**
    ```bash
    python scripts/tracker.py stats waist [--days N]
    ```
    Displays logged waist measurements, calculates Waist-to-Height Ratio (WHtR) dynamically, and shows waist change from the previous log.
