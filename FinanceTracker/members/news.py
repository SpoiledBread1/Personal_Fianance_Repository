from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


CNBC_FINANCE_FEED = "https://www.cnbc.com/id/10000664/device/rss/rss.html"


def fetch_cnbc_articles():
    request = Request(
        CNBC_FINANCE_FEED,
        headers={"User-Agent": "FinanceHub/1.0 (+https://www.cnbc.com/)"},
    )
    with urlopen(request, timeout=4) as response:
        root = ET.fromstring(response.read(1_000_000))

    articles = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        description = (item.findtext("description") or "").strip()
        link = (item.findtext("link") or "").strip()
        parsed_link = urlparse(link)
        if (
            not title
            or parsed_link.scheme != "https"
            or parsed_link.hostname not in {"cnbc.com", "www.cnbc.com"}
        ):
            continue

        published = (item.findtext("pubDate") or "").strip()
        try:
            published_at = parsedate_to_datetime(published)
            published_label = published_at.strftime("%b %d, %Y")
        except (TypeError, ValueError, OverflowError):
            published_label = ""

        articles.append(
            {
                "title": title[:250],
                "description": description[:500],
                "url": link,
                "published": published_label,
            }
        )
        if len(articles) == 12:
            break
    return articles
