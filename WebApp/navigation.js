/**
 * Инициализация SPA роутера для навигации по разделам.
 * При переходе на #quiz или #plan — открывает внешние Telegram-боты.
 * Для остальных маршрутов использует функции отрисовки из routes.
 */
export function initRouter(routes) {
  const container = document.getElementById('app-content');   // <main id="app-content">
  if (!container) {
    console.error('Ошибка: не найден контейнер с id="app"');
    return;
  }

  /**
   * Подсветка активной навигационной ссылки.
   * @param {string} hash - текущий якорь (например, "#flashcards")
   */
  function highlightNav(hash) {
    document.querySelectorAll('.nav-link').forEach(link => {
      link.classList.toggle('active', link.getAttribute('href') === hash);
    });
  }

  /**
   * Обработка изменения маршрута.
   * Открывает Telegram-боты для #quiz и #plan,
   * рендерит разделы для остальных маршрутов.
   */
  function render() {
    const hash = window.location.hash || '#flashcards';

    // Обработка внешних ботов
    if (hash === '#quiz') {
      Telegram.WebApp.openLink('https://t.me/neurorepetitor_bot');
      highlightNav(hash); // Подсветим ссылку, хотя это внешняя ссылка
      return;
    }
    if (hash === '#plan') {
      Telegram.WebApp.openLink('https://t.me/plannapalcahbot');
      highlightNav(hash); // Подсветим ссылку, хотя это внешняя ссылка
      return;
    }
    if (typeof renderFn === 'function') {
      container.innerHTML = '';          // очистили старый контент
      renderFn(container);
      highlightNav(hash);
    }
    // Обработка внутренних маршрутов
    const renderFn = routes[hash];
    if (typeof renderFn === 'function') {
      renderFn(container);
      highlightNav(hash);
    } else {
      // Если маршрут не найден, рендерим #flashcards по умолчанию
      routes['#flashcards'](container);
      highlightNav('#flashcards');
    }
  }

  // Слушаем смену маршрутов
  window.addEventListener('hashchange', render);

  // Первичная отрисовка при загрузке страницы
  render();
}
