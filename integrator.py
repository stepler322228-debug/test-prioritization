"""
Интегратор трёх методов приоритизации
"""

from typing import List, Dict, Any, Tuple
from dataclasses import dataclass, field
from .hill_climbing import HillClimbingPrioritizer
from .time_aware import TimeAwarePrioritizer
from .history_based import HistoryBasedPrioritizer


@dataclass
class PrioritizedItem:
    """Элемент с приоритетом"""
    id: str
    name: str
    hill_score: float
    time_score: float
    history_score: float
    final_score: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def __lt__(self, other):
        return self.final_score > other.final_score  # для сортировки по убыванию


class PrioritizationEngine:
    """Объединяет все три метода"""
    
    def __init__(self, weights: Dict[str, float] = None):
        """
        weights: {'hill_climbing': 0.35, 'time_aware': 0.35, 'history_based': 0.30}
        """
        self.hill_climbing = HillClimbingPrioritizer()
        self.time_aware = TimeAwarePrioritizer()
        self.history_based = HistoryBasedPrioritizer()
        
        self.weights = weights or {
            'hill_climbing': 0.35,
            'time_aware': 0.35,
            'history_based': 0.30
        }
    
    def prioritize_code_clones(self, clones: List[Dict]) -> List[PrioritizedItem]:
        """
        Приоритизация клонов кода (плагиат)
        
        clones: список словарей с ключами:
            - id: уникальный ID клона
            - code: текст кода
            - hash: хэш содержимого
            - location: файл-источник
            - extra: дополнительные данные (переименованные переменные и т.д.)
        """
        results = []
        
        for clone in clones:
            # 1. Hill Climbing
            hill_score = self.hill_climbing.analyze_code_clone(
                code_fragment=clone.get('code', ''),
                context=clone.get('extra', {})
            )
            
            # 2. Time Aware
            time_score = self.time_aware.analyze_code_execution_time(
                clone.get('code', '')
            )
            
            # 3. History-Based
            history_score = self.history_based.calculate_priority_for_code(
                content_hash=clone.get('hash', ''),
                extra_context=clone.get('extra')
            )
            
            # Итоговый приоритет
            final_score = (
                hill_score * self.weights['hill_climbing'] +
                time_score * self.weights['time_aware'] +
                history_score * self.weights['history_based']
            ) * 1000  # шкала 0-1000
            
            results.append(PrioritizedItem(
                id=clone.get('id', 'unknown'),
                name=clone.get('location', 'unknown'),
                hill_score=hill_score,
                time_score=time_score,
                history_score=history_score,
                final_score=final_score,
                details=clone
            ))
        
        # Сортируем по убыванию приоритета
        results.sort(key=lambda x: x.final_score, reverse=True)
        return results
    
    def prioritize_memory_objects(self, objects: List[Any], 
                                   locations: Dict[int, Tuple[str, int]] = None) -> List[PrioritizedItem]:
        """
        Приоритизация объектов памяти (утечки)
        
        objects: список объектов Python
        locations: маппинг id объекта -> (file, line)
        """
        results = []
        
        for obj in objects:
            obj_id = id(obj)
            obj_type = type(obj).__name__
            location_info = locations.get(obj_id, ('unknown', 0)) if locations else ('unknown', 0)
            file_name, line_num = location_info
            
            # 1. Hill Climbing
            hill_result = self.hill_climbing.analyze_object(obj)
            hill_score = hill_result.suspicion_score
            
            # 2. Time Aware
            time_metrics = self.time_aware.get_time_metrics_for_object(obj, obj_type)
            time_score = time_metrics.time_priority
            
            # 3. History-Based
            history_score = self.history_based.calculate_priority_for_object(
                obj_type=obj_type,
                location=file_name,
                line=line_num
            )
            
            # Итоговый приоритет
            final_score = (
                hill_score * self.weights['hill_climbing'] +
                time_score * self.weights['time_aware'] +
                history_score * self.weights['history_based']
            ) * 1000
            
            results.append(PrioritizedItem(
                id=str(obj_id),
                name=f"{obj_type} at {file_name}:{line_num}",
                hill_score=hill_score,
                time_score=time_score,
                history_score=history_score,
                final_score=final_score,
                details={
                    'object': obj,
                    'type': obj_type,
                    'file': file_name,
                    'line': line_num,
                    'hill_result': hill_result,
                    'time_metrics': time_metrics
                }
            ))
        
        results.sort(key=lambda x: x.final_score, reverse=True)
        return results
    
    def print_report(self, items: List[PrioritizedItem], limit: int = 10):
        """Печатает отчёт о приоритизации"""
        print("\n" + "="*70)
        print(f"PRIORITIZATION REPORT (Top {min(limit, len(items))} of {len(items)})")
        print("="*70)
        print(f"{'#':<3} {'Name':<35} {'Hill':>6} {'Time':>6} {'Hist':>6} {'Final':>8}")
        print("-"*70)
        
        for i, item in enumerate(items[:limit], 1):
            print(f"{i:<3} {item.name[:34]:<35} "
                  f"{item.hill_score*100:>5.0f}% "
                  f"{item.time_score*100:>5.0f}% "
                  f"{item.history_score*100:>5.0f}% "
                  f"{item.final_score:>7.1f}")
        
        print("="*70)
        print(f"Weights: HC={self.weights['hill_climbing']}, "
              f"TA={self.weights['time_aware']}, "
              f"HB={self.weights['history_based']}")