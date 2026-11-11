(() => {
    const form = document.querySelector('[data-instrument-search]');
    if (!form) return;
    const input = form.querySelector('[name="symbol"]');
    const list = document.querySelector('#instrument-results');
    const status = document.querySelector('#instrument-search-status');
    let timer, controller, sequence = 0;
    input.addEventListener('input', () => {
        clearTimeout(timer);
        controller?.abort();
        const current = ++sequence;
        const query = input.value.trim();
        list.replaceChildren();
        status.textContent = '';
        if (query.length < 2) return;
        timer = setTimeout(async () => {
            controller = new AbortController();
            status.textContent = 'Finding symbols…';
            try {
                const url = new URL(form.dataset.instrumentSearch, window.location.origin);
                url.searchParams.set('q', query);
                const response = await fetch(url, {credentials: 'same-origin', signal: controller.signal, cache: 'no-store'});
                if (response.redirected) throw new Error('Sign in again to search.');
                const data = await response.json();
                if (current !== sequence) return;
                if (!response.ok) throw new Error(data.error || 'Symbol search is temporarily unavailable.');
                const options = data.results.map(item => {
                    const option = document.createElement('option');
                    option.value = item.symbol;
                    option.label = item.name;
                    return option;
                });
                list.replaceChildren(...options);
                status.textContent = options.length ? 'Choose a ticker from the suggestions.' : 'No matching USD-listed symbols. Try another name or ticker.';
            } catch (error) {
                if (error.name !== 'AbortError' && current === sequence) status.textContent = error.message;
            }
        }, 400);
    });
})();
