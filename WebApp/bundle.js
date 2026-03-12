(function () {
  'use strict';

  /**
   * Инициализация SPA роутера для навигации по разделам.
   * При переходе на #quiz или #plan — открывает внешние Telegram-боты.
   * Для остальных маршрутов использует функции отрисовки из routes.
   */
  function initRouter(routes) {
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

  /* Универсальное хранилище прогресса/избранного */

  const DEFAULT_KEY = 'flashcardsProgress';

  function loadProgress(key = DEFAULT_KEY) {
    if (typeof key === 'object') {            // вызов без key
      return loadProgress()(key);
    }
    try   { return JSON.parse(localStorage.getItem(key) || '{}'); }
    catch { return {}; }
  }

  function saveProgress(key = DEFAULT_KEY, data = {}) {
    // допускаем старый вызов saveProgress(progress)
    if (typeof key === 'object') { data = key; key = DEFAULT_KEY; }
    try   { localStorage.setItem(key, JSON.stringify(data)); }
    catch (e) { console.error('storage error', e); }
  }

  // modules/flashcards.js


  let cards$1 = [];
  let currentIndex = 0;
  let isFlipped = false;

  async function renderFlashcards(container) {
    container.innerHTML = '';
    const title = document.createElement('h2');
    title.textContent = 'Flashcards: Термины и определения';
    container.appendChild(title);

    // Load data
    if (!cards$1.length) {
      try {
        const response = await fetch('data/cards.json');
        cards$1 = await response.json();
      } catch (err) {
        container.appendChild(document.createTextNode('Ошибка загрузки карточек.')); 
        console.error(err);
        return;
      }
    }

  if (!cards$1.length) {
    const noCardsMsg = document.createElement('p');
    noCardsMsg.textContent = 'Нет карточек для отображения.';
    container.appendChild(noCardsMsg);
    return;
  }


    // Load progress and find next card
    const progress = loadProgress('flashcardsProgress');
    currentIndex = cards$1.findIndex(c => !progress[c.id]);
    if (currentIndex === -1) currentIndex = 0; // все изучены

  if (currentIndex === -1) {
    container.innerHTML += '<p>Все карточки изучены! 🎉</p>';
    return;
  }


    // Create card element
    const cardEl = document.createElement('div');
    cardEl.className = 'flashcard';
    cardEl.textContent = cards$1[currentIndex].term;
    cardEl.style.cursor = 'pointer';
    cardEl.addEventListener('click', () => {
      isFlipped = !isFlipped;
      cardEl.textContent = isFlipped ? cards$1[currentIndex].definition : cards$1[currentIndex].term;
    });
    container.appendChild(cardEl);

    /*  Новый интерфейс  */
    const startBtn = document.createElement('button');
    startBtn.className = 'btn-start-session';
    startBtn.textContent = 'Начать тренировку ▶';
    startBtn.onclick = () => Promise.resolve().then(function () { return flashcardSession; })
                           .then(m => m.startSession(cards$1));
    container.appendChild(startBtn);

    /* Старая «быстрая карточка» (по желанию) можно оставить ниже */

    // Controls
    const controls = document.createElement('div');
    controls.className = 'flashcard-controls';

    const knownBtn = document.createElement('button');
    knownBtn.textContent = 'Изучено';
    knownBtn.addEventListener('click', () => handleStatus(true));

    const laterBtn = document.createElement('button');
    laterBtn.textContent = 'Повторить позже';
    laterBtn.addEventListener('click', () => handleStatus(false));

    controls.append(knownBtn, laterBtn);
    container.appendChild(controls);

    // Helper: update UI for next card
    function handleStatus(markKnown) {
      progress[cards$1[currentIndex].id] = markKnown;
      saveProgress('flashcardsProgress', progress);
      isFlipped = false;
      // Next card
      currentIndex = (currentIndex + 1) % cards$1.length;
      cardEl.textContent = cards$1[currentIndex].term;
    }
  }

  // modules/glossary.js

  let glossary = [];
  let favorites = {};

  async function renderGlossary(container) {
    // Clear container and render title
    container.innerHTML = '';
    const title = document.createElement('h2');
    title.textContent = 'Словарь терминов';
    title.className = 'glossary-title';
    container.appendChild(title);

    // Load glossary data if not already
    if (!glossary.length) {
      try {
        const response = await fetch('data/glossary.json');
        glossary = await response.json();
      } catch (err) {
        container.appendChild(document.createTextNode('Ошибка загрузки словаря.'));
        console.error(err);
        return;
      }
    }

    // Load favorites from storage
    favorites = loadProgress('glossaryFavorites') || {};

    // Search input wrapper
    const searchWrapper = document.createElement('div');
    searchWrapper.className = 'search-wrapper';
    const input = document.createElement('input');
    input.type = 'search';
    input.placeholder = 'Поиск термина…';
    input.className = 'search-input';
    searchWrapper.appendChild(input);
    container.appendChild(searchWrapper);

    // Glossary grid container
    const grid = document.createElement('div');
    grid.className = 'glossary-grid';
    container.appendChild(grid);

    // Function to render list with optional filter
    function renderList(filter = '') {
      grid.innerHTML = '';
      grid.style.opacity = 0;
      setTimeout(() => { grid.style.opacity = 1; }, 100);
      const filtered = glossary.filter(item =>
        item.term.toLowerCase().includes(filter.toLowerCase()) ||
        item.definition.toLowerCase().includes(filter.toLowerCase())
      );
      if (!filtered.length) {
        const none = document.createElement('p');
        none.textContent = 'Ничего не найдено.';
        none.className = 'no-results';
        grid.appendChild(none);
        return;
      }

      filtered.forEach(item => {
        const card = document.createElement('article');
        card.className = 'term-card';

        const header = document.createElement('div');
        header.className = 'term-header';

        const termEl = document.createElement('h3');
        termEl.className = 'term-title';
        termEl.textContent = item.term;

        const favBtn = document.createElement('button');
        favBtn.className = 'fav-btn';
        favBtn.textContent = favorites[item.term] ? '★' : '☆';
        favBtn.addEventListener('click', () => {
          favorites[item.term] = !favorites[item.term];
          saveProgress('glossaryFavorites', favorites);
          favBtn.textContent = favorites[item.term] ? '★' : '☆';
        });

        header.append(termEl, favBtn);
        card.appendChild(header);

        const defEl = document.createElement('p');
        defEl.className = 'term-definition';
        defEl.textContent = item.definition;
        card.appendChild(defEl);

        grid.appendChild(card);
      });
    }

    // Event listeners
    input.addEventListener('input', e => renderList(e.target.value));

    // Initial render
    renderList();
  }

  /* ────────────────────────────────────────────────────────────
     SCRIPT.JS   (главный клиентский файл WebApp)
     ──────────────────────────────────────────────────────────── */


  document.addEventListener('DOMContentLoaded', () => {
    /* === Telegram Web-App init === */
    if (!window.Telegram || !window.Telegram.WebApp) {
      console.error('Telegram WebApp script not loaded!');
      document.body.innerHTML =
        '<div style="text-align:center;padding:30px;font-family:sans-serif;color:red">' +
        'Ошибка: откройте эту страницу через бота Telegram.' +
        '</div>';
      return;
    }

    const tg = window.Telegram.WebApp;
    tg.ready();
    tg.expand();

    /* === SPA-роутинг === */
    initRouter({
      '#flashcards': renderFlashcards,
      '#glossary'  : renderGlossary,
    });

    /* === Платёжная часть (активируется ТОЛЬКО если нужная верстка есть) === */
    const emailInput = document.getElementById('email-input');
    const errorBlock = document.getElementById('error-message');

    // Если на странице нет этих элементов — значит мы не на тарифной странице,
    // поэтому выходим, не исполняя код оплаты и не ломая остальные разделы
    if (!emailInput || !errorBlock) {
      console.debug('[payment] UI not found — payment module skipped');
      return;          // ← выходим только из обработчика DOMContentLoaded
    }

    /* ---- Ниже можно вернуть полный код оплаты, когда он снова понадобится ---- */
    emailInput.placeholder = 'example@mail.ru';
    // … updateUI, setActiveCard, initiatePayment и т.д.
  });

  /* Оверлей-режим тренировки --------------------------------- */
  let cards = [];

  async function startSession(allCards) {
    // 1) загружаем (или получаем из вызова) карточки и фильтруем изученные
    cards = [...allCards].filter(c => !loadProgress('flashcardsProgress')[c.id]);
    if (!cards.length) return alert('Все карточки уже изучены 🎉');

    shuffle(cards);

    // 2) создаём оверлей
    const overlay = document.createElement('div');
    overlay.className = 'flashcard-session';
    overlay.innerHTML = `
    <div class="flashcard-counter">1 / ${cards.length}</div>
    <article class="flashcard-card"></article>
    <div class="flashcard-buttons">
      <button id="known"   class="btn-known">Изучено ✓</button>
      <button id="repeat"  class="btn-repeat">Повторить позже ↺</button>
    </div>`;
    document.body.appendChild(overlay);

    const cardEl  = overlay.querySelector('.flashcard-card');
    const counter = overlay.querySelector('.flashcard-counter');
    let idx = 0, flipped = false;

    renderCard();

    /* --- события ------------------------------------------ */
    overlay.addEventListener('click', e => {
      if (e.target === overlay) close();           // клик вне карточки = выход
    });
    cardEl.addEventListener('click', () => flip());
    document.addEventListener('keyup', onKey);
    overlay.querySelector('#known') .onclick = () => next(true);
    overlay.querySelector('#repeat').onclick = () => next(false);

    /* --- функции ------------------------------------------ */
    function renderCard() {
      flipped = false;
      cardEl.classList.remove('flipped');
      cardEl.innerHTML = `<span>${cards[idx].term}</span>`;
      counter.textContent = `${idx + 1} / ${cards.length}`;
    }
    function flip() {
      flipped = !flipped;
      cardEl.classList.toggle('flipped');
      cardEl.innerHTML = `<span>${flipped ? cards[idx].definition : cards[idx].term}</span>`;
    }
    function next(known) {
      const progress = loadProgress('flashcardsProgress');
      progress[cards[idx].id] = known;
      saveProgress('flashcardsProgress', progress);
      idx++;
      if (idx >= cards.length) { close(); alert('✓ Сессия завершена!'); }
      else renderCard();
    }
    function close() {
      document.removeEventListener('keyup', onKey);
      overlay.remove();
    }
    function onKey(e) {
      if (e.key === 'Escape') close();
      if (e.key === ' ')      flip();
      if (e.key === 'ArrowRight') next(true);
      if (e.key === 'ArrowLeft')  next(false);
    }
    function shuffle(arr) { for (let i = arr.length; i--; ) {
        const j = Math.floor(Math.random() * (i + 1)); [arr[i], arr[j]] = [arr[j], arr[i]];
    }}
  }

  var flashcardSession = /*#__PURE__*/Object.freeze({
    __proto__: null,
    startSession: startSession
  });

})();
