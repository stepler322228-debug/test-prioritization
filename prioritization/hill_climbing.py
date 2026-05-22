#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hill Climbing Test Case Prioritization (Static Version)

Реализует поиск оптимального порядка выполнения тестов с помощью
метода восхождения на холм (hill climbing). Целевая функция – APFD.

Алгоритм:
1. Начинает с начального порядка (жадного или случайного).
2. Генерирует соседние порядки путём перестановки двух тестов.
3. Если соседний порядок даёт лучшее APFD – переходит к нему.
4. Повторяет до заданного числа итераций, с несколькими рестартами.

Этот алгоритм соответствует классическому hill climbing для
комбинаторной оптимизации: он всегда пытается улучшить текущее
решение, делая локальные шаги, и может застревать в локальных
максимумах, поэтому используются рестарты и вероятностный отжиг.

Важное отличие от динамической версии:
    - Тесты НЕ запускаются внутри алгоритма.
    - Список упавших тестов загружается из внешнего файла (статически).
    - Это значительно быстрее и правильно для задачи приоритизации.
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
DEFAULT_MAX_ITERATIONS = 500      # Максимум итераций для одного рестарта
DEFAULT_RESTARTS = 5              # Количество рестартов
DEFAULT_TEMPERATURE = 0.5         # Начальная температура для отжига
TEMPERATURE_STEP = 0.2            # Шаг изменения температуры между рестартами
TEMPERATURE_START = 0.3           # Начальная температура для первого рестарта

# ============================================================================
# Класс для хранения информации о тесте
# ============================================================================
class TestCase:
    """
    Представляет один тест с его именем и историей падений.

    Атрибуты:
        name: полное имя теста (например, 'TestClass.test_method')
        method_name: имя метода (например, 'test_method')
        file_path: относительный путь к файлу с тестом
        historical_failures: 0 – тест прошёл, 1 – тест упал (для данного бага)
    """
    __slots__ = ('name', 'method_name', 'file_path', 'historical_failures')
    def __init__(self, name, method_name, file_path):
        self.name = name
        self.method_name = method_name
        self.file_path = file_path
        self.historical_failures = 0

# ============================================================================
# Сканер тестов (без запуска)
# ============================================================================
class TestScanner:
    """
    Сканирует проект, находит все тесты, но НЕ запускает их.
    Список упавших тестов загружается отдельно из файла.
    """

    def __init__(self, project_path):
        self.project_path = Path(project_path).resolve()
        self.tests = []

    def scan(self):
        """Главный метод: найти тесты, вернуть список."""
        sys.stderr.write("[HillClimbing] Scanning: {}\n".format(self.project_path))
        self._find_tests()
        sys.stderr.write("[HillClimbing] Found {} test cases\n".format(len(self.tests)))
        return self.tests

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
        """Извлекает тесты из AST-дерева."""
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'):
                self.tests.append(TestCase(node.name, node.name, rel_path))
            elif isinstance(node, ast.ClassDef):
                if self._is_test_class(node):
                    self._extract_methods_from_class(node, rel_path)

    @staticmethod
    def _is_test_class(class_node):
        """Проверяет, является ли класс тестовым (содержит 'Test' в имени)."""
        return 'Test' in class_node.name or 'TestCase' in class_node.name

    def _extract_methods_from_class(self, class_node, rel_path):
        """Извлекает тестовые методы из класса."""
        for item in class_node.body:
            if isinstance(item, ast.FunctionDef) and item.name.startswith('test_'):
                full_name = "{}.{}".format(class_node.name, item.name)
                self.tests.append(TestCase(full_name, item.name, rel_path))

# ============================================================================
# Загрузчик списка упавших тестов (статический)
# ============================================================================
def load_failing_tests(failing_file):
    """
    Загружает список упавших тестов из текстового файла.
    Файл должен содержать по одному имени теста на строку (например, 'test_match_str').

    Если файл не существует или пуст, возвращается пустое множество.
    """
    if not failing_file or not Path(failing_file).exists():
        return set()
    with open(failing_file, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f if line.strip())

# ============================================================================
# Hill Climbing оптимизатор (полностью статический)
# ============================================================================
class HillClimbingOptimizer:
    """
    Реализует алгоритм восхождения на холм для максимизации APFD.

    Параметры:
        tests: список объектов TestCase
        failing_set: множество имён упавших тестов
        max_iterations: количество итераций для одного рестарта
        restarts: число рестартов с разными начальными порядками

    Принцип работы:
        - Сначала каждому тесту присваивается historical_failures = 1,
          если его имя есть в failing_set, иначе 0.
        - Начальный порядок может быть жадным (упавшие тесты первыми) или случайным.
        - На каждой итерации генерируется соседний порядок (swap двух тестов).
        - Если сосед лучше – переходим. Если хуже – с некоторой вероятностью
          (зависящей от температуры) всё равно переходим (для избежания локальных максимумов).
        - Температура уменьшается с каждой итерацией, имитируя отжиг.
        - Запускается несколько рестартов с разными начальными порядками и температурами.
    """

    def __init__(self, tests, failing_set, max_iterations=DEFAULT_MAX_ITERATIONS, restarts=DEFAULT_RESTARTS):
        self.tests = tests
        self.n = len(tests)
        self.max_iterations = max_iterations
        self.restarts = restarts
        self.cache = {}  # Кэш для ускорения расчёта APFD

        # Присваиваем historical_failures на основе переданного списка упавших тестов
        for t in self.tests:
            t.historical_failures = 1 if (t.name in failing_set or t.method_name in failing_set) else 0

    def apfd(self, order):
        """
        Вычисляет APFD для заданного порядка тестов (список индексов).

        Формула:
            APFD = 1 - Σ(pos_i * w_i) / (n * Σw_i) + 1/(2n)

        где pos_i – позиция теста (начиная с 1), w_i – вес (historical_failures).
        """
        key = tuple(order)
        if key in self.cache:
            return self.cache[key]
        if self.n == 0:
            return 0.0
        weights = [self.tests[i].historical_failures for i in order]
        total_weight = sum(weights)
        if total_weight == 0:
            return 0.0
        weighted_sum = 0.0
        for pos, idx in enumerate(order, start=1):
            weighted_sum += pos * self.tests[idx].historical_failures
        apfd_val = 1.0 - weighted_sum / (self.n * total_weight) + 1.0 / (2 * self.n)
        apfd_val = max(0.0, min(1.0, apfd_val))
        self.cache[key] = apfd_val
        return apfd_val

    def _swap(self, order):
        """Генерирует соседний порядок: меняет местами два случайных теста."""
        if self.n < 2:
            return order[:]
        new = order[:]
        i, j = random.sample(range(self.n), 2)
        new[i], new[j] = new[j], new[i]
        return new

    def _greedy_initial(self):
        """Начальный порядок: тесты с historical_failures=1 в начале, остальные в конце."""
        return sorted(range(self.n), key=lambda i: -self.tests[i].historical_failures)

    def _random_initial(self):
        """Случайный начальный порядок."""
        order = list(range(self.n))
        random.shuffle(order)
        return order

    def run_single(self, initial, temperature=DEFAULT_TEMPERATURE):
        """
        Один прогон hill climbing с заданным начальным порядком.

        Аргументы:
            initial: список индексов начального порядка
            temperature: начальная температура (влияет на вероятность принятия худших решений)

        Возвращает: (лучший порядок, лучшее значение APFD) для этого прогона.
        """
        current = initial[:]
        current_apfd = self.apfd(current)
        for iteration in range(self.max_iterations):
            # Адаптивное уменьшение температуры (линейное)
            t = temperature * (1.0 - iteration / self.max_iterations)
            neighbor = self._swap(current)
            neighbor_apfd = self.apfd(neighbor)
            if neighbor_apfd > current_apfd:
                current, current_apfd = neighbor, neighbor_apfd
            else:
                delta = neighbor_apfd - current_apfd
                # С вероятностью, зависящей от температуры, принимаем худшее решение
                if random.random() < (temperature * abs(delta)):
                    current, current_apfd = neighbor, neighbor_apfd
        return current, current_apfd

    def run(self):
        """
        Запуск hill climbing с несколькими рестартами.

        Возвращает: (лучший порядок, лучший APFD) среди всех рестартов.
        """
        if self.n == 0:
            return [], 0.0
        best_order = None
        best_apfd = -1.0
        # Комбинация жадного и случайных начальных порядков
        initial_orders = [self._greedy_initial()] + [self._random_initial() for _ in range(self.restarts - 1)]
        for i, init in enumerate(initial_orders):
            # Разная температура для каждого рестарта
            temp = TEMPERATURE_START + i * TEMPERATURE_STEP
            order, apfd_val = self.run_single(init, temp)
            if apfd_val > best_apfd:
                best_apfd, best_order = apfd_val, order
        return best_order, best_apfd

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

def format_output(algorithm_name, apfd, tests_found, elapsed, top_tests=None):
    """Форматирует вывод в JSON."""
    result = {
        "algorithm": algorithm_name,
        "apfd": round(apfd, 4),
        "tests_found": tests_found,
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

    scanner = TestScanner(str(project_path))
    tests = scanner.scan()

    if not tests:
        print(format_output("Hill Climbing", 0.0, 0, time.time() - start_time))
        return

    failing_set = load_failing_tests(failing_file)
    optimizer = HillClimbingOptimizer(tests, failing_set)
    best_order, apfd_value = optimizer.run()  # Теперь получаем best_order
    elapsed = time.time() - start_time

    # Получаем топ-10 тестов
    top_10_tests = [tests[i].name for i in best_order[:10]]

    print(format_output("Hill Climbing", apfd_value, len(tests), elapsed, top_10_tests))

if __name__ == "__main__":
    main()

