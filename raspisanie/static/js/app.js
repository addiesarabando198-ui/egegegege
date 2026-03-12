/**
 * Общие скрипты для системы расписания
 * ГБОУ "Школа Покровский квартал"
 */

// Toast уведомления
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const id = 'toast-' + Date.now();
    const icons = {
        success: 'check-circle',
        danger: 'x-circle',
        warning: 'exclamation-triangle',
        info: 'info-circle'
    };

    const toastHtml = `
        <div id="${id}" class="toast align-items-center text-white bg-${type} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi bi-${icons[type] || 'info-circle'} me-2"></i>
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastEl = document.getElementById(id);
    const toast = new bootstrap.Toast(toastEl, { autohide: true, delay: 4000 });
    toast.show();

    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
}

// Подтверждение удаления
function confirmDelete(message) {
    return confirm(message || 'Вы уверены, что хотите удалить?');
}

// Форматирование даты
function formatDate(dateStr) {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleDateString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
    });
}

// Форматирование времени
function formatDateTime(dateStr) {
    if (!dateStr) return '—';
    const date = new Date(dateStr);
    return date.toLocaleString('ru-RU', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    });
}

// API запросы с обработкой ошибок
async function apiRequest(url, options = {}) {
    try {
        const response = await fetch(url, {
            headers: {
                'Content-Type': 'application/json',
                ...options.headers
            },
            ...options
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Ошибка сервера');
        }

        return data;
    } catch (error) {
        showToast(error.message, 'danger');
        throw error;
    }
}

// Дебаунс для поиска
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Названия дней недели
const DAYS = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница'];
const DAYS_SHORT = ['ПН', 'ВТ', 'СР', 'ЧТ', 'ПТ'];

// Время уроков
const LESSON_TIMES = [
    { num: 1, start: '8:30', end: '9:15' },
    { num: 2, start: '9:25', end: '10:10' },
    { num: 3, start: '10:25', end: '11:10' },
    { num: 4, start: '11:25', end: '12:10' },
    { num: 5, start: '12:20', end: '13:05' },
    { num: 6, start: '13:20', end: '14:05' },
    { num: 7, start: '14:15', end: '15:00' }
];

// Получение времени урока
function getLessonTime(lessonNumber) {
    const lesson = LESSON_TIMES.find(l => l.num === lessonNumber);
    return lesson ? `${lesson.start}-${lesson.end}` : '';
}

// Цвета для предметов (если не заданы)
const DEFAULT_COLORS = [
    '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
    '#1abc9c', '#e67e22', '#34495e', '#16a085', '#27ae60'
];

function getRandomColor() {
    return DEFAULT_COLORS[Math.floor(Math.random() * DEFAULT_COLORS.length)];
}

// Экспорт в Excel (простой CSV)
function exportToCSV(data, filename) {
    const BOM = '\uFEFF';
    const csv = BOM + data.map(row => row.join(';')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
}

// Валидация формы
function validateForm(formId, rules) {
    const form = document.getElementById(formId);
    if (!form) return false;

    let isValid = true;

    for (const [fieldId, rule] of Object.entries(rules)) {
        const field = document.getElementById(fieldId);
        if (!field) continue;

        const value = field.value.trim();
        let error = null;

        if (rule.required && !value) {
            error = 'Обязательное поле';
        } else if (rule.minLength && value.length < rule.minLength) {
            error = `Минимум ${rule.minLength} символов`;
        } else if (rule.pattern && !rule.pattern.test(value)) {
            error = rule.patternMessage || 'Неверный формат';
        }

        if (error) {
            field.classList.add('is-invalid');
            isValid = false;

            // Добавляем сообщение об ошибке если его нет
            let feedback = field.nextElementSibling;
            if (!feedback || !feedback.classList.contains('invalid-feedback')) {
                feedback = document.createElement('div');
                feedback.className = 'invalid-feedback';
                field.parentNode.appendChild(feedback);
            }
            feedback.textContent = error;
        } else {
            field.classList.remove('is-invalid');
        }
    }

    return isValid;
}

// Очистка валидации при вводе
document.addEventListener('input', function(e) {
    if (e.target.classList.contains('is-invalid')) {
        e.target.classList.remove('is-invalid');
    }
});

// Keyboard shortcuts
document.addEventListener('keydown', function(e) {
    // Ctrl+S - сохранение (предотвращение стандартного поведения)
    if (e.ctrlKey && e.key === 's') {
        e.preventDefault();
        const submitBtn = document.querySelector('form:not(.d-none) button[type="submit"]');
        if (submitBtn) submitBtn.click();
    }

    // Escape - закрытие модального окна
    if (e.key === 'Escape') {
        const modal = document.querySelector('.modal.show');
        if (modal) {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
        }
    }
});

// Инициализация tooltips
document.addEventListener('DOMContentLoaded', function() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function(tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
});

// Автосохранение черновиков форм в localStorage
function enableAutosave(formId, storageKey) {
    const form = document.getElementById(formId);
    if (!form) return;

    // Восстановление из localStorage
    const saved = localStorage.getItem(storageKey);
    if (saved) {
        const data = JSON.parse(saved);
        for (const [key, value] of Object.entries(data)) {
            const field = form.querySelector(`[name="${key}"], #${key}`);
            if (field) {
                if (field.type === 'checkbox') {
                    field.checked = value;
                } else {
                    field.value = value;
                }
            }
        }
    }

    // Сохранение при изменении
    form.addEventListener('change', debounce(function() {
        const data = {};
        const formData = new FormData(form);
        for (const [key, value] of formData.entries()) {
            data[key] = value;
        }
        localStorage.setItem(storageKey, JSON.stringify(data));
    }, 500));

    // Очистка при успешной отправке
    form.addEventListener('submit', function() {
        localStorage.removeItem(storageKey);
    });
}

// Печать расписания
function printSchedule() {
    window.print();
}

console.log('Schedule App initialized');
