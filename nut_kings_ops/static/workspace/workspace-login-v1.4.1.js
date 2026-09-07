'use strict';

document.addEventListener('DOMContentLoaded', () => {
  const button = document.getElementById('nk-toggle-password');
  const input = document.getElementById('nk-password');
  if (!button || !input) return;
  button.addEventListener('click', () => {
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(show));
    button.setAttribute('aria-label', show ? 'Hide password' : 'Show password');
    input.focus();
  });
});
