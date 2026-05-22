"""
Приоритизация для поиска утечек памяти и клонов кода
Методы: Hill Climbing, Time Aware, History-Based
"""

from .hill_climbing import HillClimbingPrioritizer, HillClimbingResult
from .time_aware import TimeAwarePrioritizer, TimeMetrics
from .history_based import HistoryBasedPrioritizer, HistoryDatabase
from .integrator import PrioritizationEngine, PrioritizedItem

__all__ = [
    'HillClimbingPrioritizer',
    'HillClimbingResult', 
    'TimeAwarePrioritizer',
    'TimeMetrics',
    'HistoryBasedPrioritizer',
    'HistoryDatabase',
    'PrioritizationEngine',
    'PrioritizedItem'
]

__version__ = '1.0.0'