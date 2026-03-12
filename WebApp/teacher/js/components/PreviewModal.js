/**
 * Модальное окно предпросмотра задания
 * Показывает финальный вид задания перед отправкой
 */

import { formatDate, formatAssignmentType, formatCount } from '../utils/formatters.js';
import { hideModal, showModal } from '../utils/ui.js';

export class PreviewModal {
  constructor(modalElement) {
    this.modal = modalElement;
    this.state = null;
    this.assignmentData = null;
  }

  /**
   * Показывает предпросмотр
   * @param {Object} state - состояние формы
   * @param {Object} assignmentData - данные для отправки
   */
  show(state, assignmentData) {
    this.state = state;
    this.assignmentData = assignmentData;

    this.render();
    showModal(this.modal.id);
    this.setupEventListeners();
  }

  /**
   * Рендерит содержимое модального окна
   */
  render() {
    const body = this.modal.querySelector('.modal-body');
    if (!body) return;

    const {
      title,
      description,
      assignmentType,
      studentIds,
      modules,
      deadline
    } = this.assignmentData;

    // Подсчитываем общее количество вопросов
    const totalQuestions = this.calculateTotalQuestions(modules);

    body.innerHTML = `
      <div class="preview-content">
        <h3 class="mb-md">${this.escapeHTML(title)}</h3>

        ${description ? `<p class="text-muted mb-lg">${this.escapeHTML(description)}</p>` : ''}

        <div class="preview-info mb-lg">
          <div class="info-item">
            <span class="label">Тип задания</span>
            <div class="value">${formatAssignmentType(assignmentType)}</div>
          </div>

          <div class="info-item">
            <span class="label">Вопросов</span>
            <div class="value">${totalQuestions}</div>
          </div>

          <div class="info-item">
            <span class="label">Учеников</span>
            <div class="value">${formatCount(studentIds.length, 'ученик', 'ученика', 'учеников')}</div>
          </div>

          <div class="info-item">
            <span class="label">Дедлайн</span>
            <div class="value">${deadline ? formatDate(deadline) : 'Без дедлайна'}</div>
          </div>
        </div>

        ${this.renderModulesInfo(modules, assignmentType)}

        <div class="preview-warning mt-lg">
          <p class="text-muted" style="font-size: 0.9rem;">
            ℹ️ После создания задание будет автоматически отправлено всем выбранным ученикам.
          </p>
        </div>
      </div>
    `;
  }

  /**
   * Рендерит информацию о модулях
   * @param {Array} modules
   * @param {string} assignmentType
   * @returns {string}
   */
  renderModulesInfo(modules, assignmentType) {
    if (assignmentType === 'full_exam') {
      return `
        <div class="preview-modules">
          <h4 class="mb-md">Состав задания:</h4>
          <p class="text-muted">Полный вариант ЕГЭ будет сгенерирован автоматически (20 заданий).</p>
        </div>
      `;
    }

    if (!modules || modules.length === 0) {
      return '';
    }

    const modulesHTML = modules.map(module => {
      let details = '';

      if (module.selection_mode === 'all') {
        details = 'Все доступные вопросы';
      } else if (module.selection_mode === 'random') {
        details = `${module.question_count} случайных вопросов`;
      } else if (module.selection_mode === 'specific') {
        details = `${module.question_ids.length} выбранных вопросов`;
      }

      return `
        <li>
          <strong>${this.getModuleName(module.module_code)}</strong>: ${details}
        </li>
      `;
    }).join('');

    return `
      <div class="preview-modules">
        <h4 class="mb-md">Состав задания:</h4>
        <ul class="preview-modules-list">
          ${modulesHTML}
        </ul>
      </div>
    `;
  }

  /**
   * Подсчитывает общее количество вопросов
   * @param {Array} modules
   * @returns {number}
   */
  calculateTotalQuestions(modules) {
    if (!modules || modules.length === 0) return 0;

    return modules.reduce((total, module) => {
      if (module.selection_mode === 'specific') {
        return total + module.question_ids.length;
      } else if (module.selection_mode === 'random') {
        return total + (module.question_count || 0);
      } else {
        // Для режима "all" нужно знать количество из модуля
        // В упрощенной версии возвращаем примерное значение
        return total;
      }
    }, 0);
  }

  /**
   * Настраивает обработчики событий
   */
  setupEventListeners() {
    const closeBtn = this.modal.querySelector('#preview-close-btn');
    if (closeBtn) {
      closeBtn.onclick = () => this.hide();
    }

    const editBtn = this.modal.querySelector('#preview-edit-btn');
    if (editBtn) {
      editBtn.onclick = () => this.hide();
    }

    // Кнопка подтверждения обрабатывается в main.js
  }

  /**
   * Скрывает модальное окно
   */
  hide() {
    hideModal(this.modal.id);
  }

  /**
   * Получает название модуля
   * @param {string} code
   * @returns {string}
   */
  getModuleName(code) {
    const names = {
      'test_part': '📝 Тестовая часть (1-16)',
      'task19': '💡 Задание 19',
      'task20': '⚙️ Задание 20',
      'task24': '📊 Задание 24',
      'task25': '💻 Задание 25'
    };
    return names[code] || code;
  }

  /**
   * Экранирует HTML
   * @param {string} str
   * @returns {string}
   */
  escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  /**
   * Уничтожает компонент
   */
  destroy() {
    this.hide();
  }
}
