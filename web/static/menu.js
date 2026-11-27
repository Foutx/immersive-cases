// Progressive enhancement: catalogue, filtering and downloads also work without JS.
const header = document.querySelector('.header');
const menu = document.querySelector('.menu-toggle');
const nav = document.querySelector('#navigation');
const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
let lastScroll = window.scrollY;
menu.addEventListener('click', () => {
  const opened = menu.getAttribute('aria-expanded') !== 'true';
  menu.setAttribute('aria-expanded', String(opened));
  nav.classList.toggle('open', opened);
  header.classList.remove('hidden');
});
nav.addEventListener('click', event => {
  if (event.target.closest('a')) {
    nav.classList.remove('open');
    menu.setAttribute('aria-expanded', 'false');
  }
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && nav.classList.contains('open')) {
    nav.classList.remove('open');
    menu.setAttribute('aria-expanded', 'false');
    menu.focus();
  }
});
window.addEventListener('scroll', () => {
  const y = window.scrollY;
  if (!reduced.matches && !nav.classList.contains('open') && !header.contains(document.activeElement)) {
    header.classList.toggle('hidden', y > 250 && y > lastScroll);
  }
  lastScroll = y;
}, { passive: true });
header.addEventListener('focusin', () => header.classList.remove('hidden'));
