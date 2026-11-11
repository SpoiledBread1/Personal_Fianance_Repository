(() => {
    const section = document.querySelector('#stocks-news');
    if (!section) return;
    const status = section.querySelector('#market-status');
    const refresh = section.querySelector('#market-retry');
    const dateFormat = new Intl.DateTimeFormat(undefined, {dateStyle: 'medium', timeStyle: 'short'});
    const dollars = new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD'});
    const numbers = new Intl.NumberFormat('en-US', {maximumFractionDigits: 6});
    let loading = false, visible = false, nextLoad = 0, timer, headlines = [];
    const node = (tag, className, text) => {
        const item = document.createElement(tag);
        if (className) item.className = className;
        if (text !== undefined) item.textContent = text;
        return item;
    };
    const money = value => value === null || value === undefined ? '—' : dollars.format(Number(value));
    const signed = value => value === null || value === undefined ? '—' : `${Number(value) > 0 ? '+' : ''}${money(value)}`;
    const percent = value => value === null || value === undefined ? '' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
    function movement(element, value) {
        element.classList.remove('market-positive', 'market-negative');
        if (value !== null && value !== undefined && Number(value) !== 0) {
            element.classList.add(Number(value) > 0 ? 'market-positive' : 'market-negative');
        }
    }
    function identity(entry) {
        const container = node('div', 'investment-identity');
        const badge = node('span', 'investment-badge', entry.symbol[0]);
        badge.setAttribute('aria-hidden', 'true');
        const name = node('div');
        name.append(node('strong', '', entry.symbol), node('span', 'investment-company', entry.name));
        container.append(badge, name);
        return container;
    }
    function renderHoldings(entries) {
        const body = section.querySelector('#holdings-body');
        body.replaceChildren();
        if (!entries.length) {
            const row = node('tr');
            const cell = node('td', 'investment-empty', 'Add your first holding to track its price and value automatically.');
            cell.colSpan = 7;
            row.append(cell);
            body.append(row);
        }
        entries.forEach(entry => {
            const quote = entry.quote;
            const row = node('tr');
            const name = node('td');
            name.append(identity(entry));
            const price = node('td', '', money(quote?.price));
            const change = node('td');
            const changeAmount = node('span', 'investment-cell-line', quote ? signed(quote.change) : '—');
            const changePercent = node('span', 'investment-cell-sub', quote ? percent(quote.change_percent) : 'Unavailable');
            movement(change, quote?.change);
            change.append(changeAmount, changePercent);
            if (quote) {
                const timestamp = `Quote: ${dateFormat.format(new Date(quote.quote_at))}`;
                price.title = timestamp;
                if (quote.stale) price.append(node('span', 'investment-cell-sub investment-stale', 'Saved quote'));
                row.title = timestamp + (quote.stale ? ' · Update unavailable' : '');
            } else {
                price.append(node('span', 'investment-cell-sub', 'Unavailable'));
            }
            const day = node('td', '', signed(quote?.stale ? null : entry.day_change));
            movement(day, quote?.stale ? null : entry.day_change);
            const editCell = node('td');
            const edit = node('a', 'text-button', 'Edit');
            edit.href = entry.edit_url;
            edit.setAttribute('aria-label', `Edit ${entry.symbol}`);
            editCell.append(edit);
            row.append(name, node('td', '', numbers.format(Number(entry.shares))), price, change,
                day, node('td', '', money(entry.market_value)), editCell);
            body.append(row);
        });
    }
    function renderWatchlist(entries) {
        entries.forEach(entry => {
            const row = section.querySelector(`[data-watch-id="${entry.id}"]`);
            if (!row) return;
            const target = row.querySelector('.investment-watch-price');
            const quote = entry.quote;
            target.replaceChildren(node('span', '', money(quote?.price)));
            const detail = node('span', 'investment-cell-sub', quote ? percent(quote.change_percent) : 'Unavailable');
            movement(detail, quote?.change);
            target.append(detail);
            if (quote) target.title = `${dateFormat.format(new Date(quote.quote_at))}${quote.stale ? ' · Saved quote' : ''}`;
            if (quote?.stale) target.append(node('span', 'investment-stale investment-cell-sub', 'Saved quote'));
        });
    }
    function renderNews() {
        const container = section.querySelector('#market-headlines');
        const symbol = section.querySelector('#news-filter').value;
        const selected = headlines.filter(article => !symbol || article.symbols.includes(symbol));
        container.replaceChildren();
        if (!selected.length) {
            container.append(node('p', 'empty-state', 'No recent articles are available for these holdings.'));
        }
        selected.slice(0, 8).forEach(article => {
            const item = node('article', 'market-headline investment-headline');
            const tags = node('p', 'investment-news-tags');
            article.symbols.forEach(ticker => tags.append(node('span', 'investment-ticker-chip', ticker)));
            const title = node('a', '', article.headline);
            title.href = article.url;
            title.target = '_blank';
            title.rel = 'noopener noreferrer';
            item.append(tags, title, node('p', 'market-headline-details', `${article.source} · ${dateFormat.format(new Date(article.published_at * 1000))} · Read article ↗`));
            container.append(item);
        });
    }
    function render(data) {
        renderHoldings(data.holdings);
        renderWatchlist(data.watchlist);
        headlines = data.headlines;
        renderNews();
        const summary = data.summary;
        section.querySelector('#portfolio-value-label').textContent = summary.stale && summary.complete ? 'Last-known portfolio value' : 'Portfolio value';
        section.querySelector('#portfolio-value').textContent = money(summary.market_value);
        section.querySelector('#holding-count').textContent = summary.count;
        const day = section.querySelector('#portfolio-day');
        day.textContent = signed(summary.day_change);
        movement(day, summary.day_change);
        const dayPercent = section.querySelector('#portfolio-day-percent');
        dayPercent.textContent = percent(summary.day_change_percent);
        movement(dayPercent, summary.day_change_percent);
        const quotes = [...data.holdings, ...data.watchlist].map(entry => entry.quote).filter(Boolean);
        const dates = quotes.map(quote => new Date(quote.quote_at).getTime());
        section.querySelector('#market-updated').textContent = dates.length
            ? `Oldest quote: ${dateFormat.format(new Date(Math.min(...dates)))} · Quotes refreshed about every 5 minutes`
            : 'No quotes available yet.';
        const warnings = data.errors.slice(0, 3);
        if (data.errors.length > 3) warnings.push('Some other market updates are also unavailable.');
        status.textContent = warnings.join(' ');
        status.hidden = !warnings.length;
        status.classList.toggle('market-status-error', warnings.length > 0);
    }
    function schedule() {
        clearTimeout(timer);
        if (visible && !document.hidden) timer = setTimeout(load, Math.max(1000, nextLoad - Date.now()));
    }
    async function load() {
        if (loading || !visible || document.hidden) return;
        if (Date.now() < nextLoad) return schedule();
        loading = true;
        refresh.disabled = true;
        refresh.textContent = 'Updating…';
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 20000);
        try {
            const response = await fetch(section.dataset.marketDataUrl, {
                headers: {Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
            });
            if (response.redirected) throw new Error('Your session expired. Sign in again to load your portfolio.');
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Market updates are temporarily unavailable.');
            render(data);
            nextLoad = Date.now() + data.refresh_seconds * 1000;
        } catch (error) {
            status.hidden = false;
            status.classList.add('market-status-error');
            status.textContent = 'Market updates are unavailable. Any displayed values are from the last successful update; check their quote times.';
            if (error.message.startsWith('Your session')) status.textContent = error.message;
            section.querySelector('#portfolio-value-label').textContent = 'Last-known portfolio value';
            section.querySelector('#portfolio-day').textContent = '—';
            section.querySelector('#portfolio-day-percent').textContent = '';
            nextLoad = Date.now() + 60000;
        } finally {
            clearTimeout(timeout);
            loading = false;
            refresh.disabled = false;
            refresh.textContent = 'Refresh';
            schedule();
        }
    }
    refresh.addEventListener('click', () => { nextLoad = 0; load(); });
    section.querySelector('#news-filter').addEventListener('change', renderNews);
    document.addEventListener('visibilitychange', () => { if (document.hidden) clearTimeout(timer); else load(); });
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(entries => {
            visible = entries[0].isIntersecting;
            if (visible) load(); else clearTimeout(timer);
        }, {rootMargin: '150px'}).observe(section);
    } else {
        visible = true;
        load();
    }
})();
