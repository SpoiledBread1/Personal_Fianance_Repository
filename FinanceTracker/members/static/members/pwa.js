let installPrompt;
const installButton = document.querySelector('#install-app');

window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
    if (installButton) installButton.hidden = false;
});

installButton?.addEventListener('click', async () => {
    if (!installPrompt) return;

    try {
        await installPrompt.prompt();
        await installPrompt.userChoice;
    } catch (error) {
        console.error('Sable could not open the install prompt:', error);
    } finally {
        installPrompt = null;
        installButton.hidden = true;
    }
});

window.addEventListener('appinstalled', () => {
    installPrompt = null;
    if (installButton) installButton.hidden = true;
});

if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js')
        .catch(error => console.error('Sable service worker registration failed:', error));
}
