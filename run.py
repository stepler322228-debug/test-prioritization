#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FINAL RUN SCRIPT (Static, no Docker)
Usage: python run.py <project_path>
Example: python run.py "C:\...\middle_1"
"""

import sys
import subprocess
import json
import csv
from pathlib import Path

def find_failing_file(project_path):
    """Ищет файл с упавшими тестами в стандартных местах"""
    candidates = [
        Path(project_path) / "failing_tests.txt",
        Path(project_path) / "failing_tests_list.txt",
        Path(project_path) / "tests" / "failing_tests.txt",
        Path(project_path) / "test" / "failing_tests.txt",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python run.py <project_path>")
        sys.exit(1)

    project_path = Path(sys.argv[1]).resolve()
    failing_file = find_failing_file(project_path)
    if not failing_file:
        print(f"Error: no failing tests file found in {project_path}")
        print("Please create failing_tests.txt with one test name per line.")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"Project: {project_path.name}")
    print(f"Failing file: {failing_file}")
    print(f"{'='*70}\n")

    algo_dir = Path(__file__).parent / "prioritization"
    algorithms = [
        ("hill_climbing.py", "Hill Climbing"),
        ("time_aware.py", "Time Aware"),
        ("history_based.py", "History Based")
    ]

    results = {}
    display_results = []

    for script, display_name in algorithms:
        script_path = algo_dir / script
        if not script_path.exists():
            print(f"Warning: {script_path} not found, skipping")
            results[display_name] = {"apfd": 0.0, "top10": ""}
            continue

        cmd = [sys.executable, str(script_path), str(project_path), str(failing_file)]
        print(f"Running {display_name}...")
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
            data = json.loads(out)
            apfd = data.get("apfd", 0.0)
            top10 = data.get("top_10_tests", [])
            top10_str = ", ".join(top10) if top10 else "(none)"
            results[display_name] = {"apfd": apfd, "top10": top10_str}
            display_results.append((display_name, apfd, top10_str))
        except Exception as e:
            print(f"Error running {display_name}: {e}")
            results[display_name] = {"apfd": 0.0, "top10": ""}
            display_results.append((display_name, 0.0, "Error"))

    # Вывод на экран в красивом формате
    print(f"\n{'='*70}")
    print("PRIORITIZATION RESULTS")
    print(f"{'='*70}\n")

    for name, apfd, top10 in display_results:
        print(f"Algorithm: {name}")
        print(f"  APFD: {apfd:.4f}")
        print(f"  Test Prioritizing (top 10): {top10}")
        print()

    # Сохраняем CSV
    csv_file = "prioritization_results.csv"
    write_header = not Path(csv_file).exists()
    with open(csv_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "project",
                "hill_climbing_apfd", "hill_climbing_top10",
                "time_aware_apfd", "time_aware_top10",
                "history_based_apfd", "history_based_top10"
            ])
        writer.writerow([
            project_path.name,
            results["Hill Climbing"]["apfd"], results["Hill Climbing"]["top10"],
            results["Time Aware"]["apfd"], results["Time Aware"]["top10"],
            results["History Based"]["apfd"], results["History Based"]["top10"]
        ])

    print(f"{'='*70}")
    print(f"Results saved to {csv_file}")
    print(f"{'='*70}")

if __name__ == "__main__":
    main()