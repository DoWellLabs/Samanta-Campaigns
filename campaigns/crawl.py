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
        return [], url
    try:
        async with session.get(url, headers=HEADERS, timeout=10) as response:
            response.raise_for_status()
            text = await response.text()
            soup = BeautifulSoup(text, 'html.parser')
            links = [a_tag.get('href') for a_tag in soup.find_all('a', href=True)]
            print(f'Fetched {len(links)} links from {url}')
            return links, url
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"Error fetching {url}: {e}")
        return [], url

async def get_links_async(urls_list):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_links(session, url) for url in urls_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return results

def process_links(results, filter_social=False):
    links = []
    for result in results:
        if isinstance(result, tuple):
            result_links, base_url = result
            for link in result_links:
                if filter_social and any(domain in link for domain in social_media_domains):
                    continue
                absolute_url = urljoin(base_url, link)
                links.append(absolute_url)
        else:
            print(f"Skipping result due to error: {result}")
    return links

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

async def crawl(urls_list):
    print("Crawling URLs:", urls_list)
    initial_results = await get_links_async(urls_list)
    initial_links = process_links(initial_results)
    
    # Removing duplicates by converting to a set
    new_urls_list = list(set(initial_links))
    
    # Fetching new set of URLs
    new_results = await get_links_async(new_urls_list)
    new_links = process_links(new_results)
    
    # Combine all links
    all_links = initial_links + new_links
    
    emails = get_emails(all_links)
    phones = get_phones(all_links)
    social_media_links = check_social_media_links(all_links)
    
    data = {
        "emails": emails,
        "phone_numbers": phones,
    }
    print("Data after crawling:", data)
    return data
