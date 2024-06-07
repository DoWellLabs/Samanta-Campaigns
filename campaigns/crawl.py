import aiohttp
import asyncio
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_10_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/39.0.2171.95 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

social_media_domains = [
    'facebook.com', 'instagram.com', 'twitter.com',
    'tiktok.com', 'linkedin.com', 'youtube.com',
    'pinterest.com', 'x.com'
]

email_pattern = r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'

async def fetch_links(session, url):
    if not url:
        print("Empty URL encountered, skipping.")
        return []
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as response:
            response.raise_for_status()
            text = await response.text()
            soup = BeautifulSoup(text, 'html.parser')
            links = [a_tag.get('href') for a_tag in soup.find_all('a', href=True)]
            print(f'Fetched {len(links)} links from {url}')
            return links
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"Error fetching {url}: {e}")
        return []

async def get_links_async(url):
    async with aiohttp.ClientSession() as session:
        links = await fetch_links(session, url)
    return links

def process_links(links, base_url, filter_social=False):
    processed_links = []
    for link in links:
        if filter_social and any(domain in link for domain in social_media_domains):
            continue
        absolute_url = urljoin(base_url, link)
        processed_links.append(absolute_url)
    return processed_links

def get_emails(links):
    emails_set = set()
    for link in links:
        emails = re.findall(email_pattern, link)
        if emails:
            emails_set.update(emails)
    return list(emails_set)

def get_phones(links):
    phones_set = set()
    for link in links:
        if link.startswith('tel:'):
            phone = link[len('tel:'):]
            phones_set.add(phone)
    return list(phones_set)

def check_social_media_links(links):
    social_links = set()
    for link in links:
        if any(domain in link for domain in social_media_domains):
            social_links.add(link)
    return list(social_links)

async def crawl(url):
    print("Crawling URL:", url)
    initial_links = await get_links_async(url)
    processed_links = process_links(initial_links, url)
    
    # Removing duplicates by converting to a set
    new_urls_list = list(set(processed_links))
    
    # Fetching new set of URLs
    all_links = []
    async with aiohttp.ClientSession() as session:
        for new_url in new_urls_list:
            links = await fetch_links(session, new_url)
            all_links.extend(process_links(links, new_url))
    
    # Combine all links
    all_links = list(set(initial_links + all_links))
    
    emails = get_emails(all_links)
    phones = get_phones(all_links)
    social_media_links = check_social_media_links(all_links)
    
    data = {
        "emails": emails,
        "phone_numbers": phones,
        "links": social_media_links
    }
    print("Data after crawling:", data)
    return data

# Example usage:
# url = 'http://example.com'
# asyncio.run(crawl(url))
