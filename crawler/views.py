from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

social_media_domains = [
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "tiktok.com",
    "linkedin.com",
    "youtube.com",
    "pinterest.com",
    "x.com",
]

email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

CONCURRENCY_LIMIT = 50
BATCH_SIZE = 50


def fetch_links(url):
    if not url:
        return []
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        text = response.text
        soup = BeautifulSoup(text, "html.parser")
        links = [
            a_tag.get("href")
            for a_tag in soup.find_all("a", href=True)
            if "about" in a_tag.get("href", "").lower()
            or "about-us" in a_tag.get("href", "").lower()
            or "contact" in a_tag.get("href", "").lower()
            or "contact-us" in a_tag.get("href", "").lower()
        ]
        return links
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []


def fetch_text(url):
    if not url:
        return ""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return ""


def process_links(links, base_url, filter_social=False):
    processed_links = []
    for link in links:
        if filter_social and any(domain in link for domain in social_media_domains):
            continue
        if (
            "about" in link.lower()
            or "about-us" in link.lower()
            or "contact" in link.lower()
            or "contact-us" in link.lower()
        ):
            absolute_url = urljoin(base_url, link)
            processed_links.append(absolute_url)
    return processed_links


def get_emails(text):
    return list(set(re.findall(email_pattern, text)))


def get_phones(links):
    phones_set = set()
    for link in links:
        if link.startswith("tel:"):
            phone = link[len("tel:") :]
            phones_set.add(phone)
    return list(phones_set)


def check_social_media_links(links):
    social_links = set()
    for link in links:
        if any(domain in link for domain in social_media_domains):
            social_links.add(link)
    return list(social_links)


def crawl(url, executor):
    with executor as pool:
        initial_links = fetch_links(url)
        processed_links = process_links(initial_links, url)
        processed_links.append(url)

        new_urls_list = list(set(processed_links))

        all_links = []
        all_text = []
        future_to_url = {
            pool.submit(fetch_text, new_url): new_url for new_url in new_urls_list
        }

        for future in as_completed(future_to_url):
            url = future_to_url[future]
            text = future.result()
            if text:
                links = fetch_links(url)
                all_links.extend(process_links(links, url))
                all_text.append(text)

        all_links = list(set(initial_links + all_links))

        emails = get_emails("\n".join(all_text))
        phones = get_phones(all_links)
        social_media_links = check_social_media_links(all_links)

        return {"emails": emails, "phone_numbers": phones, "links": social_media_links}


def process_batch(urls):
    all_emails = set()
    with ThreadPoolExecutor(max_workers=CONCURRENCY_LIMIT) as executor:
        for url in urls:
            result = crawl(url, executor)
            all_emails.update(result["emails"])

    return all_emails


class CrawlView(APIView):
    def post(self, request):
        urls = request.data.get("urls", [])
        if not urls or not isinstance(urls, list):
            return Response(
                {"error": "Invalid input, 'urls' should be a list of URLs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        all_emails = set()
        for i in range(0, len(urls), BATCH_SIZE):
            batch_urls = urls[i : i + BATCH_SIZE]
            batch_emails = process_batch(batch_urls)
            all_emails.update(batch_emails)

        return Response({"emails": list(all_emails)}, status=status.HTTP_200_OK)
