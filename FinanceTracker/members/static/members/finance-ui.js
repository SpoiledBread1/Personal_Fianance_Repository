// Optional enhancements. Login and logout still work without JavaScript.
const passwordButton = document.querySelector('.password-toggle');
const passwordInput = document.querySelector('#id_password');

if (passwordButton && passwordInput) {
    passwordButton.hidden = false;
    passwordButton.addEventListener('click', () => {
        const reveal = passwordInput.type === 'password';
        passwordInput.type = reveal ? 'text' : 'password';
        passwordButton.setAttribute('aria-pressed', String(reveal));
        passwordButton.setAttribute('aria-label', reveal ? 'Hide password' : 'Show password');
    });
}

// Sidebar links jump to real sections on this dashboard.
const sectionLinks = document.querySelectorAll('.sidebar nav .nav-link');
function updateNavigation() {
    const selected = window.location.hash || '#overview';
    sectionLinks.forEach(link => {
        const active = link.getAttribute('href') === selected;
        link.classList.toggle('active', active);
        if (active) link.setAttribute('aria-current', 'location');
        else link.removeAttribute('aria-current');
    });
}
window.addEventListener('hashchange', updateNavigation);
updateNavigation();

document.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => {
        document.getElementById(button.dataset.openDialog)?.showModal();
    });
});

document.querySelectorAll('[data-close-dialog]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog')?.close());
});

document.querySelector('dialog[data-reopen]')?.showModal();
