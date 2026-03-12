"""
core/state_validator.py
Система валидации переходов между состояниями FSM.
"""

import logging
from typing import Dict, Set, Optional, Callable, Any
from functools import wraps
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from core import states

logger = logging.getLogger(__name__)


class StateTransitionValidator:
    """Валидатор переходов между состояниями."""
    
    def __init__(self):
        # Определяем допустимые переходы между состояниями
        self.allowed_transitions: Dict[int, Set[int]] = {
            # Из CHOOSING_MODE можно перейти в любое состояние начала задания
            states.CHOOSING_MODE: {
                states.CHOOSING_BLOCK,
                states.CHOOSING_TOPIC,
                states.CHOOSING_EXAM_NUMBER,
                states.ANSWERING,
                states.CHOOSING_NEXT_ACTION,
                states.REVIEWING_MISTAKES,
                states.ANSWERING_PARTS,
                states.CHOOSING_BLOCK_T25,
                states.EXAM_MODE,
                ConversationHandler.END
            },
            
            # Из CHOOSING_BLOCK можно выбрать тему или вернуться
            states.CHOOSING_BLOCK: {
                states.CHOOSING_TOPIC,
                states.CHOOSING_MODE,
                states.ANSWERING,
                ConversationHandler.END
            },
            
            # Из CHOOSING_TOPIC можно начать отвечать или вернуться
            states.CHOOSING_TOPIC: {
                states.ANSWERING,
                states.CHOOSING_BLOCK,
                states.CHOOSING_MODE,
                ConversationHandler.END
            },
            
            # Из ANSWERING можно перейти к следующему действию
            states.ANSWERING: {
                states.CHOOSING_NEXT_ACTION,
                states.CHOOSING_MODE,
                states.CHOOSING_TOPIC,
                ConversationHandler.END
            },
            
            # Из CHOOSING_NEXT_ACTION можно продолжить или завершить
            states.CHOOSING_NEXT_ACTION: {
                states.ANSWERING,
                states.CHOOSING_MODE,
                states.CHOOSING_TOPIC,
                states.REVIEWING_MISTAKES,
                ConversationHandler.END
            },
            
            # Из REVIEWING_MISTAKES можно отвечать или вернуться
            states.REVIEWING_MISTAKES: {
                states.ANSWERING,
                states.CHOOSING_MODE,
                states.CHOOSING_NEXT_ACTION,
                ConversationHandler.END
            },
            
            # Для задания 25 с частями
            states.ANSWERING_PARTS: {
                states.CHOOSING_NEXT_ACTION,
                states.CHOOSING_MODE,
                ConversationHandler.END
            },
            
            # Специальные состояния для task25
            states.CHOOSING_BLOCK_T25: {
                states.CHOOSING_TOPIC,
                states.CHOOSING_MODE,
                states.ANSWERING_PARTS,
                ConversationHandler.END
            },
                        # ДОБАВИТЬ: Состояние для задания 20
            states.ANSWERING_T20: {
                states.CHOOSING_MODE,           # После ответа можно вернуться в меню
                states.CHOOSING_NEXT_ACTION,    # Или выбрать следующее действие
                states.ANSWERING_T20,          # Или повторить попытку
                ConversationHandler.END
            },
            
            # ДОБАВИТЬ: Состояние для задания 19
            states.TASK19_WAITING: {
                states.CHOOSING_MODE,
                states.CHOOSING_NEXT_ACTION,
                states.TASK19_WAITING,
                ConversationHandler.END
            },
            
            # ДОБАВИТЬ: Состояние для задания 25
            states.TASK25_WAITING: {
                states.CHOOSING_MODE,
                states.CHOOSING_NEXT_ACTION,
                states.TASK25_WAITING,
                ConversationHandler.END
            },

            # Режим экзамена
            states.EXAM_MODE: {
                states.EXAM_MODE,              # Переход к следующему вопросу
                states.CHOOSING_MODE,          # Завершение или отмена экзамена
                states.CHOOSING_NEXT_ACTION,   # После завершения экзамена
                ConversationHandler.END
            },
        }
        
        # Хранилище текущих состояний пользователей
        self.user_states: Dict[int, int] = {}
        
        # Статистика переходов для отладки
        self.transition_stats: Dict[str, int] = {}
    
    def is_valid_transition(self, user_id: int, from_state: int, to_state: int) -> bool:
        """Проверяет, допустим ли переход между состояниями."""
        # Специальные случаи
        if from_state == ConversationHandler.END:
            # Из END можно начать новый диалог
            return True
        
        if to_state == ConversationHandler.END:
            # В END можно перейти из любого состояния
            return True
        
        # Проверяем допустимые переходы
        allowed = self.allowed_transitions.get(from_state, set())
        return to_state in allowed
    
    def log_transition(self, user_id: int, from_state: int, to_state: int, handler_name: str):
        """Логирует переход между состояниями."""
        transition_key = f"{self._state_name(from_state)}->{self._state_name(to_state)}"
        self.transition_stats[transition_key] = self.transition_stats.get(transition_key, 0) + 1
        
        if not self.is_valid_transition(user_id, from_state, to_state):
            logger.warning(
                f"Invalid state transition for user {user_id}: "
                f"{self._state_name(from_state)} -> {self._state_name(to_state)} "
                f"in handler {handler_name}"
            )
    
    def get_current_state(self, user_id: int) -> Optional[int]:
        """Получает текущее состояние пользователя."""
        return self.user_states.get(user_id)
    
    def set_state(self, user_id: int, state: int):
        """Устанавливает состояние пользователя."""
        self.user_states[user_id] = state
    
    def clear_state(self, user_id: int):
        """Очищает состояние пользователя."""
        self.user_states.pop(user_id, None)
    
    def _state_name(self, state: int) -> str:
        """Получает имя состояния для логирования."""
        if state == ConversationHandler.END:
            return "END"
        
        # Ищем имя в модуле states
        for name, value in vars(states).items():
            if value == state and name.isupper():
                return name
        
        return f"STATE_{state}"
    
    def get_stats(self) -> Dict[str, Any]:
        """Получает статистику переходов."""
        return {
            "total_transitions": sum(self.transition_stats.values()),
            "unique_transitions": len(self.transition_stats),
            "top_transitions": sorted(
                self.transition_stats.items(),
                key=lambda x: x[1],
                reverse=True
            )[:10],
            "active_users": len(self.user_states)
        }


# Глобальный экземпляр валидатора
state_validator = StateTransitionValidator()


def validate_state_transition(expected_states: Optional[Set[int]] = None):
    """
    Декоратор для валидации переходов состояний.
    
    Args:
        expected_states: Множество ожидаемых входных состояний
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id if update.effective_user else 0
            handler_name = func.__name__
            
            # Получаем текущее состояние
            current_state = state_validator.get_current_state(user_id)
            
            # Проверяем, если заданы ожидаемые состояния
            if expected_states and current_state not in expected_states:
                logger.warning(
                    f"Handler {handler_name} called from unexpected state: "
                    f"{state_validator._state_name(current_state)} "
                    f"(expected: {[state_validator._state_name(s) for s in expected_states]})"
                )
            
            # Вызываем оригинальную функцию
            result = await func(update, context, *args, **kwargs)
            
            # Логируем переход
            if isinstance(result, int):
                state_validator.log_transition(
                    user_id,
                    current_state or ConversationHandler.END,
                    result,
                    handler_name
                )
                
                # Обновляем состояние
                if result == ConversationHandler.END:
                    state_validator.clear_state(user_id)
                else:
                    state_validator.set_state(user_id, result)
            
            return result
        
        return wrapper
    return decorator


# Функция для восстановления состояния после ошибки
async def recover_user_state(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Восстанавливает пользователя в безопасное состояние после ошибки."""
    user_id = update.effective_user.id if update.effective_user else 0
    
    # Очищаем текущее состояние
    state_validator.clear_state(user_id)
    
    # Очищаем данные контекста
    context.user_data.clear()
    
    # Возвращаем в главное меню
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🏠 В главное меню", callback_data="to_main_menu")
    ]])
    
    message = "Произошла ошибка. Данные сброшены, можете начать заново."
    
    if update.callback_query:
        await update.callback_query.message.reply_text(message, reply_markup=kb)
    elif update.message:
        await update.message.reply_text(message, reply_markup=kb)
    
    return states.CHOOSING_MODE