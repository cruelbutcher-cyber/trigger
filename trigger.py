import streamlit as st
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from collections import deque
import csv
import datetime
import re
import time
from io import StringIO

class EnhancedWebCrawler:
    def __init__(self, start_url, max_pages=9):
        self.session = requests.Session()
        self.start_url = start_url
        self.keywords = ["gowithguide", "go with guide", "go-with-guide", "87121"]
        self.main_domain = urlparse(start_url).netloc
        self.max_pages = max_pages
        self.visited = set()
        self.results = []
        self.queue = deque()
        self.categories = []
        self.current_category = None
        self.status_messages = []
        self.user_stopped = False
        self.pages_crawled = 0
        self.redirect_cache = {}

    def is_subdomain_of(self, url_netloc):
        main_domain = self.main_domain.replace("www.", "").lower()
        url_netloc = url_netloc.replace("www.", "").lower()
        return url_netloc.endswith("." + main_domain) or url_netloc == main_domain

    def resolve_redirects(self, url):
        if url in self.redirect_cache:
            return self.redirect_cache[url]
        try:
            response = self.session.head(url, allow_redirects=True, timeout=10, 
                                        headers={'User-Agent': 'Mozilla/5.0'})
            final_url = response.url
            history = [r.url for r in response.history]
            if not history and url != final_url:
                response_get = self.session.get(url, allow_redirects=False, timeout=10)
                if 300 <= response_get.status_code < 400:
                    location = response_get.headers.get('Location', '')
                    if location:
                        history = [url]
                        final_url = location
            self.redirect_cache[url] = (final_url, history)
            return final_url, history
        except Exception as e:
            self.status_messages.append(f"Error resolving redirects for {url}: {str(e)}")
            return url, []

    def get_matched_keywords(self, text):
        text_lower = str(text).lower().strip()
        exact_matches = []
        for kw in self.keywords:
            kw_lower = kw.lower()
            if kw_lower in text_lower:
                exact_matches.append(kw)
        for kw in self.keywords:
            kw_encoded = kw.replace(' ', '%20')
            if kw_encoded.lower() in text_lower:
                exact_matches.append(kw)
        url_patterns = [
            r'(?:https?://)?(?:www\.)?gowithguide\.com',
            r'utm_source=([^&]*)',
            r'utm_campaign=([^&]*)',
            r'sv1=([^&]*)',
            r'awc=([^&]*)',
            r'87121(?:_\d+|%5F\d+)?'
        ]
        for pattern in url_patterns:
            matches = re.findall(pattern, text_lower)
            if matches:
                for match in matches:
                    if isinstance(match, str):
                        for kw in self.keywords:
                            if kw.lower() in match.lower():
                                exact_matches.append(kw)
        return list(set(exact_matches))

    def check_url_for_keywords(self, url, source_url):
        matched_kws = self.get_matched_keywords(url)
        if matched_kws:
            self.add_result(
                source_url=source_url,
                matched_url=url,
                element='url',
                attribute='href',
                content=url,
                keywords=matched_kws,
                location_type='direct_url'
            )
        final_url, history = self.resolve_redirects(url)
        if final_url != url:
            matched_kws_final = self.get_matched_keywords(final_url)
            if matched_kws_final:
                self.add_result(
                    source_url=source_url,
                    matched_url=final_url,
                    element='url',
                    attribute='href',
                    content=f"Redirected from: {url} to: {final_url}",
                    keywords=matched_kws_final,
                    location_type='redirected_url'
                )
        for intermediate_url in history:
            matched_kws_intermediate = self.get_matched_keywords(intermediate_url)
            if matched_kws_intermediate:
                self.add_result(
                    source_url=source_url,
                    matched_url=intermediate_url,
                    element='url',
                    attribute='href',
                    content=f"Redirect chain URL: {intermediate_url}",
                    keywords=matched_kws_intermediate,
                    location_type='redirect_chain_url'
                )

    def process_url(self, url):
        if url in self.visited or self.pages_crawled >= self.max_pages:
            return []
        self.visited.add(url)
        self.pages_crawled += 1
        try:
            response = self.session.get(url, headers={'User-Agent': 'Mozilla/5.0'}, 
                                     timeout=15, allow_redirects=True)
            response.raise_for_status()
        except Exception as e:
            self.status_messages.append(f"Error fetching {url}: {str(e)}")
            return []
        if 'text/html' not in response.headers.get('Content-Type', ''):
            return []
        final_url = response.url
        soup = BeautifulSoup(response.text, 'lxml')
        elements = soup.find_all(['a', 'div', 'section', 'title', 'main', 
                                'article', 'span', 'p', 'img', 'meta', 'iframe'])
        for element in elements:
            self.check_element(element, final_url)
        script_tags = soup.find_all('script')
        for script in script_tags:
            if script.string:
                urls_in_js = re.findall(r'(https?://[^\s\'"]+)', script.string)
                for js_url in urls_in_js:
                    self.check_url_for_keywords(js_url, final_url)
        return []

    def check_element(self, element, source_url):
        element_type = element.name if element.name else 'unknown'
        if element.has_attr('href'):
            href = element['href'].strip()
            if href:
                resolved_url = urljoin(source_url, href)
                self.check_url_for_keywords(href, source_url)
                text = element.get_text(separator=' ', strip=True)
                matched_kws = self.get_matched_keywords(text)
                if matched_kws:
                    self.add_result(
                        source_url=source_url,
                        matched_url=resolved_url,
                        element=element_type,
                        attribute='text',
                        content=text,
                        keywords=matched_kws,
                        location_type='anchor_text'
                    )
        if element.name in ['p', 'div', 'span', 'title', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            text = element.get_text(separator=' ', strip=True)
            matched_kws = self.get_matched_keywords(text)
            if matched_kws:
                self.add_result(
                    source_url=source_url,
                    matched_url=source_url,
                    element=element_type,
                    attribute='text',
                    content=text,
                    keywords=matched_kws,
                    location_type='content'
                )
        if element.name == 'meta' and element.get('content'):
            content = element['content'].strip()
            matched_kws = self.get_matched_keywords(content)
            if matched_kws:
                attr_name = element.get('name') or element.get('property') or 'meta'
                self.add_result(
                    source_url=source_url,
                    matched_url=source_url,
                    element=element_type,
                    attribute=attr_name,
                    content=content,
                    keywords=matched_kws,
                    location_type='meta'
                )
        if element.name == 'img' and element.get('alt'):
            alt_text = element['alt'].strip()
            matched_kws = self.get_matched_keywords(alt_text)
            if matched_kws:
                self.add_result(
                    source_url=source_url,
                    matched_url=source_url,
                    element=element_type,
                    attribute='alt',
                    content=alt_text,
                    keywords=matched_kws,
                    location_type='alt_text'
                )
        for attr in element.attrs:
            if attr.startswith('data-') and isinstance(element[attr], str):
                if 'url' in attr.lower() or 'href' in attr.lower():
                    data_url = element[attr].strip()
                    if data_url:
                        self.check_url_for_keywords(data_url, source_url)

    def add_result(self, source_url, matched_url, element, attribute, content, keywords, location_type):
        for keyword in keywords:
            self.results.append({
                'source_url': source_url,
                'matched_url': matched_url,
                'element': element,
                'attribute': attribute,
                'keyword': keyword,
                'content': content[:500],
                'location_type': location_type,
                'timestamp': datetime.datetime.now().isoformat()
            })

    def extract_categories(self):
        try:
            response = self.session.get(self.start_url)
            soup = BeautifulSoup(response.text, 'lxml')
            categories = []
            category_priority = ['travel', 'blog', 'resources']
            for link in soup.find_all('a', href=True):
                href = link['href'].lower()
                text = link.get_text().lower()
                if '/category/' in href or any(cat in href or cat in text for cat in category_priority):
                    full_url = urljoin(self.start_url, href)
                    cat_match = re.search(r'/category/([^/]+)', href)
                    if cat_match:
                        cat_name = cat_match.group(1).lower()
                    else:
                        for cat in category_priority:
                            if cat in href or cat in text:
                                cat_name = cat
                                break
                        else:
                            cat_name = 'other'
                    categories.append((cat_name, full_url))
            sorted_categories = []
            for cat in category_priority:
                matched = [c for c in categories if c[0] == cat]
                if matched:
                    sorted_categories.append(matched[0])
            remaining = [c for c in categories if c[0] not in category_priority]
            sorted_categories.extend(remaining)
            return sorted_categories[:5]
        except Exception as e:
            st.error(f"Error extracting categories: {str(e)}")
            return []

    def get_main_pages(self):
        try:
            response = self.session.get(self.start_url)
            soup = BeautifulSoup(response.text, 'lxml')
            main_links = []
            for link in soup.find_all('a', href=True):
                url = urljoin(self.start_url, link['href'])
                if (self.is_subdomain_of(urlparse(url).netloc) and 
                    url not in main_links and 
                    url != self.start_url):
                    main_links.append(url)
            return main_links[:8]
        except Exception as e:
            st.error(f"Error getting main pages: {str(e)}")
            return []

    def get_category_pages(self, category_url):
        try:
            response = self.session.get(category_url)
            soup = BeautifulSoup(response.text, 'lxml')
            article_links = []
            for link in soup.find_all('a', href=True):
                url = urljoin(category_url, link['href'])
                if (self.is_subdomain_of(urlparse(url).netloc) and 
                    url not in article_links and 
                    url != category_url):
                    if ('/article/' in url or 
                        '/post/' in url or 
                        '/blog/' in url or 
                        '/news/' in url or
                        re.search(r'/\d{4}/\d{2}/', url)):
                        article_links.append(url)
            try:
                article_links.sort(key=lambda x: re.findall(r'/(\d{4})/(\d{2})/', x)[-1], reverse=True)
            except:
                pass
            return article_links[:self.max_pages]
        except Exception as e:
            st.error(f"Error getting category pages: {str(e)}")
            return []

def main():
    st.set_page_config(page_title="Web Crawler", page_icon="🌐", layout="wide")
    # Initialize session state
    if 'crawler' not in st.session_state:
        st.session_state.crawler = None
        st.session_state.running = False
        st.session_state.results = []
        st.session_state.status = []
        st.session_state.categories = []
    # UI Components
    st.title("Enhanced Web Crawler")
    st.write("Search for GoWithGuide references on a website.")
    col1, col2 = st.columns([3, 1])
    with col1:
        url_input = st.text_input("Enter website URL:", "https://example.com")
    with col2:
        max_pages = st.number_input("Max pages per section:", min_value=1, value=9, step=1)
    start_btn = st.button("Start Crawling")
    stop_btn = st.button("Stop & Reset")
    # Status and Results Display
    status_container = st.empty()
    results_container = st.empty()
    # Handle Start Button
    if start_btn and not st.session_state.running:
        if not url_input.startswith(('http://', 'https://')):
            url_input = f'https://{url_input}'
        st.session_state.crawler = EnhancedWebCrawler(start_url=url_input, max_pages=max_pages)
        st.session_state.running = True
        st.session_state.results = []
        st.session_state.status = [f"Starting crawl of {url_input}"]
        st.session_state.categories = []
    # Handle Stop Button
    if stop_btn:
        st.session_state.running = False
        st.session_state.crawler = None
        st.session_state.results = []
        st.session_state.status = []
        st.session_state.categories = []
    # Crawling Logic
    if st.session_state.running and st.session_state.crawler:
        crawler = st.session_state.crawler
        progress_bar = st.progress(0)
        # Crawl homepage and main pages
        if not st.session_state.categories:
            homepage_links = crawler.get_main_pages()
            st.session_state.status.append("Crawling homepage and main pages...")
            urls_to_crawl = [crawler.start_url] + homepage_links
            for i, url in enumerate(urls_to_crawl[:crawler.max_pages]):
                if not st.session_state.running:
                    break
                st.session_state.status.append(f"Crawling: {url}")
                crawler.process_url(url)
                st.session_state.results = crawler.results
                progress_bar.progress((i + 1) / min(crawler.max_pages, len(urls_to_crawl)))
                if crawler.results:
                    st.session_state.status.append(f"Found {len(crawler.results)} matches")
                    break
            if not crawler.results:
                st.session_state.status.append("No matches found in homepage section.")
                st.session_state.categories = crawler.extract_categories()
                if st.session_state.categories:
                    st.session_state.status.append(f"Found categories: {', '.join([c[0] for c in st.session_state.categories])}")
                else:
                    st.session_state.status.append("No categories found.")
                    st.session_state.running = False
        # Crawl categories
        elif st.session_state.categories:
            cat_name, cat_url = st.session_state.categories.pop(0)
            st.session_state.status.append(f"Processing category: {cat_name}")
            category_links = crawler.get_category_pages(cat_url)
            if not category_links:
                st.session_state.status.append(f"No pages found in {cat_name} category")
            else:
                for i, url in enumerate(category_links[:crawler.max_pages]):
                    if not st.session_state.running:
                        break
                    st.session_state.status.append(f"Crawling: {url}")
                    crawler.process_url(url)
                    st.session_state.results = crawler.results
                    progress_bar.progress((i + 1) / crawler.max_pages)
                    if crawler.results:
                        st.session_state.status.append(f"Found {len(crawler.results)} matches")
                        break
                if not crawler.results:
                    st.session_state.status.append(f"No matches found in {cat_name} category")
            if not st.session_state.categories and not crawler.results:
                st.session_state.running = False
        # Display Status
        with status_container.container():
            st.subheader("Status")
            for msg in st.session_state.status[-10:]:  # Show last 10 messages
                st.write(msg)
        # Display Results and Options
        if st.session_state.results:
            with results_container.container():
                st.subheader("Matches Found")
                for i, result in enumerate(st.session_state.results[-5:], 1):  # Show last 5
                    st.markdown(f"""
                    **Match {i}:**  
                    **Source URL:** {result['source_url']}  
                    **Matched URL:** {result['matched_url']}  
                    **Keyword:** {result['keyword']}  
                    **Location:** {result['location_type']}  
                    **Element:** {result['element']} [{result['attribute']}]  
                    **Content:** `{result['content'][:100]}...`
                    """)
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("Save Results & Stop"):
                        csv_data = generate_csv(crawler.results)
                        st.download_button(
                            label="Download CSV",
                            data=csv_data,
                            file_name=f"crawl_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                        st.session_state.running = False
                        crawler.user_stopped = True
                with col2:
                    if st.button("Continue to Next Category"):
                        crawler.pages_crawled = 0
                with col3:
                    if st.button("Continue Current Category"):
                        crawler.pages_crawled = 0
        # Final Report
        if not st.session_state.running and st.session_state.results and not crawler.user_stopped:
            csv_data = generate_csv(crawler.results)
            st.download_button(
                label="Download Final Results",
                data=csv_data,
                file_name=f"crawl_report_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

def generate_csv(results):
    csv_file = StringIO()
    writer = csv.DictWriter(csv_file, fieldnames=[
        'source_url', 'matched_url', 'keyword', 
        'location_type', 'element', 'attribute',
        'content_sample', 'timestamp'
    ])
    writer.writeheader()
    for result in results:
        writer.writerow({
            'source_url': result['source_url'],
            'matched_url': result['matched_url'],
            'keyword': result['keyword'],
            'location_type': result['location_type'],
            'element': result['element'],
            'attribute': result['attribute'],
            'content_sample': result['content'][:300],
            'timestamp': result['timestamp']
        })
    return csv_file.getvalue()

if __name__ == "__main__":
    main()
