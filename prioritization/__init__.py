#!/usr/bin/env python3
"""
Модуль приоритизации тестов
"""

from .hill_climbing import HillClimbingRunner
from .time_aware import TimeAwareRunner
from .history_based import HistoryBasedRunner

__all__ = ['HillClimbingRunner', 'TimeAwareRunner', 'HistoryBasedRunner']