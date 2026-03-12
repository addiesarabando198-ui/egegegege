/**
 * Компонент браузера вопросов
 * Показывает список вопросов с поиском и пагинацией
 */

import { api } from '../api.js';
import { EventEmitter } from '../utils/EventEmitter.js';
import { debounce } from '../utils/formatters.js';
import { showToast, showEmptyState, createSpinner } from '../utils/ui.js';

export class QuestionBrowser extends EventEmitter {
  constructor(container) {
    super();
    this.container = container;
    this.moduleCode = null;
    this.selectedIds = new Set();
    this.questions = [];
    this.currentPage = 1;
    this.pageSize = 20;
    this.totalQuestions = 0;
    this.searchQuery = '';
  }

  /**
   * Инициализация браузера
   * @param {string} moduleCode
   * @param {Array} preselectedIds - предвыбранные вопросы
   */
  async init(moduleCode, preselectedIds = []) {
    this.moduleCode = moduleCode;
    this.selectedIds = new Set(preselectedIds);

    this.render();
    await this.loadQuestions();
  }

  /**
   * Рендерит структуру браузера
   */
  render() {
    this.container.innerHTML = `
      <div class="question-browser">
        <div class="browser-controls">
          <input type="search"
                 class="form-input"
                 id="question-search"
                 placeholder="🔍 Поиск по тексту вопроса...">
        </div>

        <div class="question-list" id="question-list">
          ${createSpinner().outerHTML}
        </div>

        <div class="pagination" id="pagination" style="display: none;">
          <button class="btn-secondary" id="prev-page" disabled>← Назад</button>
          <span>Страница <span id="current-page">1</span> из <span id="total-pages">1</span></span>
          <button class="btn-secondary" id="next-page">Вперед →</button>
        </div>

        <div class="browser-info">
          Выбрано вопросов: <strong id="selected-count">0</strong>
        </div>
      </div>
    `;

    this.setupEventListeners();
  }

  /**
   * Настраивает обработчики событий
   */
  setupEventListeners() {
    const searchInput = this.container.querySelector('#question-search');
    if (searchInput) {
      searchInput.addEventListener('input', debounce((e) => {
        this.searchQuery = e.target.value;
        this.currentPage = 1;
        this.loadQuestions();
      }, 500));
    }

    const prevBtn = this.container.querySelector('#prev-page');
    if (prevBtn) {
      prevBtn.addEventListener('click', () => {
        if (this.currentPage > 1) {
          this.currentPage--;
          this.loadQuestions();
        }
      });
    }

    const nextBtn = this.container.querySelector('#next-page');
    if (nextBtn) {
      nextBtn.addEventListener('click', () => {
        const totalPages = Math.ceil(this.totalQuestions / this.pageSize);
        if (this.currentPage < totalPages) {
          this.currentPage++;
          this.loadQuestions();
        }
      });
    }
  }

  /**
   * Загружает вопросы с сервера
   */
  async loadQuestions() {
    try {
      const response = await api.getQuestions({
        module: this.moduleCode,
        search: this.searchQuery,
        limit: this.pageSize,
        offset: (this.currentPage - 1) * this.pageSize
      });

      this.questions = response.questions || [];
      this.totalQuestions = response.total || 0;

      this.renderQuestions();
      this.updatePagination();

    } catch (error) {
      console.error('Failed to load questions:', error);
      showToast('Ошибка загрузки вопросов', 'error');
      this.renderError();
    }
  }

  /**
   * Рендерит список вопросов
   */
  renderQuestions() {
    const listContainer = this.container.querySelector('#question-list');
    if (!listContainer) return;

    if (this.questions.length === 0) {
      showEmptyState(listContainer, {
        icon: '🔍',
        title: 'Вопросы не найдены',
        description: this.searchQuery ? 'Попробуйте изменить поисковый запрос' : ''
      });
      return;
    }

    const html = this.questions.map(q => `
      <div class="question-card ${this.selectedIds.has(q.id) ? 'selected' : ''}"
           data-id="${q.id}">
        <input type="checkbox"
               data-id="${q.id}"
               ${this.selectedIds.has(q.id) ? 'checked' : ''}>
        <div class="question-content">
          <span class="question-number">#${q.number || q.id}</span>
          <p class="question-text">${this.truncateText(q.text, 150)}</p>
          ${q.topic ? `<span class="question-topic">${q.topic}</span>` : ''}
        </div>
      </div>
    `).join('');

    listContainer.innerHTML = html;

    // Добавляем обработчики для карточек
    listContainer.querySelectorAll('.question-card').forEach(card => {
      card.addEventListener('click', (e) => {
        const questionId = card.dataset.id;
        const checkbox = card.querySelector('input[type="checkbox"]');

        // Если клик был не по checkbox, переключаем его
        if (e.target !== checkbox) {
          checkbox.checked = !checkbox.checked;
        }

        this.toggleSelection(questionId, checkbox.checked);
      });

      const checkbox = card.querySelector('input[type="checkbox"]');
      checkbox.addEventListener('change', (e) => {
        e.stopPropagation();
        this.toggleSelection(card.dataset.id, e.target.checked);
      });
    });

    this.updateCounter();
  }

  /**
   * Рендерит ошибку
   */
  renderError() {
    const listContainer = this.container.querySelector('#question-list');
    if (!listContainer) return;

    showEmptyState(listContainer, {
      icon: '⚠️',
      title: 'Ошибка загрузки',
      description: 'Не удалось загрузить вопросы'
    });
  }

  /**
   * Обновляет пагинацию
   */
  updatePagination() {
    const paginationContainer = this.container.querySelector('#pagination');
    if (!paginationContainer) return;

    const totalPages = Math.ceil(this.totalQuestions / this.pageSize);

    if (totalPages <= 1) {
      paginationContainer.style.display = 'none';
      return;
    }

    paginationContainer.style.display = 'flex';

    const currentPageSpan = paginationContainer.querySelector('#current-page');
    const totalPagesSpan = paginationContainer.querySelector('#total-pages');
    const prevBtn = paginationContainer.querySelector('#prev-page');
    const nextBtn = paginationContainer.querySelector('#next-page');

    if (currentPageSpan) currentPageSpan.textContent = this.currentPage;
    if (totalPagesSpan) totalPagesSpan.textContent = totalPages;

    if (prevBtn) {
      prevBtn.disabled = this.currentPage === 1;
    }

    if (nextBtn) {
      nextBtn.disabled = this.currentPage === totalPages;
    }
  }

  /**
   * Переключает выбор вопроса
   * @param {string} questionId
   * @param {boolean} selected
   */
  toggleSelection(questionId, selected) {
    if (selected) {
      this.selectedIds.add(questionId);
    } else {
      this.selectedIds.delete(questionId);
    }

    // Обновляем UI карточки
    const card = this.container.querySelector(`.question-card[data-id="${questionId}"]`);
    if (card) {
      card.classList.toggle('selected', selected);
    }

    this.updateCounter();
    this.emit('change', Array.from(this.selectedIds));
  }

  /**
   * Обновляет счетчик выбранных вопросов
   */
  updateCounter() {
    const counter = this.container.querySelector('#selected-count');
    if (counter) {
      counter.textContent = this.selectedIds.size;
    }
  }

  /**
   * Обрезает текст
   * @param {string} text
   * @param {number} maxLength
   * @returns {string}
   */
  truncateText(text, maxLength) {
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength) + '...';
  }

  /**
   * Получает выбранные ID
   * @returns {Array}
   */
  getSelectedIds() {
    return Array.from(this.selectedIds);
  }

  /**
   * Устанавливает выбранные ID
   * @param {Array} ids
   */
  setSelectedIds(ids) {
    this.selectedIds = new Set(ids);
    this.updateCounter();
    this.renderQuestions();
  }

  /**
   * Очищает выбор
   */
  clearSelection() {
    this.selectedIds.clear();
    this.updateCounter();
    this.renderQuestions();
    this.emit('change', []);
  }

  /**
   * Уничтожает компонент
   */
  destroy() {
    this.container.innerHTML = '';
  }
}
