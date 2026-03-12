"""
core/state_monitoring.py
Расширенная система мониторинга и аналитики для валидации состояний.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple, Any, Set, Callable
from collections import defaultdict, deque
from dataclasses import dataclass, asdict
from functools import wraps
import aiofiles

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from core.state_validator import state_validator
from core.admin_tools import admin_manager
from core import states

logger = logging.getLogger(__name__)


@dataclass
class StateTransitionEvent:
    """Событие перехода состояния."""
    user_id: int
    from_state: Optional[int]
    to_state: int
    handler_name: str
    is_valid: bool
    timestamp: datetime
    duration_ms: Optional[int] = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь для сериализации."""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        data['from_state_name'] = state_validator._state_name(self.from_state) if self.from_state else "None"
        data['to_state_name'] = state_validator._state_name(self.to_state)
        return data


class StateMonitor:
    """Монитор состояний с расширенной аналитикой."""
    
    def __init__(self, 
                 anomaly_threshold: int = 5,
                 window_size: int = 3600,  # 1 час
                 max_events: int = 10000):
        self.anomaly_threshold = anomaly_threshold
        self.window_size = window_size
        self.max_events = max_events
        
        # Хранилище событий
        self.events: deque = deque(maxlen=max_events)
        
        # Счетчики для быстрого доступа
        self.user_error_counts: Dict[int, int] = defaultdict(int)
        self.transition_counts: Dict[str, int] = defaultdict(int)
        self.handler_performance: Dict[str, List[int]] = defaultdict(list)
        
        # Аномалии
        self.anomalies: List[Dict] = []
        self.blocked_users: Set[int] = set()
        
        # Фоновые задачи
        self._monitoring_task = None
        self._cleanup_task = None
    
    async def start(self):
        """Запуск мониторинга."""
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("State monitoring started")
    
    async def stop(self):
        """Остановка мониторинга."""
        if self._monitoring_task:
            self._monitoring_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        
        # Сохраняем статистику
        await self.save_stats()
        logger.info("State monitoring stopped")
    
    def record_transition(self, event: StateTransitionEvent):
        """Записывает событие перехода."""
        self.events.append(event)
        
        # Обновляем счетчики
        transition_key = f"{event.from_state}->{event.to_state}"
        self.transition_counts[transition_key] += 1
        
        if not event.is_valid:
            self.user_error_counts[event.user_id] += 1
        
        if event.duration_ms:
            self.handler_performance[event.handler_name].append(event.duration_ms)
            # Оставляем только последние 100 измерений
            if len(self.handler_performance[event.handler_name]) > 100:
                self.handler_performance[event.handler_name] = self.handler_performance[event.handler_name][-100:]
    
    async def _monitor_loop(self):
        """Основной цикл мониторинга."""
        while True:
            try:
                await asyncio.sleep(60)  # Проверка каждую минуту
                await self._check_anomalies()
                await self._check_performance()
                await self._update_metrics()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
    
    async def _cleanup_loop(self):
        """Очистка старых данных."""
        while True:
            try:
                await asyncio.sleep(3600)  # Каждый час
                await self._cleanup_old_events()
                await self._reset_counters()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    async def _check_anomalies(self):
        """Проверка аномалий."""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=self.window_size)
        
        # Проверяем пользователей с большим количеством ошибок
        for user_id, error_count in self.user_error_counts.items():
            if error_count >= self.anomaly_threshold:
                anomaly = {
                    'type': 'high_error_rate',
                    'user_id': user_id,
                    'error_count': error_count,
                    'timestamp': now.isoformat()
                }
                self.anomalies.append(anomaly)
                await self._handle_anomaly(anomaly)
        
        # Проверяем циклические переходы
        user_transitions = defaultdict(list)
        for event in self.events:
            if event.timestamp > window_start:
                user_transitions[event.user_id].append((event.from_state, event.to_state))
        
        for user_id, transitions in user_transitions.items():
            if self._detect_cycles(transitions):
                anomaly = {
                    'type': 'cyclic_transitions',
                    'user_id': user_id,
                    'transitions': transitions,
                    'timestamp': now.isoformat()
                }
                self.anomalies.append(anomaly)
                await self._handle_anomaly(anomaly)
    
    def _detect_cycles(self, transitions: List[Tuple[int, int]], min_cycle_length: int = 3) -> bool:
        """Обнаружение циклических переходов."""
        if len(transitions) < min_cycle_length * 2:
            return False
        
        # Проверяем повторяющиеся паттерны
        for cycle_len in range(min_cycle_length, len(transitions) // 2 + 1):
            for start in range(len(transitions) - cycle_len * 2 + 1):
                pattern = transitions[start:start + cycle_len]
                next_pattern = transitions[start + cycle_len:start + cycle_len * 2]
                if pattern == next_pattern:
                    return True
        
        return False
    
    async def _check_performance(self):
        """Проверка производительности обработчиков."""
        slow_handlers = []
        
        for handler_name, durations in self.handler_performance.items():
            if durations:
                avg_duration = sum(durations) / len(durations)
                if avg_duration > 1000:  # Более 1 секунды
                    slow_handlers.append({
                        'handler': handler_name,
                        'avg_duration_ms': avg_duration,
                        'samples': len(durations)
                    })
        
        if slow_handlers:
            await self._notify_admins_performance(slow_handlers)
    
    async def _handle_anomaly(self, anomaly: Dict):
        """Обработка обнаруженной аномалии."""
        logger.warning(f"Anomaly detected: {anomaly}")
        
        # Временная блокировка пользователя при критических аномалиях
        if anomaly['error_count'] > self.anomaly_threshold * 2:
            self.blocked_users.add(anomaly['user_id'])
            asyncio.create_task(self._unblock_user_later(anomaly['user_id'], 300))  # 5 минут
        
        # Уведомление админов
        await self._notify_admins_anomaly(anomaly)
    
    async def _unblock_user_later(self, user_id: int, delay: int):
        """Разблокировка пользователя через заданное время."""
        await asyncio.sleep(delay)
        self.blocked_users.discard(user_id)
        logger.info(f"User {user_id} unblocked after {delay} seconds")
    
    async def _notify_admins_anomaly(self, anomaly: Dict):
        """Уведомление админов об аномалии."""
        message = f"🚨 <b>Обнаружена аномалия</b>\n\n"
        
        if anomaly['type'] == 'high_error_rate':
            message += (
                f"Тип: Высокий уровень ошибок\n"
                f"User ID: {anomaly['user_id']}\n"
                f"Ошибок: {anomaly['error_count']}\n"
            )
        elif anomaly['type'] == 'cyclic_transitions':
            message += (
                f"Тип: Циклические переходы\n"
                f"User ID: {anomaly['user_id']}\n"
                f"Паттерн обнаружен в переходах\n"
            )
        
        # Отправляем первому админу
        admin_list = admin_manager.get_admin_list()
        if admin_list:
            try:
                # Нужен доступ к bot instance
                from core.app import app
                await app.bot.send_message(admin_list[0], message, parse_mode='HTML')
            except:
                logger.error("Failed to notify admins about anomaly")
    
    async def _notify_admins_performance(self, slow_handlers: List[Dict]):
        """Уведомление о проблемах производительности."""
        message = "⚠️ <b>Медленные обработчики</b>\n\n"
        
        for handler in slow_handlers[:5]:  # Топ 5
            message += (
                f"• {handler['handler']}: "
                f"{handler['avg_duration_ms']:.0f}ms "
                f"({handler['samples']} замеров)\n"
            )
        
        admin_list = admin_manager.get_admin_list()
        if admin_list:
            try:
                from core.app import app
                await app.bot.send_message(admin_list[0], message, parse_mode='HTML')
            except:
                pass
    
    async def _update_metrics(self):
        """Обновление метрик для внешних систем."""
        metrics = self.get_current_metrics()
        
        # Можно отправить в Prometheus, Grafana, etc.
        # Пример: await push_to_prometheus(metrics)
        
        # Сохраняем локально для отладки
        await self._save_metrics(metrics)
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Получение текущих метрик."""
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        
        recent_events = [e for e in self.events if e.timestamp > hour_ago]
        
        metrics = {
            'timestamp': now.isoformat(),
            'total_transitions': len(recent_events),
            'invalid_transitions': sum(1 for e in recent_events if not e.is_valid),
            'unique_users': len(set(e.user_id for e in recent_events)),
            'blocked_users': len(self.blocked_users),
            'anomalies_detected': len(self.anomalies),
            'top_transitions': self._get_top_transitions(5),
            'error_rate': (sum(1 for e in recent_events if not e.is_valid) / len(recent_events) * 100) if recent_events else 0,
            'avg_handler_performance': self._get_avg_performance(),
        }
        
        return metrics
    
    def _get_top_transitions(self, limit: int = 5) -> List[Dict]:
        """Получение топ переходов."""
        sorted_transitions = sorted(
            self.transition_counts.items(),
            key=lambda x: x[1],
            reverse=True
        )[:limit]
        
        return [
            {
                'transition': key,
                'count': count,
                'percentage': (count / sum(self.transition_counts.values()) * 100) if self.transition_counts else 0
            }
            for key, count in sorted_transitions
        ]
    
    def _get_avg_performance(self) -> Dict[str, float]:
        """Средняя производительность обработчиков."""
        return {
            handler: sum(durations) / len(durations) if durations else 0
            for handler, durations in self.handler_performance.items()
        }
    
    async def _save_metrics(self, metrics: Dict):
        """Сохранение метрик в файл."""
        filename = f"metrics/state_metrics_{datetime.now().strftime('%Y%m%d')}.jsonl"
        
        async with aiofiles.open(filename, 'a') as f:
            await f.write(json.dumps(metrics) + '\n')
    
    async def _cleanup_old_events(self):
        """Очистка старых событий."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        
        # Удаляем события старше 24 часов
        self.events = deque(
            (e for e in self.events if e.timestamp > cutoff),
            maxlen=self.max_events
        )
        
        # Очищаем старые аномалии
        self.anomalies = [
            a for a in self.anomalies 
            if datetime.fromisoformat(a['timestamp']) > cutoff
        ]
    
    async def _reset_counters(self):
        """Сброс счетчиков ошибок."""
        # Уменьшаем счетчики ошибок на 50%
        for user_id in list(self.user_error_counts.keys()):
            self.user_error_counts[user_id] = self.user_error_counts[user_id] // 2
            if self.user_error_counts[user_id] == 0:
                del self.user_error_counts[user_id]
    
    async def save_stats(self):
        """Сохранение статистики."""
        stats = {
            'saved_at': datetime.now(timezone.utc).isoformat(),
            'total_events': len(self.events),
            'transition_counts': dict(self.transition_counts),
            'anomalies': self.anomalies,
            'metrics': self.get_current_metrics()
        }
        
        filename = f"stats/state_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        async with aiofiles.open(filename, 'w') as f:
            await f.write(json.dumps(stats, indent=2))
    
    def generate_report(self) -> str:
        """Генерация отчета для админов."""
        metrics = self.get_current_metrics()
        
        report = f"""📊 <b>Отчет мониторинга состояний</b>

📅 Период: последний час
👥 Уникальных пользователей: {metrics['unique_users']}
🔄 Всего переходов: {metrics['total_transitions']}
❌ Недопустимых переходов: {metrics['invalid_transitions']} ({metrics['error_rate']:.1f}%)
🚫 Заблокированных пользователей: {metrics['blocked_users']}
⚠️ Обнаружено аномалий: {metrics['anomalies_detected']}

<b>Топ переходов:</b>"""
        
        for transition in metrics['top_transitions']:
            report += f"\n• {transition['transition']}: {transition['count']} ({transition['percentage']:.1f}%)"
        
        return report


# Глобальный экземпляр монитора
state_monitor = StateMonitor()


# Интеграция с валидатором состояний
def enhanced_validate_state_transition(expected_states: Optional[Set[int]] = None):
    """Расширенный декоратор с мониторингом."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id if update.effective_user else 0
            handler_name = func.__name__
            start_time = datetime.now(timezone.utc)
            
            # Проверяем блокировку пользователя
            if user_id in state_monitor.blocked_users:
                logger.warning(f"Blocked user {user_id} tried to access {handler_name}")
                if update.callback_query:
                    await update.callback_query.answer(
                        "⚠️ Временная блокировка. Попробуйте через несколько минут.",
                        show_alert=True
                    )
                return ConversationHandler.END
            
            # Получаем текущее состояние
            current_state = state_validator.get_current_state(user_id)
            
            # Валидация
            is_valid = True
            error = None
            
            if expected_states and current_state not in expected_states:
                is_valid = False
                error = f"Expected {expected_states}, got {current_state}"
            
            try:
                # Вызываем оригинальную функцию
                result = await func(update, context, *args, **kwargs)
                
                # Записываем событие
                duration = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
                
                event = StateTransitionEvent(
                    user_id=user_id,
                    from_state=current_state,
                    to_state=result if isinstance(result, int) else current_state,
                    handler_name=handler_name,
                    is_valid=is_valid,
                    timestamp=start_time,
                    duration_ms=duration,
                    error=error
                )
                
                state_monitor.record_transition(event)
                
                # Обновляем состояние
                if isinstance(result, int):
                    if result == ConversationHandler.END:
                        state_validator.clear_state(user_id)
                    else:
                        state_validator.set_state(user_id, result)
                
                return result
                
            except Exception as e:
                # Записываем ошибку
                event = StateTransitionEvent(
                    user_id=user_id,
                    from_state=current_state,
                    to_state=current_state,
                    handler_name=handler_name,
                    is_valid=False,
                    timestamp=start_time,
                    error=str(e)
                )
                
                state_monitor.record_transition(event)
                raise
        
        return wrapper
    return decorator


# Команды для админов
async def monitoring_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает отчет мониторинга."""
    if not admin_manager.is_admin(update.effective_user.id):
        return
    
    report = state_monitor.generate_report()
    await update.message.reply_text(report, parse_mode='HTML')


async def monitoring_metrics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальные метрики."""
    if not admin_manager.is_admin(update.effective_user.id):
        return
    
    metrics = state_monitor.get_current_metrics()
    
    # Форматируем JSON для читаемости
    text = f"```json\n{json.dumps(metrics, indent=2, ensure_ascii=False)}\n```"
    
    # Если слишком длинный, отправляем файлом
    if len(text) > 4000:
        filename = f"metrics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(filename, 'w') as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        
        await update.message.reply_document(
            document=open(filename, 'rb'),
            caption="📊 Детальные метрики мониторинга"
        )
        
        os.remove(filename)
    else:
        await update.message.reply_text(text, parse_mode='Markdown')