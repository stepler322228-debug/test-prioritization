"""
Hill Climbing для приоритизации
Источник: https://dl.acm.org/doi/10.1145/1830483.1830735
Идея: "поднимаемся" к объектам с максимальной подозрительностью
"""

import gc
import sys
from typing import Dict, List, Any, Set, Optional
from dataclasses import dataclass


@dataclass
class HillClimbingResult:
    """Результат Hill Climbing анализа"""
    object_id: int
    object_type: str
    path_length: int          # длина пути до GC root
    depth: int                # глубина в дереве ссылок
    is_cyclic: bool           # есть циклическая ссылка?
    ref_count: int            # количество ссылок на объект
    suspicion_score: float    # итоговая оценка 0-1


class HillClimbingPrioritizer:
    """
    Hill Climbing для поиска подозрительных объектов/клонов
    
    Применение к двум задачам:
    1. Плагиат: чем сложнее соединить фрагменты кода, тем подозрительнее
    2. Утечки памяти: чем дальше объект от GC root, тем подозрительнее
    """
    
    def __init__(self, use_heuristics: bool = True):
        self.use_heuristics = use_heuristics
        self._visited: Set[int] = set()
        self._max_depth = 20
    
    def analyze_object(self, obj: Any) -> HillClimbingResult:
        """
        Hill Climbing анализ ОДНОГО объекта (для утечек памяти)
        """
        obj_id = id(obj)
        obj_type = type(obj).__name__
        
        # Измеряем путь до GC root
        path_length = self._measure_path_to_root(obj)
        
        # Проверяем на циклические ссылки
        is_cyclic = self._detect_cycle(obj)
        
        # Считаем количество ссылок
        ref_count = len(gc.get_referrers(obj))
        
        # Глубина (эвристика)
        depth = min(path_length, self._max_depth)
        
        # Рассчитываем suspicion_score (0-1)
        suspicion = self._calculate_suspicion_score(
            path_length=path_length,
            is_cyclic=is_cyclic,
            ref_count=ref_count,
            obj_type=obj_type,
            use_case="memory_leak"
        )
        
        return HillClimbingResult(
            object_id=obj_id,
            object_type=obj_type,
            path_length=path_length,
            depth=depth,
            is_cyclic=is_cyclic,
            ref_count=ref_count,
            suspicion_score=suspicion
        )
    
    def analyze_code_clone(self, code_fragment: str, context: Dict = None) -> float:
        """
        Hill Climbing анализ ДЛЯ КЛОНОВ КОДА (плагиат)
        
        Идея: чем больше "шагов" нужно сделать, чтобы соединить фрагменты,
        тем выше подозрительность (код был намеренно изменён)
        """
        if not self.use_heuristics:
            return 0.5
        
        suspicion = 0.0
        
        # Фактор 1: Длина фрагмента (большие блоки = подозрительнее)
        lines = code_fragment.split('\n')
        if len(lines) > 20:
            suspicion += 0.3
        elif len(lines) > 10:
            suspicion += 0.15
        
        # Фактор 2: Сложность структуры (наличие вложенных блоков)
        indent_ratio = self._calculate_indent_complexity(code_fragment)
        suspicion += indent_ratio * 0.2
        
        # Фактор 3: Энтропия (равномерность распределения символов)
        entropy = self._calculate_entropy(code_fragment)
        if entropy > 4.0:  # высокая энтропия = возможно обфускация
            suspicion += 0.25
        
        # Фактор 4: Аномалии в именах (подозрительные переименования)
        if context and 'renamed_vars' in context:
            suspicion += min(len(context['renamed_vars']) * 0.05, 0.25)
        
        return min(suspicion, 1.0)
    
    def _measure_path_to_root(self, obj: Any) -> int:
        """Измеряет длину пути от объекта до GC root"""
        # Упрощённая эвристика
        referrers = gc.get_referrers(obj)
        if not referrers:
            return 0
        
        # Проверяем, является ли кто-то из рефереров GC root
        for ref in referrers:
            if self._is_gc_root(ref):
                return 1
        
        # Рекурсивно ищем (ограничиваем глубину)
        return min(len(referrers), self._max_depth)
    
    def _is_gc_root(self, obj: Any) -> bool:
        """Проверяет, является ли объект GC root"""
        # В Python GC roots включают: глобальные переменные модуля, стек вызовов
        try:
            # Простая эвристика
            if hasattr(obj, '__module__') and obj.__module__ == '__main__':
                return True
        except:
            pass
        return False
    
    def _detect_cycle(self, obj: Any) -> bool:
        """Детектирует циклические ссылки"""
        referrers = gc.get_referrers(obj)
        try:
            referents = gc.get_referents(obj)
            for ref in referrers:
                if id(ref) in [id(r) for r in referents]:
                    return True
        except:
            pass
        return False
    
    def _calculate_suspicion_score(self, path_length: int, is_cyclic: bool,
                                    ref_count: int, obj_type: str,
                                    use_case: str = "memory_leak") -> float:
        """Расчёт итоговой подозрительности"""
        score = 0.0
        
        if use_case == "memory_leak":
            # Длинный путь до GC root
            if path_length > 10:
                score += 0.4
            elif path_length > 5:
                score += 0.25
            elif path_length > 2:
                score += 0.1
            
            # Циклические ссылки (классика утечек в Python)
            if is_cyclic:
                score += 0.35
            
            # Много ссылок = сложный граф
            if ref_count > 10:
                score += 0.2
        
        else:  # plagiarism
            # Другая логика для плагиата
            if path_length > 5:
                score += 0.3
            if is_cyclic:  # повторяющиеся паттерны
                score += 0.2
            if ref_count > 5:  # много совпадений
                score += 0.15
        
        return min(score, 1.0)
    
    def _calculate_indent_complexity(self, code: str) -> float:
        """Считает сложность отступов (вложенность)"""
        lines = code.split('\n')
        max_indent = 0
        for line in lines:
            stripped = line.lstrip()
            if stripped:
                indent = len(line) - len(stripped)
                max_indent = max(max_indent, indent // 4)
        return min(max_indent / 10, 1.0)
    
    def _calculate_entropy(self, text: str) -> float:
        """Считает энтропию Шеннона (чем выше, тем "случайнее" текст)"""
        import math
        if not text:
            return 0.0
        
        freq = {}
        for ch in text:
            freq[ch] = freq.get(ch, 0) + 1
        
        entropy = 0.0
        length = len(text)
        for count in freq.values():
            prob = count / length
            entropy -= prob * math.log2(prob)
        
        return entropy