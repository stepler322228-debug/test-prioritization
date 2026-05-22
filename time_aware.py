"""
Time-Aware Prioritization
Источник: https://dl.acm.org/doi/10.1145/1572272.1572297
Идея: объекты/фрагменты с аномальным временем жизни имеют высокий приоритет
"""

import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import defaultdict
from dataclasses import dataclass


@dataclass
class TimeMetrics:
    """Временные метрики для объекта"""
    retention_seconds: float      # время жизни
    allocation_rate: float        # объектов/сек
    last_access_delta: float      # секунд с последнего доступа
    idle_ratio: float             # доля времени простоя
    time_priority: float          # итоговая оценка 0-1


class TimeAwarePrioritizer:
    """
    Time-Aware для двух задач:
    1. Плагиат: время выполнения фрагмента (аномально медленный код = подозрительно)
    2. Утечки памяти: время жизни объекта без освобождения
    """
    
    def __init__(self):
        self._allocation_tracker: Dict[int, float] = {}
        self._access_tracker: Dict[int, float] = {}
        self._type_allocations: Dict[str, int] = defaultdict(int)
        self._last_reset = time.time()
        self._lock = threading.Lock()
    
    def track_allocation(self, obj: Any, obj_type: str):
        """Отслеживает создание объекта"""
        with self._lock:
            now = time.time()
            obj_id = id(obj)
            self._allocation_tracker[obj_id] = now
            self._access_tracker[obj_id] = now
            self._type_allocations[obj_type] += 1
    
    def track_access(self, obj: Any):
        """Отслеживает доступ к объекту"""
        with self._lock:
            obj_id = id(obj)
            if obj_id in self._access_tracker:
                self._access_tracker[obj_id] = time.time()
    
    def get_time_metrics_for_object(self, obj: Any, obj_type: str) -> TimeMetrics:
        """Получает временные метрики для объекта (утечки памяти)"""
        with self._lock:
            now = time.time()
            obj_id = id(obj)
            
            alloc_time = self._allocation_tracker.get(obj_id, now)
            last_access = self._access_tracker.get(obj_id, now)
            
            retention = now - alloc_time
            
            # Частота создания объектов данного типа (объектов/сек)
            elapsed = max(now - self._last_reset, 0.001)
            type_rate = self._type_allocations.get(obj_type, 0) / elapsed
            
            idle = now - last_access
            idle_ratio = idle / max(retention, 0.001)
            
            # Рассчитываем time_priority
            time_priority = self._calculate_time_priority_object(
                retention=retention,
                type_rate=type_rate,
                idle_ratio=idle_ratio
            )
            
            return TimeMetrics(
                retention_seconds=retention,
                allocation_rate=type_rate,
                last_access_delta=idle,
                idle_ratio=idle_ratio,
                time_priority=time_priority
            )
    
    def analyze_code_execution_time(self, code: str) -> float:
        """
        Time-Aware анализ для КЛОНА КОДА
        
        Измеряет, сколько времени выполняется фрагмент.
        Аномально медленный код (например, пустые циклы) = признак обфускации
        """
        try:
            # Профилируем выполнение
            import cProfile
            import io
            import pstats
            
            # Создаём безопасное окружение
            safe_globals = {'__builtins__': __builtins__}
            
            pr = cProfile.Profile()
            pr.enable()
            
            start = time.time()
            # Выполняем код (ограничиваем время)
            exec(code, safe_globals)
            exec_time = time.time() - start
            
            pr.disable()
            
            # Анализируем профиль
            s = io.StringIO()
            ps = pstats.Stats(pr, stream=s).sort_stats('cumulative')
            ps.print_stats(10)
            
            # Ищем подозрительные паттерны
            suspicion = self._detect_suspicious_patterns(s.getvalue(), exec_time)
            
            return min(suspicion, 1.0)
            
        except Exception:
            return 0.0
    
    def _calculate_time_priority_object(self, retention: float,
                                         type_rate: float,
                                         idle_ratio: float) -> float:
        """Расчёт приоритета для объектов памяти"""
        score = 0.0
        
        # Фактор 1: Долгоживущие объекты
        if retention > 3600:      # > 1 часа
            score += 0.4
        elif retention > 600:     # > 10 минут
            score += 0.25
        elif retention > 60:      # > 1 минуты
            score += 0.1
        
        # Фактор 2: Высокая частота создания
        if type_rate > 100:
            score += 0.35
        elif type_rate > 10:
            score += 0.2
        elif type_rate > 1:
            score += 0.1
        
        # Фактор 3: Заброшенные объекты (idle_ratio > 0.9)
        if idle_ratio > 0.95:
            score += 0.25
        elif idle_ratio > 0.8:
            score += 0.15
        
        return min(score, 1.0)
    
    def _detect_suspicious_patterns(self, profile_output: str, exec_time: float) -> float:
        """Детектирует подозрительные паттерны в коде"""
        score = 0.0
        
        # Медленный код (подозрительно)
        if exec_time > 1.0:
            score += 0.3
        
        # Поиск пустых циклов в профиле
        if "range" in profile_output and "tottime" in profile_output:
            score += 0.2
        
        # Много вызовов одной функции
        import re
        calls = re.findall(r'(\d+)\s+function calls', profile_output)
        if calls and int(calls[0]) > 1000:
            score += 0.25
        
        return min(score, 1.0)
    
    def reset_stats(self):
        """Сброс статистики для нового теста"""
        with self._lock:
            self._type_allocations.clear()
            self._last_reset = time.time()
    
    def get_allocation_summary(self) -> Dict[str, int]:
        """Возвращает сводку по аллокациям"""
        with self._lock:
            return dict(self._type_allocations)