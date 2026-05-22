#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
History-Based Test Case Prioritization (Static Version)

Использует историческую информацию о прошлых запусках тестов для оценки
приоритета. В статической версии данные о падениях загружаются из внешнего
файла (один раз), а не запускаются внутри алгоритма.

Алгоритм:
1. Сканирует проект, находит все тесты.
2. Загружает список упавших тестов из файла (полученного предварительным
   запуском bugsinpy-test или pytest).
3. Для каждого теста вычисляет:
   - частоту падений (failure_rate) – сколько раз упал из общего числа прогонов
   - давность последнего падения (recency) – чем свежее, тем выше
   - серьёзность (severity) – consecutive failures (сколько раз подряд падал)
4. Комбинирует их с весами: priority = 0.5*freq + 0.3*recency + 0.2*severity.
5. Сортирует тесты по убыванию приоритета.
6. Вычисляет APFD.

Важное отличие от динамической версии:
    - Тесты НЕ запускаются внутри алгоритма.
    - Данные о падениях берутся из внешнего источника (файл).
    - Это позволяет работать с любым проектом, где предварительно получен
      список упавших тестов.
"""

import os
import sys
import ast
import json
import time
from pathlib import Path

# ============================================================================
# Конфигурационные константы
# ============================================================================
WEIGHT_FREQUENCY = 0.5      # Вес частоты падений
WEIGHT_RECENCY = 0.3        # Вес давности
WEIGHT_SEVERITY = 0.2       # Вес серьёзности
RECENCY_WINDOW_DAYS = 14.0  # Окно давности (дни)
MAX_CONSECUTIVE_FOR_SEVERITY = 5.0  # Нормализация consecutive failures

# ============================================================================
# Класс для хранения исторической информации о тесте
# ============================================================================
class HistoricalTest:
    """
    Хранит всю историю выполнения одного теста.
    В статической версии эти данные заполняются на основе входного файла.

    Атрибуты:
        name: полное имя теста
        method_name: имя метода
        file_path: путь к файлу
        total_runs: общее число запусков
        total_failures: число падений
        consecutive_failures: число падений подряд
        last_fail_time: время последнего падения (timestamp)
        last_pass_time: время последнего успеха
        failing_versions: множество версий (коммитов), где тест падал
    """
    __slots__ = ('name', 'method_name', 'file_path', 'total_runs', 'total_failures',
                 'consecutive_failures', 'last_fail_time', 'last_pass_time', 'failing_versions')
    def __init__(self, name, method_name, file_path):
        self.name = name
        self.method_name = method_name
        self.file_path = file_path
        self.total_runs = 0
        self.total_failures = 0
        self.consecutive_failures = 0
        self.last_fail_time = 0.0
        self.last_pass_time = 0.0
        self.failing_versions = set()

    def failure_rate(self):
        """Частота падений: total_failures / total_runs (0 если runs=0)."""
        return self.total_failures / self.total_runs if self.total_runs else 0.0

# ============================================================================
# Сканер тестов (без запуска)
# ============================================================================
class HistoryScanner:
    """
    Сканирует проект, находит все тесты, НЕ запускает их.
    Данные о падениях будут загружены отдельно.
    """

    def __init__(self, project_path):
        self.project_path = Path(project_path).resolve()
        self.tests = {}   # словарь: id теста -> HistoricalTest

    def scan(self):
        """Находит тесты и возвращает список объектов HistoricalTest."""
        sys.stderr.write("[HistoryBased] Scanning: {}\n".format(self.project_path))
        self._find_tests()
        sys.stderr.write("[HistoryBased] Found {} unique tests\n".format(len(self.tests)))
        return list(self.tests.values())

    def _find_tests(self):
        """Обходит все .py файлы, ищет test_* и парсит их."""
        self._walk_and_parse(self.project_path)
        # Дополнительно ищем в стандартных папках test/tests
        for subdir in ['test', 'tests']:
            test_dir = self.project_path / subdir
            if test_dir.is_dir():
                self._walk_and_parse(test_dir)

    def _walk_and_parse(self, root_path):
        """Рекурсивно обходит root_path и парсит все .py файлы, подходящие под тестовые."""
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
        """Извлекает тесты из AST-дерева и добавляет в словарь."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                tid = "{}::{}".format(rel_path, node.name)
                if tid not in self.tests:
                    self.tests[tid] = HistoricalTest(node.name, node.name, rel_path)
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
                tid = "{}::{}".format(rel_path, full_name)
                if tid not in self.tests:
                    self.tests[tid] = HistoricalTest(full_name, item.name, rel_path)

# ============================================================================
# Загрузчик данных о падениях (статический)
# ============================================================================
def load_failure_data(tests, failing_file):
    """
    Загружает список упавших тестов из текстового файла.
    Для каждого теста, попавшего в список, увеличивает total_failures и total_runs.
    Для остальных – только total_runs.

    Файл должен содержать по одному имени теста на строку.
    """
    if not failing_file or not Path(failing_file).exists():
        return

    with open(failing_file, 'r', encoding='utf-8') as f:
        failed_names = set(line.strip() for line in f if line.strip())

    now = time.time()
    for test in tests:
        test.total_runs += 1
        if test.name in failed_names or test.method_name in failed_names:
            test.total_failures += 1
            test.consecutive_failures += 1
            test.last_fail_time = now
        else:
            test.consecutive_failures = 0
            test.last_pass_time = now

# ============================================================================
# History-Based Prioritizer
# ============================================================================
class HistoryBasedPrioritizer:
    """
    Вычисляет приоритет для каждого теста на основе исторических данных.

    Формула приоритета:
        priority = weight_freq * failure_rate
                 + weight_recency * recency_score
                 + weight_severity * severity_score

    Затем сортирует тесты по убыванию приоритета и вычисляет APFD.
    """

    def __init__(self, tests):
        self.tests = tests
        self.n = len(tests)

    def apfd(self, order):
        """
        Вычисляет APFD для заданного порядка тестов.

        Формула:
            APFD = 1 - Σ(pos_i * w_i) / (n * Σw_i) + 1/(2n)

        где w_i = total_failures теста.
        """
        n = len(order)
        if n == 0:
            return 0.0
        weights = [t.total_failures for t in order]
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        weighted_sum = 0.0
        for pos, test in enumerate(order, start=1):
            weighted_sum += pos * test.total_failures
        apfd_val = 1.0 - weighted_sum / (n * total_weight) + 1.0 / (2 * n)
        return max(0.0, min(1.0, apfd_val))

    def _recency_score(self, test, now):
        """
        Оценка давности последнего падения:
            1.0 если падение было сегодня, 0 если >14 дней назад.
        """
        if test.last_fail_time == 0:
            return 0.0
        days_since = (now - test.last_fail_time) / 86400.0
        return max(0.0, 1.0 - days_since / RECENCY_WINDOW_DAYS)

    def _severity_score(self, test):
        """
        Оценка серьёзности (consecutive failures):
            consecutive_failures / MAX_CONSECUTIVE, но не более 1.
        """
        return min(1.0, test.consecutive_failures / MAX_CONSECUTIVE_FOR_SEVERITY)

    def prioritize(self):
        """
        Вычисляет приоритеты, сортирует тесты, возвращает порядок и APFD.
        """
        if not self.tests:
            return [], 0.0
        now = time.time()
        scored = []
        for test in self.tests:
            freq = test.failure_rate()
            recency = self._recency_score(test, now)
            severity = self._severity_score(test)
            priority = (WEIGHT_FREQUENCY * freq) + (WEIGHT_RECENCY * recency) + (WEIGHT_SEVERITY * severity)
            scored.append((priority, test))
        scored.sort(reverse=True, key=lambda x: x[0])
        ordered_tests = [test for _, test in scored]
        apfd_val = self.apfd(ordered_tests)
        return ordered_tests, apfd_val

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

def format_output(algorithm_name, apfd, tests_found, total_runs, total_fails, elapsed, top_tests=None):
    """Форматирует вывод в JSON."""
    result = {
        "algorithm": algorithm_name,
        "apfd": round(apfd, 4),
        "tests_found": tests_found,
        "total_executions": total_runs,
        "total_failures": total_fails,
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

    try:
        project_path = validate_project_path(project_path_str)
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return

    start_time = time.time()

    scanner = HistoryScanner(str(project_path))
    tests = scanner.scan()

    if not tests:
        print(format_output("History Based", 0.0, 0, 0, 0, time.time() - start_time))
        return

    load_failure_data(tests, failing_file)

    prioritizer = HistoryBasedPrioritizer(tests)
    ordered_tests, apfd_value = prioritizer.prioritize()  # Теперь получаем ordered_tests
    elapsed = time.time() - start_time

    total_runs = sum(t.total_runs for t in tests)
    total_fails = sum(t.total_failures for t in tests)
    top_10_tests = [t.name for t in ordered_tests[:10]]  # Берём топ-10

    print(format_output("History Based", apfd_value, len(tests), total_runs, total_fails, elapsed, top_10_tests))

if __name__ == "__main__":
    main()