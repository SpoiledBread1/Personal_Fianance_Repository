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

document.querySelectorAll('[data-open-dialog]').forEach(button => {
    button.addEventListener('click', () => {
        document.getElementById(button.dataset.openDialog)?.showModal();
    });
});

document.querySelectorAll('[data-close-dialog]').forEach(button => {
    button.addEventListener('click', () => button.closest('dialog')?.close());
});

document.querySelectorAll('.entry-form select[name="category_name"]').forEach(select => {
    const customField = select.form.querySelector('.category-custom-field');
    const customInput = customField?.querySelector('input');
    if (!customField || !customInput) return;

    const updateCustomCategory = () => {
        const showCustomField = select.value === '__new__';
        customField.hidden = !showCustomField;
        customInput.required = showCustomField;
        if (!showCustomField) customInput.value = '';
    };

    select.addEventListener('change', updateCustomCategory);
    updateCustomCategory();
});

document.querySelector('dialog[data-reopen]')?.showModal();

const requestedDialog = new URLSearchParams(window.location.search).get('dialog');
if (requestedDialog === 'transaction-dialog' || requestedDialog === 'account-dialog' || requestedDialog === 'budget-dialog') {
    document.getElementById(requestedDialog)?.showModal();
}
