/**
 * Компонент выбора учеников
 * Показывает список учеников с поиском и множественным выбором
 */

import { EventEmitter } from '../utils/EventEmitter.js';
import { debounce } from '../utils/formatters.js';
import { showEmptyState } from '../utils/ui.js';

export class StudentSelector extends EventEmitter {
  constructor(container) {
    super();
    this.container = container;
    this.students = [];
    this.filteredStudents = [];
    this.selectedIds = new Set();
    this.searchQuery = '';
  }

  /**
   * Инициализация компонента
   * @param {Array} students - список учеников
   */
  async init(students) {
    this.students = students;
    this.filteredStudents = students;

    this.render();
    this.renderStudents();
  }

  /**
   * Рендерит структуру компонента
   */
  render() {
    this.container.innerHTML = `
      <div class="student-selector">
        <input type="search"
               class="form-input mb-md"
               id="student-search"
               placeholder="🔍 Поиск по имени или username...">

        <div class="quick-actions mb-md">
          <button class="btn-secondary" id="select-all">Выбрать всех</button>
          <button class="btn-secondary" id="select-none">Снять выбор</button>
        </div>

        <div class="student-list" id="student-list"></div>

        <div class="selector-info mt-md">
          Выбрано учеников: <strong id="selected-students-count">0</strong>
        </div>
      </div>
    `;

    this.setupEventListeners();
  }

  /**
   * Настраивает обработчики событий
   */
  setupEventListeners() {
    const searchInput = this.container.querySelector('#student-search');
    if (searchInput) {
      searchInput.addEventListener('input', debounce((e) => {
        this.searchQuery = e.target.value.toLowerCase();
        this.filterStudents();
        this.renderStudents();
      }, 300));
    }

    const selectAllBtn = this.container.querySelector('#select-all');
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => this.selectAll());
    }

    const selectNoneBtn = this.container.querySelector('#select-none');
    if (selectNoneBtn) {
      selectNoneBtn.addEventListener('click', () => this.selectNone());
    }
  }

  /**
   * Фильтрует учеников по поисковому запросу
   */
  filterStudents() {
    if (!this.searchQuery) {
      this.filteredStudents = this.students;
      return;
    }

    this.filteredStudents = this.students.filter(student => {
      const name = (student.name || '').toLowerCase();
      const username = (student.username || '').toLowerCase();
      return name.includes(this.searchQuery) || username.includes(this.searchQuery);
    });
  }

  /**
   * Рендерит список учеников
   */
  renderStudents() {
    const listContainer = this.container.querySelector('#student-list');
    if (!listContainer) return;

    if (this.filteredStudents.length === 0) {
      if (this.students.length === 0) {
        showEmptyState(listContainer, {
          icon: '👥',
          title: 'У вас пока нет учеников',
          description: 'Пригласите учеников подключиться к вам через код учителя'
        });
      } else {
        showEmptyState(listContainer, {
          icon: '🔍',
          title: 'Ученики не найдены',
          description: 'Попробуйте изменить поисковый запрос'
        });
      }
      return;
    }

    const html = this.filteredStudents.map(student => `
      <div class="student-card ${this.selectedIds.has(student.user_id) ? 'selected' : ''}"
           data-id="${student.user_id}">
        <input type="checkbox"
               data-id="${student.user_id}"
               ${this.selectedIds.has(student.user_id) ? 'checked' : ''}>
        <div class="student-info">
          <div class="student-name">${this.escapeHTML(student.name || 'Безымянный')}</div>
          ${student.username ? `<div class="student-username">@${student.username}</div>` : ''}
          ${student.stats ? `
            <div class="student-stats">
              <span>Выполнено: ${student.stats.completed_assignments || 0}</span>
              <span>Средний балл: ${(student.stats.average_score || 0).toFixed(1)}%</span>
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');

    listContainer.innerHTML = html;

    // Добавляем обработчики
    listContainer.querySelectorAll('.student-card').forEach(card => {
      card.addEventListener('click', (e) => {
        const studentId = parseInt(card.dataset.id);
        const checkbox = card.querySelector('input[type="checkbox"]');

        if (e.target !== checkbox) {
          checkbox.checked = !checkbox.checked;
        }

        this.toggleSelection(studentId, checkbox.checked);
      });

      const checkbox = card.querySelector('input[type="checkbox"]');
      checkbox.addEventListener('change', (e) => {
        e.stopPropagation();
        this.toggleSelection(parseInt(card.dataset.id), e.target.checked);
      });
    });

    this.updateCounter();
  }

  /**
   * Переключает выбор ученика
   * @param {number} studentId
   * @param {boolean} selected
   */
  toggleSelection(studentId, selected) {
    if (selected) {
      this.selectedIds.add(studentId);
    } else {
      this.selectedIds.delete(studentId);
    }

    // Обновляем UI карточки
    const card = this.container.querySelector(`.student-card[data-id="${studentId}"]`);
    if (card) {
      card.classList.toggle('selected', selected);
    }

    this.updateCounter();
    this.emit('change', Array.from(this.selectedIds));
  }

  /**
   * Выбирает всех учеников (из отфильтрованного списка)
   */
  selectAll() {
    this.filteredStudents.forEach(student => {
      this.selectedIds.add(student.id);
    });

    this.renderStudents();
    this.emit('change', Array.from(this.selectedIds));
  }

  /**
   * Снимает выбор со всех
   */
  selectNone() {
    this.selectedIds.clear();
    this.renderStudents();
    this.emit('change', []);
  }

  /**
   * Обновляет счетчик выбранных учеников
   */
  updateCounter() {
    const counter = this.container.querySelector('#selected-students-count');
    if (counter) {
      counter.textContent = this.selectedIds.size;
    }
  }

  /**
   * Получает выбранные ID
   * @returns {Array}
   */
  getSelected() {
    return Array.from(this.selectedIds);
  }

  /**
   * Устанавливает выбранные ID
   * @param {Array} ids
   */
  setSelected(ids) {
    this.selectedIds = new Set(ids);
    this.renderStudents();
    this.emit('change', Array.from(this.selectedIds));
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
    this.container.innerHTML = '';
  }
}
