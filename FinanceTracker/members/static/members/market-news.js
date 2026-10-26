const marketSection = document.querySelector('#stocks-news');
const marketStatus = document.querySelector('#market-status');
const marketQuotes = document.querySelector('#market-quotes');
const marketHeadlines = document.querySelector('#market-headlines');
const marketUpdated = document.querySelector('#market-updated');
const marketRetry = document.querySelector('#market-retry');

let marketDataLoaded = false;
let marketDataLoading = false;
let marketDataLoadedAt = 0;

function addEmptyMessage(container, message) {
    const empty = document.createElement('p');
    empty.className = 'empty-state';
    empty.textContent = message;
    container.append(empty);
}

function renderQuotes(quotes) {
    marketQuotes.replaceChildren();
    if (!quotes.length) {
        addEmptyMessage(marketQuotes, 'No stock prices are available right now.');
        return;
    }

    const currency = new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
    });
    const decimal = new Intl.NumberFormat('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    });

    quotes.forEach(quote => {
        const card = document.createElement('article');
        card.className = 'market-quote';

        const heading = document.createElement('div');
        heading.className = 'market-quote-heading';
        const symbol = document.createElement('h3');
        symbol.textContent = quote.symbol;
        const movement = document.createElement('span');
        movement.className = quote.change >= 0 ? 'market-positive' : 'market-negative';
        movement.textContent = `${quote.change >= 0 ? '+' : ''}${decimal.format(quote.change_percent)}%`;
        heading.append(symbol, movement);

        const price = document.createElement('p');
        price.className = 'market-quote-price';
        price.textContent = currency.format(quote.price);

        const change = document.createElement('p');
        change.className = 'market-quote-change';
        change.textContent = `${quote.change >= 0 ? '+' : ''}${currency.format(quote.change)} vs. previous close`;

        card.append(heading, price, change);
        marketQuotes.append(card);
    });
}

function renderHeadlines(headlines) {
    marketHeadlines.replaceChildren();
    if (!headlines.length) {
        addEmptyMessage(marketHeadlines, 'No recent headlines are available right now.');
        return;
    }

    const dateFormatter = new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
    });

    headlines.forEach(article => {
        const item = document.createElement('article');
        item.className = 'market-headline';

        const link = document.createElement('a');
        link.href = article.url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = article.headline;

        const details = document.createElement('p');
        details.className = 'market-headline-details';
        details.textContent = `${article.source} - ${dateFormatter.format(new Date(article.published_at * 1000))}`;

        item.append(link, details);
        marketHeadlines.append(item);
    });
}

async function loadMarketData() {
    if (!marketSection || marketDataLoading) return;
    marketDataLoading = true;
    marketStatus.textContent = 'Loading market data...';
    marketStatus.classList.remove('market-status-error');
    marketRetry.hidden = true;

    try {
        const response = await fetch(marketSection.dataset.marketDataUrl, {
            headers: { Accept: 'application/json' },
            credentials: 'same-origin',
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Market data could not be loaded.');

        renderQuotes(data.quotes);
        renderHeadlines(data.headlines);
        marketUpdated.textContent = `Updated ${new Intl.DateTimeFormat(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short',
        }).format(new Date(data.updated_at))}`;

        marketStatus.textContent = data.errors.length
            ? data.errors.join(' ')
            : 'Market data and headlines are up to date.';
        marketStatus.classList.toggle('market-status-error', data.errors.length > 0);
        marketStatus.setAttribute('role', data.errors.length ? 'alert' : 'status');
        marketRetry.hidden = data.errors.length === 0;
        marketDataLoaded = data.errors.length === 0;
        marketDataLoadedAt = Date.now();
    } catch (error) {
        marketStatus.textContent = error.message;
        marketStatus.classList.add('market-status-error');
        marketStatus.setAttribute('role', 'alert');
        marketRetry.hidden = false;
        console.error('Sable market data could not be loaded:', error);
    } finally {
        marketDataLoading = false;
    }
}

if (marketSection) {
    marketRetry.addEventListener('click', loadMarketData);
    window.addEventListener('hashchange', () => {
        if (
            window.location.hash === '#stocks-news'
            && (!marketDataLoaded || Date.now() - marketDataLoadedAt >= 300000)
        ) {
            loadMarketData();
        }
    });
    if (window.location.hash === '#stocks-news') loadMarketData();
}
