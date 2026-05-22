#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Time-Aware Test Case Prioritization (Static Version)

Учитывает время выполнения тестов и бюджет времени (time budget).
Цель – максимизировать количество обнаруженных дефектов за отведённое время.

Алгоритм:
1. Сканирует проект, находит все тесты (без запуска).
2. Загружает список упавших тестов из внешнего файла (статически).
3. Оценивает время выполнения каждого теста по размеру файла (эвристика).
4. Вычисляет приоритет = (failures + 0.5) / sqrt(exec_time) * (criticality/5).
5. Сортирует тесты по убыванию приоритета.
6. Жадно отбирает тесты, пока не будет превышен бюджет времени.
7. Вычисляет APFD для отобранных тестов.

Важное отличие от динамической версии:
    - Тесты НЕ запускаются внутри алгоритма.
    - Список упавших тестов загружается из файла (полученного предварительно).
"""

import os
import sys
import ast
import json
import random
import time
from pathlib import Path

# ============================================================================
# Конфигурационные константы
# ============================================================================
DEFAULT_TIME_BUDGET = 300.0          # бюджет времени по умолчанию (секунды)
MAX_ESTIMATED_TIME = 30.0            # максимальное оценочное время теста
MIN_ESTIMATED_TIME = 0.1             # минимальное оценочное время
BYTES_PER_SECOND_ESTIMATE = 5000.0   # для оценки: 5KB = 1 секунда
FAILURE_CRITICALITY = 8              # критичность для упавших тестов
PASS_CRITICALITY = 5                 # критичность для прошедших тестов
LAST_RUN_MAX_DAYS = 86400            # максимальное смещение last_run (24 часа)

# ============================================================================
# Класс для хранения теста с временными характеристиками
# ============================================================================
class TimedTest:
    """
    Расширенная информация о тесте:
    - имя, путь, метод
    - historical_failures (1 – упал, 0 – прошёл)
    - exec_time – оценочное время выполнения (секунды)
    - min_time, max_time – границы оценки
    - last_run – время последнего запуска (имитация)
    - criticality – важность (1..10)
    """
    __slots__ = ('name', 'method_name', 'file_path', 'historical_failures',
                 'exec_time', 'min_time', 'max_time', 'last_run', 'criticality')
    def __init__(self, name, method_name, file_path):
        self.name = name
        self.method_name = method_name
        self.file_path = file_path
        self.historical_failures = 0
        self.exec_time = 1.0
        self.min_time = 0.5
        self.max_time = 2.0
        self.last_run = 0.0
        self.criticality = 5

# ============================================================================
# Сканер тестов (без запуска)
# ============================================================================
class TimeAwareScanner:
    """
    Сканирует проект, находит все тесты, НЕ запускает их.
    Данные о падениях загружаются отдельно.
    Время выполнения оценивается статически по размеру файла.
    """

    def __init__(self, project_path, time_budget=DEFAULT_TIME_BUDGET):
        self.project_path = Path(project_path).resolve()
        self.time_budget = time_budget
        self.tests = []

    def scan(self):
        """Главный метод: найти тесты, вернуть список."""
        sys.stderr.write("[TimeAware] Scanning: {}\n".format(self.project_path))
        self._collect_tests()
        sys.stderr.write("[TimeAware] Found {} test cases\n".format(len(self.tests)))
        return self.tests

    def _collect_tests(self):
        """Обходит все .py файлы и парсит тесты."""
        self._walk_and_parse(self.project_path)
        # Дополнительно ищем в стандартных папках test/tests
        for subdir in ['test', 'tests']:
            test_dir = self.project_path / subdir
            if test_dir.is_dir():
                self._walk_and_parse(test_dir)

    def _walk_and_parse(self, root_path):
        """Рекурсивно обходит root_path и парсит все .py файлы."""
        for root, dirs, files in os.walk(str(root_path)):
            # Пропускаем скрытые директории и виртуальные окружения
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('env', 'venv', '.venv')]
            for f in files:
                if not f.endswith('.py'):
                    continue
                if self._is_test_file(f):
                    self._parse_file(Path(root) / f)

    @staticmethod
    def _is_test_file(filename):
        """Определяет, является ли файл тестовым (по имени)."""
        return ('test_' in filename or '_test' in filename or filename.startswith('test'))

    def _parse_file(self, filepath):
        """Анализирует один файл через AST, извлекает имена тестов."""
        try:
            with open(str(filepath), 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            tree = ast.parse(content)
            rel_path = str(filepath.relative_to(self.project_path))
            self._extract_tests_from_tree(tree, rel_path)
        except Exception as e:
            sys.stderr.write("Warning: could not parse {}: {}\n".format(filepath, e))

    def _extract_tests_from_tree(self, tree, rel_path):
        """Извлекает тесты из AST-дерева."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                self.tests.append(TimedTest(node.name, node.name, rel_path))
            elif isinstance(node, ast.ClassDef):
                if self._is_test_class(node):
                    self._extract_methods_from_class(node, rel_path)

    @staticmethod
    def _is_test_class(class_node):
        """Проверяет, является ли класс тестовым."""
        return 'Test' in class_node.name or 'TestCase' in class_node.name

    def _extract_methods_from_class(self, class_node, rel_path):
        """Извлекает тестовые методы из класса."""
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'):
                full_name = "{}.{}".format(class_node.name, item.name)
                self.tests.append(TimedTest(full_name, item.name, rel_path))

    def estimate_times(self):
        """
        Оценивает время выполнения теста по размеру файла (байты/5000).
        Также устанавливает min/max время, критичность и last_run.
        Вызывается после загрузки historical_failures.
        """
        for t in self.tests:
            full_path = self.project_path / t.file_path
            if full_path.exists():
                size = full_path.stat().st_size
                t.exec_time = max(MIN_ESTIMATED_TIME, size / BYTES_PER_SECOND_ESTIMATE)
            else:
                t.exec_time = 1.0
            t.exec_time = min(t.exec_time, MAX_ESTIMATED_TIME)
            t.min_time = t.exec_time * 0.8
            t.max_time = t.exec_time * 1.2
            t.criticality = FAILURE_CRITICALITY if t.historical_failures else PASS_CRITICALITY
            # Имитация времени последнего запуска (случайное смещение)
            t.last_run = time.time() - random.uniform(0, LAST_RUN_MAX_DAYS)

# ============================================================================
# Загрузчик списка упавших тестов (статический)
# ============================================================================
def load_failures(tests, failing_file):
    """
    Загружает список упавших тестов из текстового файла.
    Присваивает historical_failures = 1 для упавших, иначе 0.
    """
    if not failing_file or not Path(failing_file).exists():
        return
    with open(failing_file, 'r', encoding='utf-8') as f:
        failed_names = set(line.strip() for line in f if line.strip())
    for t in tests:
        t.historical_failures = 1 if (t.name in failed_names or t.method_name in failed_names) else 0

# ============================================================================
# Time-Aware приоритизатор
# ============================================================================
class TimeAwarePrioritizer:
    """
    Реализует жадный алгоритм отбора тестов в пределах бюджета времени.
    Приоритет = (failures + 0.5) / sqrt(exec_time) * (criticality/5)
    Тесты с высоким приоритетом выполняются раньше.
    """

    def __init__(self, tests, time_budget):
        self.tests = tests
        self.time_budget = time_budget
        self.n = len(tests)

    def apfd(self, order):
        """
        Вычисляет APFD для заданного порядка тестов.
        Формула: APFD = 1 - Σ(pos_i * w_i) / (n * Σw_i) + 1/(2n)
        где w_i = historical_failures.
        """
        n = len(order)
        if n == 0:
            return 0.0
        weights = [t.historical_failures for t in order]
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        weighted_sum = 0.0
        for pos, test in enumerate(order, start=1):
            weighted_sum += pos * test.historical_failures
        apfd_val = 1.0 - weighted_sum / (n * total_weight) + 1.0 / (2 * n)
        return max(0.0, min(1.0, apfd_val))

    def _compute_priority(self, test):
        """
        Вычисляет приоритет теста:
        prio = (historical_failures + 0.5) / sqrt(exec_time) * (criticality/5)
        """
        if test.exec_time <= 0:
            exec_sqrt = 1.0
        else:
            exec_sqrt = test.exec_time ** 0.5
        priority = (test.historical_failures + 0.5) / (exec_sqrt + 0.1)
        priority *= (test.criticality / 5.0)
        return priority

    def prioritize(self):
        """
        Жадный отбор тестов в пределах time_budget.
        Возвращает (список отобранных тестов, APFD).
        """
        if not self.tests:
            return [], 0.0
        # Вычисляем приоритет для каждого теста
        scored = [(self._compute_priority(t), t) for t in self.tests]
        scored.sort(reverse=True, key=lambda x: x[0])
        # Жадный отбор
        selected = []
        time_used = 0.0
        for priority, test in scored:
            if time_used + test.exec_time <= self.time_budget:
                selected.append(test)
                time_used += test.exec_time
        # Если не влез ни один тест, берём хотя бы самый приоритетный
        if not selected and scored:
            selected.append(scored[0][1])
        apfd_val = self.apfd(selected)
        return selected, apfd_val

# ============================================================================
# Вспомогательные функции
# ============================================================================
def validate_project_path(path_str):
    """Проверяет, существует ли переданный путь и является ли он директорией."""
    path = Path(path_str)
    if not path.exists():
        raise FileNotFoundError("Project path does not exist: {}".format(path_str))
    if not path.is_dir():
        raise NotADirectoryError("Project path is not a directory: {}".format(path_str))
    return path

def format_output(algorithm_name, apfd, tests_found, tests_in_budget, budget, elapsed, top_tests=None):
    """Форматирует вывод в JSON."""
    result = {
        "algorithm": algorithm_name,
        "apfd": round(apfd, 4),
        "tests_found": tests_found,
        "tests_in_budget": tests_in_budget,
        "time_budget_seconds": budget,
        "execution_time_seconds": round(elapsed, 2)
    }
    if top_tests:
        result["top_10_tests"] = top_tests
    return json.dumps(result)

# ============================================================================
# Точка входа
# ============================================================================
def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "project path required"}))
        return

    project_path_str = sys.argv[1]
    failing_file = sys.argv[2] if len(sys.argv) > 2 else None
    budget = float(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_TIME_BUDGET

    try:
        project_path = validate_project_path(project_path_str)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return

    start_time = time.time()

    scanner = TimeAwareScanner(str(project_path), budget)
    tests = scanner.scan()

    if not tests:
        print(format_output("Time Aware", 0.0, 0, 0, budget, time.time() - start_time))
        return

    load_failures(tests, failing_file)
    scanner.estimate_times()

    prioritizer = TimeAwarePrioritizer(tests, budget)
    selected_order, apfd_val = prioritizer.prioritize()
    elapsed = time.time() - start_time

    top_10_tests = [t.name for t in selected_order[:10]]

    print(format_output("Time Aware", apfd_val, len(tests), len(selected_order), budget, elapsed, top_10_tests))

if __name__ == "__main__":
    main()