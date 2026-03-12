/* ────────────────────────────────────────────────────────────
   SCRIPT.JS   (главный клиентский файл WebApp)
   ──────────────────────────────────────────────────────────── */

import { initRouter }       from './navigation.js';
import { renderFlashcards } from './modules/flashcards.js';
import { renderGlossary }   from './modules/glossary.js';

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
