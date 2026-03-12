/**
 * Компонент формы создания задания
 * Главный компонент, управляющий всем процессом создания задания
 */

import { api } from '../api.js';
import { validateAssignmentForm, attachLiveValidation, titleValidator, descriptionValidator } from '../utils/validation.js';
import { showToast, updateProgress, toggle, showEmptyState } from '../utils/ui.js';
import { draftManager } from '../utils/storage.js';
import { debounce } from '../utils/formatters.js';
import { QuestionBrowser } from './QuestionBrowser.js';
import { StudentSelector } from './StudentSelector.js';
import { PreviewModal } from './PreviewModal.js';

export class AssignmentForm {
  constructor(container) {
    this.container = container;

    // Состояние формы
    this.state = {
      assignmentType: null,
      modules: [],
      title: '',
      description: '',
      studentIds: [],
      deadline: null
    };

    // Компоненты
    this.questionBrowser = null;
    this.studentSelector = null;
    this.previewModal = null;

    // Флаги
    this.initialized = false;
    this.hasChanges = false;
    this.autoSaveInterval = null;

    // Данные с сервера
    this.availableModules = [];
    this.students = [];
  }

  /**
   * Инициализация компонента
   */
  async init() {
    console.log('Initializing AssignmentForm...');

    try {
      // Загружаем данные с сервера
      await this.loadData();

      // Настраиваем обработчики событий
      this.setupEventListeners();

      // Настраиваем валидацию
      this.setupValidation();

      // Запускаем автосохранение
      this.startAutoSave();

      // Создаем компоненты
      this.studentSelector = new StudentSelector(
        document.getElementById('student-selector-content')
      );
      await this.studentSelector.init(this.students);

      // Подписываемся на изменения StudentSelector ПОСЛЕ его создания
      this.studentSelector.on('change', (selectedIds) => {
        this.state.studentIds = selectedIds;
        console.log('[AssignmentForm] Students changed:', selectedIds);
        this.markAsChanged();
        this.updateCreateButton();
      });

      this.previewModal = new PreviewModal(
        document.getElementById('preview-modal')
      );

      this.initialized = true;
      console.log('AssignmentForm initialized');

    } catch (error) {
      console.error('AssignmentForm initialization error:', error);
      showToast('Ошибка инициализации формы', 'error');
    }
  }

  /**
   * Загружает данные с сервера
   */
  async loadData() {
    try {
      // Загружаем модули и учеников параллельно
      const [modulesResponse, studentsResponse] = await Promise.all([
        api.getModules(),
        api.getStudents({ limit: 100 })
      ]);

      this.availableModules = modulesResponse.modules || [];
      this.students = studentsResponse.students || [];

      console.log('Data loaded:', {
        modules: this.availableModules.length,
        students: this.students.length
      });

    } catch (error) {
      console.error('Failed to load data:', error);
      throw error;
    }
  }

  /**
   * Настраивает обработчики событий
   */
  setupEventListeners() {
    // Обработчики выбора типа задания
    const typeCards = this.container.querySelectorAll('.type-card');
    typeCards.forEach(card => {
      card.addEventListener('click', () => {
        const type = card.dataset.type;
        this.handleTypeSelection(type);
      });
    });

    // Обработчики полей формы
    const titleInput = document.getElementById('assignment-title');
    if (titleInput) {
      titleInput.addEventListener('input', (e) => {
        this.state.title = e.target.value;
        this.markAsChanged();
      });
    }

    const descriptionInput = document.getElementById('assignment-description');
    if (descriptionInput) {
      descriptionInput.addEventListener('input', (e) => {
        this.state.description = e.target.value;
        this.markAsChanged();
      });
    }

    // Обработчики дедлайна
    const deadlineQuickButtons = document.querySelectorAll('.deadline-quick-btn');
    deadlineQuickButtons.forEach(btn => {
      btn.addEventListener('click', () => {
        const days = parseInt(btn.dataset.days);
        this.setDeadlineFromDays(days);
        this.updateDeadlineButtons(btn);
      });
    });

    const deadlineInput = document.getElementById('deadline-input');
    if (deadlineInput) {
      deadlineInput.addEventListener('change', (e) => {
        this.state.deadline = e.target.value;
        this.markAsChanged();
        this.updateDeadlineButtons(null);
      });
    }

    const noDeadlineCheckbox = document.getElementById('no-deadline');
    if (noDeadlineCheckbox) {
      noDeadlineCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) {
          this.state.deadline = null;
          if (deadlineInput) {
            deadlineInput.value = '';
            deadlineInput.disabled = true;
          }
          this.updateDeadlineButtons(null);
        } else {
          if (deadlineInput) {
            deadlineInput.disabled = false;
          }
        }
        this.markAsChanged();
      });
    }

    // УДАЛЕНО: Подписка перенесена в init() после создания studentSelector
  }

  /**
   * Настраивает валидацию полей
   */
  setupValidation() {
    const titleInput = document.getElementById('assignment-title');
    if (titleInput) {
      attachLiveValidation(titleInput, titleValidator);
    }

    const descriptionInput = document.getElementById('assignment-description');
    if (descriptionInput) {
      attachLiveValidation(descriptionInput, descriptionValidator);
    }
  }

  /**
   * Обрабатывает выбор типа задания
   * @param {string} type
   */
  async handleTypeSelection(type) {
    console.log('Type selected:', type);

    // Обновляем UI
    const typeCards = this.container.querySelectorAll('.type-card');
    typeCards.forEach(card => {
      card.classList.toggle('selected', card.dataset.type === type);
    });

    // Обновляем состояние
    this.state.assignmentType = type;
    this.markAsChanged();

    // Показываем следующие секции
    toggle('#question-selection-section', true);
    toggle('#details-section', true);
    toggle('#students-section', true);
    toggle('#deadline-section', true);

    // Обновляем прогресс
    updateProgress(2);

    // Загружаем интерфейс выбора вопросов
    await this.loadQuestionSelection(type);

    // Обновляем кнопку создания
    this.updateCreateButton();
  }

  /**
   * Загружает интерфейс выбора вопросов
   * @param {string} type
   */
  async loadQuestionSelection(type) {
    const container = document.getElementById('question-selection-content');
    if (!container) return;

    try {
      // Для смешанного типа показываем выбор модулей
      if (type === 'mixed') {
        await this.renderModuleSelection(container);
      }
      // Для конкретного модуля показываем браузер вопросов
      else if (['test_part', 'task19', 'task20', 'task24', 'task25'].includes(type)) {
        await this.renderQuestionBrowser(container, type);
      }
      // Для полного варианта ничего не показываем (автоматически генерируется)
      else if (type === 'full_exam') {
        container.innerHTML = `
          <p class="text-muted">Полный вариант ЕГЭ будет сгенерирован автоматически.</p>
        `;
      }

    } catch (error) {
      console.error('Failed to load question selection:', error);
      showToast('Ошибка загрузки вопросов', 'error');
    }
  }

  /**
   * Рендерит выбор модулей (для смешанного типа)
   * @param {HTMLElement} container
   */
  async renderModuleSelection(container) {
    container.innerHTML = `
      <div class="module-selector" id="module-selector">
        <p class="mb-md">Выберите модули для включения в задание:</p>
        <div id="module-list"></div>
      </div>
    `;

    const moduleList = container.querySelector('#module-list');

    this.availableModules.forEach(module => {
      const moduleItem = document.createElement('div');
      moduleItem.className = 'module-item';
      moduleItem.dataset.moduleCode = module.code;

      moduleItem.innerHTML = `
        <div class="module-header">
          <input type="checkbox" id="module-${module.code}" value="${module.code}">
          <label for="module-${module.code}" class="module-title">${module.name}</label>
          <span class="module-count">${module.total_questions} вопросов</span>
        </div>
        <div class="module-details">
          <div class="form-group">
            <label class="form-label">Способ отбора:</label>
            <select class="form-input module-selection-mode" data-module="${module.code}">
              <option value="random">Случайные вопросы</option>
              <option value="specific">Конкретные вопросы</option>
              <option value="all">Все вопросы</option>
            </select>
          </div>
          <div class="form-group module-count-group">
            <label class="form-label">Количество вопросов:</label>
            <input type="number" class="form-input module-question-count"
                   data-module="${module.code}"
                   min="1" max="${module.total_questions}"
                   placeholder="Введите количество">
          </div>
          <div class="form-group module-specific-group" style="display: none;">
            <button class="btn-secondary browse-questions-btn"
                    data-module="${module.code}">
              Выбрать вопросы
            </button>
            <div class="selected-questions-info" data-module="${module.code}">
              Выбрано: <strong>0</strong> вопросов
            </div>
          </div>
        </div>
      `;

      moduleList.appendChild(moduleItem);
    });

    // Настраиваем обработчики для модулей
    this.setupModuleEventListeners(container);
  }

  /**
   * Настраивает обработчики для модулей
   * @param {HTMLElement} container
   */
  setupModuleEventListeners(container) {
    // Обработчик checkbox модулей
    container.querySelectorAll('.module-item input[type="checkbox"]').forEach(checkbox => {
      checkbox.addEventListener('change', (e) => {
        const moduleItem = e.target.closest('.module-item');
        const moduleCode = e.target.value;

        if (e.target.checked) {
          moduleItem.classList.add('selected');
          this.addModule(moduleCode);
        } else {
          moduleItem.classList.remove('selected');
          this.removeModule(moduleCode);
        }

        this.markAsChanged();
        this.updateCreateButton();
      });
    });

    // Обработчик изменения режима отбора
    container.querySelectorAll('.module-selection-mode').forEach(select => {
      select.addEventListener('change', (e) => {
        const moduleCode = e.target.dataset.module;
        const mode = e.target.value;
        const moduleItem = e.target.closest('.module-item');

        // Показываем/скрываем соответствующие поля
        const countGroup = moduleItem.querySelector('.module-count-group');
        const specificGroup = moduleItem.querySelector('.module-specific-group');

        if (mode === 'specific') {
          countGroup.style.display = 'none';
          specificGroup.style.display = 'block';
        } else if (mode === 'all') {
          countGroup.style.display = 'none';
          specificGroup.style.display = 'none';
        } else {
          countGroup.style.display = 'block';
          specificGroup.style.display = 'none';
        }

        this.updateModuleSelectionMode(moduleCode, mode);
        this.markAsChanged();
      });
    });

    // Обработчик ввода количества вопросов
    container.querySelectorAll('.module-question-count').forEach(input => {
      input.addEventListener('input', debounce((e) => {
        const moduleCode = e.target.dataset.module;
        const count = parseInt(e.target.value);

        this.updateModuleQuestionCount(moduleCode, count);
        this.markAsChanged();
      }, 500));
    });

    // Обработчик кнопок выбора конкретных вопросов
    container.querySelectorAll('.browse-questions-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        const moduleCode = e.target.dataset.module;
        await this.openQuestionBrowser(moduleCode);
      });
    });
  }

  /**
   * Добавляет модуль в состояние
   * @param {string} moduleCode
   */
  addModule(moduleCode) {
    const existing = this.state.modules.find(m => m.module_code === moduleCode);
    if (!existing) {
      this.state.modules.push({
        module_code: moduleCode,
        selection_mode: 'random',
        question_count: null,
        question_ids: []
      });
    }
  }

  /**
   * Удаляет модуль из состояния
   * @param {string} moduleCode
   */
  removeModule(moduleCode) {
    this.state.modules = this.state.modules.filter(m => m.module_code !== moduleCode);
  }

  /**
   * Обновляет режим отбора для модуля
   * @param {string} moduleCode
   * @param {string} mode
   */
  updateModuleSelectionMode(moduleCode, mode) {
    const module = this.state.modules.find(m => m.module_code === moduleCode);
    if (module) {
      module.selection_mode = mode;

      // Сбрасываем данные в зависимости от режима
      if (mode === 'all') {
        module.question_count = null;
        module.question_ids = [];
      } else if (mode === 'random') {
        module.question_ids = [];
      } else if (mode === 'specific') {
        module.question_count = null;
      }
    }
  }

  /**
   * Обновляет количество вопросов для модуля
   * @param {string} moduleCode
   * @param {number} count
   */
  updateModuleQuestionCount(moduleCode, count) {
    const module = this.state.modules.find(m => m.module_code === moduleCode);
    if (module) {
      module.question_count = count;
    }
  }

  /**
   * Открывает браузер вопросов для модуля
   * @param {string} moduleCode
   */
  async openQuestionBrowser(moduleCode) {
    const module = this.state.modules.find(m => m.module_code === moduleCode);
    if (!module) return;

    try {
      // Создаем модальное окно с браузером вопросов
      const modal = document.createElement('div');
      modal.className = 'modal';
      modal.style.display = 'flex';

      modal.innerHTML = `
        <div class="modal-content" style="max-width: 800px;">
          <div class="modal-header">
            <h2>Выбор вопросов: ${this.getModuleName(moduleCode)}</h2>
            <button class="close-btn" id="browser-modal-close">×</button>
          </div>
          <div class="modal-body" id="browser-modal-body"></div>
          <div class="modal-footer">
            <button class="btn-secondary" id="browser-cancel">Отмена</button>
            <button class="btn-primary" id="browser-confirm">Применить</button>
          </div>
        </div>
      `;

      document.body.appendChild(modal);

      const browserContainer = modal.querySelector('#browser-modal-body');
      const questionBrowser = new QuestionBrowser(browserContainer);
      await questionBrowser.init(moduleCode, module.question_ids);

      // Обработчики кнопок
      modal.querySelector('#browser-modal-close').addEventListener('click', () => {
        document.body.removeChild(modal);
      });

      modal.querySelector('#browser-cancel').addEventListener('click', () => {
        document.body.removeChild(modal);
      });

      modal.querySelector('#browser-confirm').addEventListener('click', () => {
        const selectedIds = questionBrowser.getSelectedIds();
        module.question_ids = selectedIds;

        // Обновляем счетчик
        const infoElement = document.querySelector(`.selected-questions-info[data-module="${moduleCode}"]`);
        if (infoElement) {
          infoElement.innerHTML = `Выбрано: <strong>${selectedIds.length}</strong> ${this.pluralize(selectedIds.length)}`;
        }

        document.body.removeChild(modal);
        this.markAsChanged();
      });

    } catch (error) {
      console.error('Failed to open question browser:', error);
      showToast('Ошибка открытия браузера вопросов', 'error');
    }
  }

  /**
   * Рендерит браузер вопросов для одного модуля
   * @param {HTMLElement} container
   * @param {string} moduleCode
   */
  async renderQuestionBrowser(container, moduleCode) {
    this.questionBrowser = new QuestionBrowser(container);
    await this.questionBrowser.init(moduleCode);

    // ИСПРАВЛЕНО: Правильная инициализация модуля при выборе вопросов
    // Слушаем изменения выбора
    this.questionBrowser.on('change', (selectedIds) => {
      console.log('Questions selected:', selectedIds.length);

      // Ищем существующий модуль по module_code
      let module = this.state.modules.find(m => m.module_code === moduleCode);

      if (!module) {
        // Создаем новый модуль
        module = {
          module_code: moduleCode,
          selection_mode: 'specific',
          question_count: null,
          question_ids: selectedIds
        };
        this.state.modules.push(module);
        console.log('Created new module:', module);
      } else {
        // Обновляем существующий модуль
        module.selection_mode = 'specific';
        module.question_ids = selectedIds;
        module.question_count = null;
        console.log('Updated existing module:', module);
      }

      this.markAsChanged();
      this.updateCreateButton();
      console.log('Current state.modules:', this.state.modules);
    });
  }

  /**
   * Устанавливает дедлайн на N дней вперед
   * @param {number} days
   */
  setDeadlineFromDays(days) {
    const deadline = new Date();
    deadline.setDate(deadline.getDate() + days);
    deadline.setHours(23, 59, 0, 0);

    const deadlineInput = document.getElementById('deadline-input');
    if (deadlineInput) {
      // Форматируем для datetime-local input
      const formatted = deadline.toISOString().slice(0, 16);
      deadlineInput.value = formatted;
      deadlineInput.disabled = false;
    }

    const noDeadlineCheckbox = document.getElementById('no-deadline');
    if (noDeadlineCheckbox) {
      noDeadlineCheckbox.checked = false;
    }

    this.state.deadline = deadline.toISOString();
    this.markAsChanged();
  }

  /**
   * Обновляет визуальное состояние кнопок дедлайна
   * @param {HTMLElement|null} activeBtn
   */
  updateDeadlineButtons(activeBtn) {
    document.querySelectorAll('.deadline-quick-btn').forEach(btn => {
      btn.classList.toggle('selected', btn === activeBtn);
    });
  }

  /**
   * Валидирует форму
   * @returns {Object} - объект с ошибками
   */
  validate() {
    const errors = validateAssignmentForm(this.state);

    // Показываем ошибки в UI
    this.showErrors(errors);

    return errors;
  }

  /**
   * Показывает ошибки валидации в UI
   * @param {Object} errors
   */
  showErrors(errors) {
    // Очищаем все предыдущие ошибки
    document.querySelectorAll('.form-error.show').forEach(el => {
      el.classList.remove('show');
    });
    document.querySelectorAll('.form-input.error').forEach(el => {
      el.classList.remove('error');
    });

    // Показываем новые ошибки
    Object.entries(errors).forEach(([field, message]) => {
      let input = null;

      if (field === 'title') {
        input = document.getElementById('assignment-title');
      } else if (field === 'description') {
        input = document.getElementById('assignment-description');
      } else if (field === 'deadline') {
        input = document.getElementById('deadline-input');
      }

      if (input) {
        input.classList.add('error');
        const errorElement = input.parentElement?.querySelector('.form-error');
        if (errorElement) {
          errorElement.textContent = message;
          errorElement.classList.add('show');
        }
      }
    });
  }

  /**
   * Обновляет состояние кнопки создания задания
   */
  updateCreateButton() {
    const createBtn = document.getElementById('create-btn');
    const previewBtn = document.getElementById('preview-btn');

    if (!createBtn || !previewBtn) return;

    const isValid = this.isFormValid();

    // Отладочное логирование
    console.log('[updateCreateButton] isValid:', isValid);
    console.log('[updateCreateButton] state:', {
      assignmentType: this.state.assignmentType,
      title: this.state.title,
      titleLength: this.state.title?.trim()?.length,
      studentIds: this.state.studentIds,
      studentIdsLength: this.state.studentIds?.length,
      modules: this.state.modules,
      modulesLength: this.state.modules?.length
    });

    createBtn.disabled = !isValid;
    previewBtn.disabled = !isValid;
  }

  /**
   * Проверяет, валидна ли форма (базовая проверка)
   * @returns {boolean}
   */
  isFormValid() {
    // ИСПРАВЛЕНО: Добавлена проверка наличия выбранных вопросов для типов заданий, которые требуют их

    // Базовые проверки
    if (!this.state.assignmentType) return false;
    if (this.state.title.trim().length < 3) return false;
    if (this.state.studentIds.length === 0) return false;

    // ИСПРАВЛЕНО: Проверка наличия вопросов для типов, которые их требуют
    const needsModules = ['task19', 'task20', 'task24', 'task25', 'mixed', 'test_part'].includes(this.state.assignmentType);

    if (needsModules) {
      // Проверяем наличие модулей
      if (!this.state.modules || this.state.modules.length === 0) {
        return false;
      }

      // Проверяем что каждый модуль имеет выбранные вопросы
      for (const module of this.state.modules) {
        if (module.selection_mode === 'specific') {
          if (!module.question_ids || module.question_ids.length === 0) {
            return false;
          }
        } else if (module.selection_mode === 'random') {
          if (!module.question_count || module.question_count < 1) {
            return false;
          }
        }
        // Для 'all' модуль валиден по умолчанию
      }
    }

    return true;
  }

  /**
   * Показывает предпросмотр задания
   */
  showPreview() {
    if (this.previewModal) {
      this.previewModal.show(this.state, this.getAssignmentData());
    }
  }

  /**
   * Получает данные для отправки на сервер
   * @returns {Object}
   */
  getAssignmentData() {
    const data = {
      assignment_type: this.state.assignmentType,
      title: this.state.title.trim(),
      description: this.state.description.trim() || null,
      deadline: this.state.deadline || null,
      student_ids: this.state.studentIds,
      modules: this.state.modules
    };

    // Добавляем camelCase версии для PreviewModal
    data.assignmentType = data.assignment_type;
    data.studentIds = data.student_ids;

    return data;
  }

  /**
   * Получает текущее состояние формы
   * @returns {Object}
   */
  getState() {
    return { ...this.state };
  }

  /**
   * Загружает состояние в форму
   * @param {Object} state
   */
  loadState(state) {
    this.state = { ...state };

    // Обновляем UI в соответствии с загруженным состоянием
    this.updateUIFromState();
  }

  /**
   * Обновляет UI на основе текущего состояния
   */
  updateUIFromState() {
    // Тип задания
    if (this.state.assignmentType) {
      const typeCard = this.container.querySelector(
        `.type-card[data-type="${this.state.assignmentType}"]`
      );
      if (typeCard) {
        typeCard.click();
      }
    }

    // Название и описание
    const titleInput = document.getElementById('assignment-title');
    if (titleInput) {
      titleInput.value = this.state.title;
    }

    const descriptionInput = document.getElementById('assignment-description');
    if (descriptionInput) {
      descriptionInput.value = this.state.description;
    }

    // Дедлайн
    if (this.state.deadline) {
      const deadlineInput = document.getElementById('deadline-input');
      if (deadlineInput) {
        const formatted = new Date(this.state.deadline).toISOString().slice(0, 16);
        deadlineInput.value = formatted;
      }
    }

    // Ученики
    if (this.studentSelector && this.state.studentIds.length > 0) {
      this.studentSelector.setSelected(this.state.studentIds);
    }

    this.updateCreateButton();
  }

  /**
   * Проверяет наличие несохраненных изменений
   * @returns {boolean}
   */
  hasUnsavedChanges() {
    return this.hasChanges;
  }

  /**
   * Помечает форму как измененную
   */
  markAsChanged() {
    this.hasChanges = true;
  }

  /**
   * Сбрасывает флаг изменений
   */
  resetChanges() {
    this.hasChanges = false;
  }

  /**
   * Запускает автосохранение черновика
   */
  startAutoSave() {
    this.autoSaveInterval = setInterval(() => {
      if (this.hasChanges && this.isFormValid()) {
        draftManager.saveCurrent(this.state);
        console.log('Draft auto-saved');
      }
    }, 30000); // Каждые 30 секунд
  }

  /**
   * Останавливает автосохранение
   */
  stopAutoSave() {
    if (this.autoSaveInterval) {
      clearInterval(this.autoSaveInterval);
      this.autoSaveInterval = null;
    }
  }

  /**
   * Получает название модуля по коду
   * @param {string} code
   * @returns {string}
   */
  getModuleName(code) {
    const module = this.availableModules.find(m => m.code === code);
    return module ? module.name : code;
  }

  /**
   * Склонение слова "вопрос"
   * @param {number} count
   * @returns {string}
   */
  pluralize(count) {
    const mod10 = count % 10;
    const mod100 = count % 100;

    if (mod10 === 1 && mod100 !== 11) {
      return 'вопрос';
    } else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
      return 'вопроса';
    } else {
      return 'вопросов';
    }
  }

  /**
   * Очищает форму
   */
  clear() {
    this.state = {
      assignmentType: null,
      modules: [],
      title: '',
      description: '',
      studentIds: [],
      deadline: null
    };

    this.updateUIFromState();
    this.resetChanges();
  }

  /**
   * Уничтожает компонент
   */
  destroy() {
    this.stopAutoSave();

    if (this.questionBrowser) {
      this.questionBrowser.destroy();
    }

    if (this.studentSelector) {
      this.studentSelector.destroy();
    }

    if (this.previewModal) {
      this.previewModal.destroy();
    }
  }
}
