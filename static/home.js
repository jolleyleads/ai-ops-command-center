(() => {
  const toggle = document.querySelector('.menu-toggle');
  const links = document.getElementById('nav-links');
  function closeMenu() { links.classList.remove('open'); toggle.setAttribute('aria-expanded', 'false'); }
  toggle.addEventListener('click', () => {
    const open = toggle.getAttribute('aria-expanded') !== 'true';
    toggle.setAttribute('aria-expanded', String(open));
    links.classList.toggle('open', open);
  });
  links.addEventListener('click', event => { if (event.target.closest('a')) closeMenu(); });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') { closeMenu(); toggle.focus(); }
  });
  fetch('/auth/session', {credentials: 'same-origin', cache: 'no-store'})
    .then(response => response.ok ? response.json() : null)
    .then(state => {
      if (state && state.signed_in === true) document.querySelectorAll('[data-login]').forEach(link => {
        link.textContent = 'Open Dashboard'; link.href = '/chat-operator';
      });
    }).catch(() => {});
})();
