"""
History-Based Prioritization
Источник: https://ieeexplore.ieee.org/document/10011511
Идея: объекты/паттерны, которые уже были проблемой, имеют высокий приоритет
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from pathlib import Path
from collections import defaultdict


class HistoryDatabase:
    """Хранилище истории (SQLite)"""
    
    def __init__(self, db_path: str = "history.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            # Для плагиата
            conn.execute("""
                CREATE TABLE IF NOT EXISTS code_clone_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_hash TEXT,
                    file_location TEXT,
                    detection_count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP,
                    was_verified_plagiarism BOOLEAN DEFAULT 0
                )
            """)
            
            # Для утечек памяти
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_leak_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_type TEXT,
                    file_location TEXT,
                    line_number INTEGER,
                    size_bytes INTEGER,
                    detection_count INTEGER DEFAULT 1,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP,
                    was_confirmed_leak BOOLEAN DEFAULT 0
                )
            """)
            
            # Общая статистика
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_stats (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP
                )
            """)
    
    def record_code_clone(self, content_hash: str, location: str, is_plagiarism: bool = False):
        """Записывает обнаружение клона кода"""
        with sqlite3.connect(self.db_path) as conn:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO code_clone_history 
                (content_hash, file_location, detection_count, first_seen, last_seen, was_verified_plagiarism)
                VALUES (?, ?, 1, ?, ?, ?)
                ON CONFLICT DO UPDATE SET
                    detection_count = detection_count + 1,
                    last_seen = ?,
                    was_verified_plagiarism = was_verified_plagiarism OR ?
            """, (content_hash, location, now, now, is_plagiarism, now, is_plagiarism))
    
    def record_memory_leak(self, obj_type: str, location: str, line: int,
                           size: int, is_leak: bool = False):
        """Записывает подозрение на утечку памяти"""
        with sqlite3.connect(self.db_path) as conn:
            now = datetime.now().isoformat()
            conn.execute("""
                INSERT INTO memory_leak_history 
                (object_type, file_location, line_number, size_bytes, detection_count, first_seen, last_seen, was_confirmed_leak)
                VALUES (?, ?, ?, ?, 1, ?, ?, ?)
            """, (obj_type, location, line, size, now, now, is_leak))
    
    def get_history_for_code(self, content_hash: str) -> Dict:
        """Получает историю для клона кода"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT detection_count, last_seen, was_verified_plagiarism
                FROM code_clone_history
                WHERE content_hash = ?
            """, (content_hash,))
            row = cursor.fetchone()
            
            if not row:
                return {'detection_count': 0, 'days_since_last': None, 'is_verified': False}
            
            detection_count, last_seen, is_verified = row
            last_seen_dt = datetime.fromisoformat(last_seen)
            days_since = (datetime.now() - last_seen_dt).days
            
            return {
                'detection_count': detection_count,
                'days_since_last': days_since,
                'is_verified': is_verified
            }
    
    def get_history_for_object(self, obj_type: str, location: str, line: int) -> Dict:
        """Получает историю для объекта памяти"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT detection_count, last_seen, was_confirmed_leak, avg(size_bytes) as avg_size
                FROM memory_leak_history
                WHERE object_type = ? AND file_location = ? AND line_number = ?
                GROUP BY object_type, file_location, line_number
            """, (obj_type, location, line))
            row = cursor.fetchone()
            
            if not row:
                return {'detection_count': 0, 'days_since_last': None, 'is_confirmed': False}
            
            detection_count, last_seen, is_confirmed, avg_size = row
            last_seen_dt = datetime.fromisoformat(last_seen)
            days_since = (datetime.now() - last_seen_dt).days
            
            return {
                'detection_count': detection_count,
                'days_since_last': days_since,
                'is_confirmed': is_confirmed,
                'avg_size': avg_size
            }


class HistoryBasedPrioritizer:
    """
    History-Based для двух задач
    """
    
    def __init__(self, db_path: str = "history.db"):
        self.db = HistoryDatabase(db_path)
    
    def calculate_priority_for_code(self, content_hash: str, extra_context: Dict = None) -> float:
        """
        History-приоритет для КЛОНА КОДА
        
        Принципы из статьи IEEE:
        - Часто встречающиеся клоны = высокий приоритет
        - Недавние клоны = высокий приоритет (recency)
        - Подтверждённый плагиат = супер-высокий приоритет
        """
        history = self.db.get_history_for_code(content_hash)
        
        detection_count = history['detection_count']
        days_since = history.get('days_since_last')
        is_verified = history.get('is_verified', False)
        
        score = 0.0
        
        # Фактор 1: Количество предыдущих детекций
        if detection_count >= 5:
            score += 0.5
        elif detection_count >= 3:
            score += 0.35
        elif detection_count >= 1:
            score += 0.2
        
        # Фактор 2: Недавность (recency)
        if days_since is not None:
            if days_since <= 1:      # сегодня
                score += 0.3
            elif days_since <= 7:    # на этой неделе
                score += 0.2
            elif days_since <= 30:   # в этом месяце
                score += 0.1
        
        # Фактор 3: Подтверждённый случай
        if is_verified:
            score += 0.25
        
        return min(score, 1.0)
    
    def calculate_priority_for_object(self, obj_type: str, location: str, line: int) -> float:
        """
        History-приоритет для ОБЪЕКТА ПАМЯТИ
        """
        history = self.db.get_history_for_object(obj_type, location, line)
        
        detection_count = history['detection_count']
        days_since = history.get('days_since_last')
        is_confirmed = history.get('is_confirmed', False)
        
        score = 0.0
        
        if detection_count >= 3:
            score += 0.5
        elif detection_count >= 1:
            score += 0.3
        
        if days_since is not None:
            if days_since <= 1:
                score += 0.35
            elif days_since <= 7:
                score += 0.2
        
        if is_confirmed:
            score += 0.3
        
        return min(score, 1.0)
    
    def record_suspicious_code(self, content_hash: str, location: str):
        """Записывает подозрительный фрагмент кода"""
        self.db.record_code_clone(content_hash, location)
    
    def record_confirmed_plagiarism(self, content_hash: str, location: str):
        """Подтверждает, что это был плагиат"""
        self.db.record_code_clone(content_hash, location, is_plagiarism=True)
    
    def record_suspicious_object(self, obj_type: str, location: str, line: int, size: int):
        """Записывает подозрительный объект"""
        self.db.record_memory_leak(obj_type, location, line, size)
    
    def get_top_recurring_patterns(self, limit: int = 10) -> List[Dict]:
        """Возвращает самые частые паттерны из истории"""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.execute("""
                SELECT content_hash, detection_count, last_seen
                FROM code_clone_history
                ORDER BY detection_count DESC
                LIMIT ?
            """, (limit,))
            
            return [{'hash': row[0], 'count': row[1], 'last_seen': row[2]}
                    for row in cursor.fetchall()]