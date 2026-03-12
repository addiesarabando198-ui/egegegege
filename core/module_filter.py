from telegram.ext import filters
from telegram import Update

class ModuleFilter(filters.BaseFilter):
    """Фильтр для проверки активного модуля в контексте."""
    
    def __init__(self, module_name: str):
        self.module_name = module_name
        super().__init__()
    
    def filter(self, update: Update) -> bool:
        """Проверяет, что активный модуль соответствует требуемому."""
        if not hasattr(update, '_context'):
            return False
        
        context = update._context
        active_module = context.user_data.get('active_module')
        current_module = context.user_data.get('current_module')
        
        # Проверяем оба поля для обратной совместимости
        return (active_module == self.module_name or 
                current_module == self.module_name)


def create_module_filter(module_name: str):
    """Создает фильтр для конкретного модуля."""
    return ModuleFilter(module_name)