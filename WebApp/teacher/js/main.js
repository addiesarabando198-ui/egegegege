/**
 * Главный файл приложения WebApp для учителей
 * Точка входа и инициализация всех компонентов
 */

import { telegramAuth } from './auth.js';
import { api, APIError } from './api.js';
import { draftManager } from './utils/storage.js';
import { AssignmentForm } from './components/AssignmentForm.js';
import { showToast, hideLoadingScreen, showLoadingScreen } from './utils/ui.js';

class TeacherApp {
  constructor() {
    this.initialized = false;
    this.teacherProfile = null;
    this.assignmentForm = null;
  }

  /**
   * Инициализация приложения
   */
  async init() {
    console.log('Initializing Teacher WebApp...');

    try {
      // 1. Инициализация Telegram WebApp
      const telegramInitialized = telegramAuth.init();
      if (!telegramInitialized) {
        this.showError('Ошибка инициализации Telegram WebApp');
        return;
      }

      // 2. Проверка аутентификации и загрузка профиля
      await this.loadTeacherProfile();

      // 3. Инициализация компонентов
      await this.initComponents();

      // 4. Настройка обработчиков событий
      this.setupEventListeners();

      // 5. Загрузка черновика (если есть)
      this.loadDraft();

      // 6. Скрываем экран загрузки
      hideLoadingScreen();

      // 7. Показываем приложение
      document.getElementById('app').style.display = 'block';

      this.initialized = true;
      console.log('Teacher WebApp initialized successfully');

    } catch (error) {
      console.error('Initialization error:', error);
      this.showError(error.message || 'Ошибка инициализации приложения');
    }
  }

  /**
   * Загружает профиль учителя
   */
  async loadTeacherProfile() {
    try {
      console.log('Loading teacher profile...');
      this.teacherProfile = await api.getTeacherProfile();
      console.log('Teacher profile loaded:', this.teacherProfile);
    } catch (error) {
      console.error('Failed to load teacher profile:', error);

      if (error instanceof APIError && error.isAuthError()) {
        throw new Error('Ошибка аутентификации. У вас нет доступа к режиму учителя.');
      }

      throw new Error('Не удалось загрузить профиль учителя. Попробуйте позже.');
    }
  }

  /**
   * Инициализирует компоненты
   */
  async initComponents() {
    console.log('Initializing components...');

    // Создаем форму создания задания
    const formContainer = document.getElementById('assignment-form');
    if (formContainer) {
      this.assignmentForm = new AssignmentForm(formContainer);
      await this.assignmentForm.init();
    }
  }

  /**
   * Настраивает обработчики событий
   */
  setupEventListeners() {
    // Кнопка закрытия
    const closeBtn = document.getElementById('close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => this.handleClose());
    }

    // Кнопка сохранения черновика
    const saveDraftBtn = document.getElementById('save-draft-btn');
    if (saveDraftBtn) {
      saveDraftBtn.addEventListener('click', () => this.handleSaveDraft());
    }

    // Кнопка предпросмотра
    const previewBtn = document.getElementById('preview-btn');
    if (previewBtn) {
      previewBtn.addEventListener('click', () => this.handlePreview());
    }

    // Кнопка создания задания
    const createBtn = document.getElementById('create-btn');
    if (createBtn) {
      createBtn.addEventListener('click', () => this.handleCreate());
    }

    // Предотвращаем закрытие при несохраненных изменениях
    window.addEventListener('beforeunload', (e) => {
      if (this.assignmentForm?.hasUnsavedChanges()) {
        e.preventDefault();
        e.returnValue = '';
      }
    });

    // Telegram WebApp события
    if (telegramAuth.tg) {
      // Обработка закрытия WebApp
      telegramAuth.tg.onEvent('backButtonClicked', () => {
        this.handleClose();
      });
    }
  }

  /**
   * Загружает черновик из LocalStorage
   */
  loadDraft() {
    if (!this.assignmentForm) return;

    const draft = draftManager.loadCurrent();
    if (draft) {
      console.log('Draft found, loading...');

      const age = draftManager.getCurrentAge();
      const ageMinutes = Math.floor(age / 60000);

      // Спрашиваем пользователя, хочет ли он загрузить черновик
      const message = `Найден черновик задания (создан ${ageMinutes} мин. назад). Загрузить его?`;

      telegramAuth.showPopup({
        title: 'Черновик найден',
        message,
        buttons: [
          { id: 'load', type: 'default', text: 'Загрузить' },
          { id: 'discard', type: 'destructive', text: 'Отменить' }
        ]
      }, (buttonId) => {
        if (buttonId === 'load') {
          this.assignmentForm.loadState(draft);
          showToast('Черновик загружен', 'success');
        } else {
          draftManager.removeCurrent();
        }
      });
    }
  }

  /**
   * Обработчик закрытия приложения
   */
  async handleClose() {
    if (this.assignmentForm?.hasUnsavedChanges()) {
      const confirmed = await telegramAuth.showConfirm(
        'У вас есть несохраненные изменения. Вы уверены, что хотите выйти?'
      );

      if (!confirmed) {
        return;
      }
    }

    telegramAuth.close();
  }

  /**
   * Обработчик сохранения черновика
   */
  handleSaveDraft() {
    if (!this.assignmentForm) return;

    try {
      const state = this.assignmentForm.getState();
      draftManager.saveCurrent(state);

      showToast('Черновик сохранен', 'success');
      telegramAuth.hapticFeedback('success');

      // Также сохраняем на сервер (опционально)
      this.saveDraftToServer(state);

    } catch (error) {
      console.error('Failed to save draft:', error);
      showToast('Ошибка сохранения черновика', 'error');
    }
  }

  /**
   * Сохраняет черновик на сервер
   */
  async saveDraftToServer(state) {
    try {
      await api.saveDraft(state);
      console.log('Draft saved to server');
    } catch (error) {
      console.error('Failed to save draft to server:', error);
      // Не показываем ошибку пользователю, т.к. черновик уже сохранен локально
    }
  }

  /**
   * Обработчик предпросмотра
   */
  handlePreview() {
    if (!this.assignmentForm) return;

    try {
      const errors = this.assignmentForm.validate();

      if (Object.keys(errors).length > 0) {
        showToast('Исправьте ошибки в форме', 'warning');
        return;
      }

      this.assignmentForm.showPreview();
      telegramAuth.hapticFeedback('light');

    } catch (error) {
      console.error('Preview error:', error);
      showToast('Ошибка создания предпросмотра', 'error');
    }
  }

  /**
   * Обработчик создания задания
   */
  async handleCreate() {
    if (!this.assignmentForm) return;

    try {
      // Валидация
      const errors = this.assignmentForm.validate();
      if (Object.keys(errors).length > 0) {
        showToast('Исправьте ошибки в форме', 'warning');
        return;
      }

      // Подтверждение
      const confirmed = await telegramAuth.showConfirm(
        'Вы уверены, что хотите создать это задание?'
      );

      if (!confirmed) {
        return;
      }

      // Показываем загрузку
      showLoadingScreen('Создание задания...');

      // Получаем данные формы
      const assignmentData = this.assignmentForm.getAssignmentData();

      // Отправляем на сервер
      const response = await api.createAssignment(assignmentData);

      // Удаляем черновик
      draftManager.removeCurrent();

      // Показываем успех
      hideLoadingScreen();
      telegramAuth.hapticFeedback('success');

      const message = `Задание "${assignmentData.title}" успешно создано и отправлено ${response.students_notified} ученикам!`;

      telegramAuth.showPopup({
        title: 'Успех!',
        message,
        buttons: [
          { id: 'close', type: 'default', text: 'Закрыть' }
        ]
      }, () => {
        telegramAuth.close();
      });

    } catch (error) {
      hideLoadingScreen();
      console.error('Failed to create assignment:', error);

      let errorMessage = 'Не удалось создать задание. Попробуйте еще раз.';

      if (error instanceof APIError) {
        errorMessage = error.getUserMessage();

        if (error.isValidationError()) {
          const validationErrors = error.getValidationErrors();
          this.assignmentForm.showErrors(validationErrors);
        }
      }

      showToast(errorMessage, 'error');
      telegramAuth.hapticFeedback('error');
    }
  }

  /**
   * Показывает ошибку
   */
  showError(message) {
    hideLoadingScreen();

    const errorContainer = document.createElement('div');
    errorContainer.style.cssText = `
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 2rem;
      text-align: center;
    `;

    errorContainer.innerHTML = `
      <div style="font-size: 3rem; margin-bottom: 1rem;">⚠️</div>
      <h2 style="margin-bottom: 1rem;">Ошибка</h2>
      <p style="color: var(--tg-theme-hint-color); margin-bottom: 2rem;">${message}</p>
      <button onclick="window.Telegram.WebApp.close()" style="
        padding: 12px 24px;
        background: var(--tg-theme-button-color);
        color: var(--tg-theme-button-text-color);
        border: none;
        border-radius: 8px;
        font-size: 16px;
        cursor: pointer;
      ">Закрыть</button>
    `;

    document.body.innerHTML = '';
    document.body.appendChild(errorContainer);
  }
}

// Инициализация приложения при загрузке DOM
document.addEventListener('DOMContentLoaded', () => {
  const app = new TeacherApp();
  app.init();

  // Для отладки - сохраняем в window (временно для диагностики)
  window.teacherApp = app;

  // После инициализации assignmentForm может быть еще undefined
  // Сохраняем его после полной инициализации
  setTimeout(() => {
    window.assignmentForm = app.assignmentForm;
    console.log('Debug: assignmentForm set to window', !!window.assignmentForm);
  }, 100);
});

// Экспортируем для доступа из других модулей
export { TeacherApp };
