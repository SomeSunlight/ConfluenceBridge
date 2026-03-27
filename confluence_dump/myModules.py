# -*- coding: utf-8 -*-
"""
⚠️ DEPRECATED: This module is being phased out in favor of the new ETL-Pipeline architecture.

Legacy module to abstract Confluence API calls and provide local file/directory utilities.
Supports both Confluence Cloud and Data Center platforms.
Includes BeautifulSoup logic for HTML processing (downloading assets, fixing links, injecting sidebar).

MIGRATION NOTICE:
- API calls have been moved to: confluence_dump/api/client.py
- HTML processing has been moved to: confluence_dump/transform/html_processor.py
- Link rewriting has been moved to: confluence_dump/transform/link_rewriter.py
- Sidebar building has been moved to: confluence_dump/transform/sidebar_builder.py

This module is only used for legacy mode (without --use-etl flag).
For new features, use the ETL-Pipeline modules instead.
"""

import os
import sys
import requests
import configparser
import re
from requests.auth import HTTPBasicAuth
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup, Comment
from datetime import datetime

# --- Globals for output directories ---
outdir_base = ""
outdir_pages = ""
outdir_attachments = ""
outdir_styles = ""
outdir_logs = ""


# --- Setup Functions ---

def set_variables():
    """ Sets and returns global variables. """
    global page_ids_in_space, page_names_in_space, attachments_in_space
    page_ids_in_space = []
    page_names_in_space = []
    attachments_in_space = []
    return


def setup_output_directories(base_outdir):
    """ Sets global directory variables and robustly creates them. """
    global outdir_base, outdir_pages, outdir_attachments, outdir_styles, outdir_logs

    outdir_base = base_outdir.rstrip('/') + '/'
    outdir_pages = outdir_base + "pages/"
    outdir_attachments = outdir_base + "attachments/"
    outdir_styles = outdir_base + "styles/"
    outdir_logs = outdir_base + "logs/"

    try:
        os.makedirs(outdir_pages, exist_ok=True)
        os.makedirs(outdir_attachments, exist_ok=True)
        os.makedirs(outdir_styles, exist_ok=True)
        os.makedirs(outdir_logs, exist_ok=True)
    except Exception as e:
        print(f"Fatal Error creating directories: {e}", file=sys.stderr)
        sys.exit(1)
    return


# --- Configuration & Auth ---

def load_platform_config(profile_name):
    config = configparser.ConfigParser()
    if not os.path.exists('confluence_products.ini'):
        print("Error: 'confluence_products.ini' not found.", file=sys.stderr)
        sys.exit(1)
    config.read('confluence_products.ini')
    if profile_name not in config:
        print(f"Error: Profile '{profile_name}' not found.", file=sys.stderr)
        sys.exit(1)
    return dict(config[profile_name])


def get_auth_config(platform_config):
    auth_method = platform_config.get('auth_method')
    if auth_method == 'basic_api_token':
        try:
            return HTTPBasicAuth(os.environ['CONFLUENCE_USER'], os.environ['CONFLUENCE_TOKEN'])
        except KeyError:
            print("Error: Missing CONFLUENCE_USER/TOKEN for Cloud.", file=sys.stderr)
            sys.exit(1)
    elif auth_method == 'bearer_pat':
        try:
            return {'Authorization': f"Bearer {os.environ['CONFLUENCE_TOKEN']}"}
        except KeyError:
            print("Error: Missing CONFLUENCE_TOKEN for Data Center.", file=sys.stderr)
            sys.exit(1)
    return None


# --- API Helpers ---

def _build_api_url(base_url, platform_config, context_path_override, template_key, path_params=None):
    if path_params is None: path_params = {}
    template = platform_config.get(template_key)
    if not template:
        print(f"Error: Template '{template_key}' missing in INI.", file=sys.stderr)
        sys.exit(1)

    if platform_config.get('platform_type') == 'dc':
        # Data Center Context Path Logic
        c_path = context_path_override if context_path_override is not None else platform_config.get(
            'default_context_path', '')
        if c_path:
            c_path = '/' + c_path.strip().strip('/')
        else:
            c_path = ''
        path_params['context_path'] = c_path

    return f"{base_url.rstrip('/')}{template.format(**path_params)}"


def _execute_get_request(url, auth_info, params=None):
    """ Executes GET request. Prints ERRORS to stderr, but stays silent on success. """
    headers = {"Accept": "application/json"}
    if isinstance(auth_info, dict): headers.update(auth_info)

    try:
        resp = requests.get(url, headers=headers, auth=auth_info if not isinstance(auth_info, dict) else None,
                            params=params)
        resp.raise_for_status()

        # Robust check for HTML responses (SSO redirects) with specific hints
        if 'application/json' not in resp.headers.get('Content-Type', ''):
            print(f"Error: Non-JSON response from {url} (Content-Type: {resp.headers.get('Content-Type')})",
                  file=sys.stderr)
            if isinstance(auth_info, dict):
                print("[Hint]: Check VPN/Intranet connection for Data Center.", file=sys.stderr)
            return None
        return resp.json()
    except Exception as e:
        print(f"Request Error: {e}", file=sys.stderr)
        return None


def get_page_view_url(base_url, platform_config, context_path_override, spaceKey, pageId):
    path_params = {'spaceKey': spaceKey, 'pageId': pageId}
    return _build_api_url(base_url, platform_config, context_path_override, 'url_view_page', path_params)


# --- Downloader ---

def download_file(url, local_filename, auth_info):
    headers = {}
    auth_obj = None
    if isinstance(auth_info, dict):
        headers.update(auth_info)
    else:
        auth_obj = auth_info

    try:
        with requests.get(url, headers=headers, auth=auth_obj, stream=True) as r:
            r.raise_for_status()
            with open(local_filename, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"Download Error {url}: {e}", file=sys.stderr)
        return False


# --- Anchor Repair Logic (Improved) ---

def parse_anchors_from_storage(storage_xml):
    """
    Parses the Confluence Storage Format (XML) to extract links that have anchors.
    Returns a list of dicts: {'text': link_text, 'anchor': anchor_name, 'target_title': title_or_None}
    Handles both prefixed (ac:link) and stripped (link) namespace tags.
    """
    if not storage_xml:
        return []

    # FIX: Wrap content in a dummy root tag.
    # Confluence storage format is often a fragment (multiple top-level elements).
    wrapped_xml = f"<root>{storage_xml}</root>"

    try:
        # Use XML parser if possible to handle namespaces correctly
        soup = BeautifulSoup(wrapped_xml, 'xml')
    except:
        # Fallback
        soup = BeautifulSoup(storage_xml, 'html.parser')

    anchor_candidates = []

    # Search for link tags (with and without 'ac:' prefix)
    # 'link' is common when lxml strips undefined namespaces
    links = soup.find_all(['ac:link', 'AC:LINK', 'link'])

    for link in links:
        # Check anchor attribute (ac:anchor, AC:ANCHOR, or just anchor)
        anchor = link.get('ac:anchor') or link.get('AC:ANCHOR') or link.get('anchor')

        if anchor:
            # Check if it links to another page
            target_title = None
            # Search for page resource identifier (ri:page, RI:PAGE, or page)
            ri_page = link.find(['ri:page', 'RI:PAGE', 'page'])
            if ri_page:
                target_title = ri_page.get('ri:content-title') or ri_page.get('RI:CONTENT-TITLE') or ri_page.get(
                    'content-title')

            # Extract Link Text
            text = link.get_text(" ", strip=True)
            if text:
                anchor_candidates.append({
                    'text': text,
                    'anchor': anchor,
                    'target_title': target_title
                })

    return anchor_candidates


def generate_confluence_anchor(page_title, anchor_name):
    """
    Simulates Confluence ID generation: PageTitle (no spaces) + '-' + AnchorName
    """
    if not page_title:
        return anchor_name  # Fallback: just the anchor if local

    # Remove spaces from title
    clean_title = page_title.replace(" ", "")
    return f"{clean_title}-{anchor_name}"


# --- HTML Processor ---

def inject_sidebar(soup, sidebar_html, current_page_id):
    """ Injects the sidebar HTML and wrapper. """
    if not sidebar_html: return soup

    sidebar_soup = BeautifulSoup(sidebar_html, 'html.parser')
    target_href = f"{current_page_id}.html"
    active_link = sidebar_soup.find('a', href=target_href)

    if active_link:
        active_link['class'] = active_link.get('class', []) + ['active-page']
        parent = active_link.parent
        while parent:
            if parent.name == 'details':
                parent['open'] = ''
            parent = parent.parent

    if soup.body:
        toggle_btn = soup.new_tag('button', id='sidebar-toggle', attrs={'title': 'Toggle Sidebar'})
        toggle_btn.string = "☰"

        layout_div = soup.new_tag('div', attrs={'class': 'layout-container'})

        aside = soup.new_tag('aside', id='sidebar')
        aside.append(Comment(" CONFLUENCE-SIDEBAR-START "))
        if sidebar_soup.body:
            for child in list(sidebar_soup.body.children): aside.append(child)
        else:
            for child in list(sidebar_soup.children): aside.append(child)
        aside.append(Comment(" CONFLUENCE-SIDEBAR-END "))

        resizer = soup.new_tag('div', id='resizer')
        main_content = soup.new_tag('main', id='content')

        for content in list(soup.body.contents):
            main_content.append(content)

        layout_div.append(aside)
        layout_div.append(resizer)
        layout_div.append(main_content)

        soup.body.clear()
        soup.body.append(toggle_btn)
        soup.body.append(layout_div)

        script = soup.new_tag('script')
        script.string = """
            document.addEventListener('DOMContentLoaded', function() {
                const btn = document.getElementById('sidebar-toggle');
                const sidebar = document.getElementById('sidebar');
                const resizer = document.getElementById('resizer');

                const savedWidth = localStorage.getItem('sidebarWidth');
                if (savedWidth && sidebar) {
                    sidebar.style.width = savedWidth;
                    sidebar.style.flexBasis = savedWidth;
                }

                if (btn && sidebar) {
                    btn.addEventListener('click', function() {
                        sidebar.classList.toggle('collapsed');
                    });
                }

                if (resizer && sidebar) {
                    let isResizing = false;
                    resizer.addEventListener('mousedown', (e) => {
                        isResizing = true;
                        document.body.style.cursor = 'col-resize';
                        resizer.classList.add('active');
                    });
                    document.addEventListener('mousemove', (e) => {
                        if (!isResizing) return;
                        let newWidth = e.clientX;
                        if (newWidth < 50) newWidth = 50;
                        if (newWidth > window.innerWidth * 0.6) newWidth = window.innerWidth * 0.6;
                        sidebar.style.width = newWidth + 'px';
                        sidebar.style.flexBasis = newWidth + 'px';
                    });
                    document.addEventListener('mouseup', () => {
                        if (isResizing) {
                            localStorage.setItem('sidebarWidth', sidebar.style.width);
                        }
                        isResizing = false;
                        document.body.style.cursor = 'default';
                        resizer.classList.remove('active');
                    });
                }
            });
        """
        soup.body.append(script)
    return soup


def process_page_content(html_content, page_metadata, base_url, auth_info, css_files=None, exported_page_ids=None,
                         sidebar_html=None, storage_content=None):
    """
    ⚠️ DEPRECATED: Use confluence_dump.transform.html_processor.HTMLProcessor instead.
    
    Legacy HTML processing function.
    Parses the HTML content.
    Includes smart Anchor Repair based on Storage Format.
    Uses strict separation of Extraction and Rewrite logic to prevent regression.
    Includes fallback for locally existing files (even if not in current export batch).
    
    This function is only used in legacy mode (without --use-etl flag).
    """
    soup = BeautifulSoup(html_content or "", 'html.parser')
    valid_ids = set(exported_page_ids) if exported_page_ids else set()
    page_id = page_metadata.get('id')
    current_page_title = page_metadata.get('title', 'Untitled')

    # 0. Anchor Repair Preparation
    anchor_repair_queue = []
    if storage_content:
        anchor_repair_queue = parse_anchors_from_storage(storage_content)

    # 1. Metadata Injection (Head)
    if not soup.head:
        head = soup.new_tag('head')
        soup.insert(0, head)

    title_tag = soup.new_tag('title')
    title_tag.string = current_page_title
    soup.head.append(title_tag)

    meta_id = soup.new_tag('meta', attrs={'name': 'confluence-page-id', 'content': page_id})
    soup.head.append(meta_id)

    labels = [l['name'] for l in page_metadata.get('metadata', {}).get('labels', {}).get('results', [])]
    meta_labels = soup.new_tag('meta', attrs={'name': 'confluence-labels', 'content': ', '.join(labels)})
    soup.head.append(meta_labels)

    # --- Inject Title & Metadata in Body ---
    if not soup.body:
        body = soup.new_tag('body')
        for element in list(soup.children):
            if element.name != 'head':
                body.append(element)
        soup.append(body)

    h1 = soup.new_tag('h1')
    h1.string = current_page_title

    version_info = page_metadata.get('version', {})
    author_name = "Unknown"
    date_str = "Unknown Date"
    if 'by' in version_info and 'displayName' in version_info['by']:
        author_name = version_info['by']['displayName']
    if 'when' in version_info:
        try:
            dt = datetime.strptime(version_info['when'].split('.')[0], "%Y-%m-%dT%H:%M:%S")
            date_str = dt.strftime("%d. %b %Y")
        except:
            date_str = version_info['when']

    meta_div = soup.new_tag('div', attrs={'class': 'page-metadata'})
    meta_ul = soup.new_tag('ul')
    meta_li = soup.new_tag('li', attrs={'class': 'page-metadata-modification-info'})
    meta_li.append("Zuletzt aktualisiert von ")
    span_author = soup.new_tag('span', attrs={'class': 'author'})
    span_author.string = author_name
    meta_li.append(span_author)
    meta_li.append(" am ")
    span_date = soup.new_tag('span', attrs={'class': 'last-modified'})
    span_date.string = date_str
    meta_li.append(span_date)
    meta_ul.append(meta_li)
    meta_div.append(meta_ul)

    soup.body.insert(0, meta_div)
    soup.body.insert(0, h1)

    # CSS Injection
    style_tag = soup.new_tag('style')
    style_tag.string = """
        /* Global Reset */
        *, *::before, *::after { box-sizing: border-box; }
        body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
        .layout-container { display: flex; height: 100vh; overflow: hidden; }

        #sidebar { 
            flex: 0 0 auto; width: 350px; min-width: 50px; border-right: 1px solid #ddd; 
            overflow-y: auto; padding: 10px; padding-left: 15px; padding-top: 60px; padding-right: 4px; 
            background: #f4f5f7; font-size: 14px; resize: horizontal; position: relative;
        }
        #sidebar.collapsed { width: 0px !important; min-width: 0 !important; padding: 0; border: none; overflow: hidden; flex-basis: 0 !important; }
        #sidebar-toggle { position: fixed; top: 15px; left: 15px; z-index: 9999; background: rgba(255, 255, 255, 0.9); border: 1px solid #ccc; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); font-size: 20px; cursor: pointer; color: #42526e; width: 32px; height: 32px; line-height: 30px; text-align: center; padding: 0; }
        #sidebar-toggle:hover { background: #ebecf0; }
        #resizer { width: 5px; cursor: col-resize; background-color: transparent; border-left: 1px solid #eee; flex: 0 0 auto; z-index: 10; }
        #resizer:hover, #resizer.active { background-color: #4c9aff; }

        #content { flex: 1; overflow-y: auto; padding: 40px 30px !important; max-width: 100%; }

        h1 { margin-top: 0; color: #172b4d; font-size: 2em; font-weight: 600; }
        .page-metadata { margin-bottom: 20px; font-size: 12px; color: #6b778c; }
        .page-metadata ul { list-style: none; padding: 0; margin: 0; }
        .page-metadata li { display: inline-block; margin-right: 10px; }

        #sidebar ul { list-style: none; padding-left: 28px; margin: 0; }
        #sidebar li { margin: 4px 0; white-space: normal; word-wrap: break-word; }
        #sidebar li.leaf { list-style: disc; margin-left: 18px; } 
        #sidebar li.folder { list-style: none; }
        #sidebar summary { cursor: pointer; font-weight: 500; margin-bottom: 2px; color: #42526e; outline: none; }
        #sidebar a { text-decoration: none; color: #42526e; }
        #sidebar a:hover { color: #0052cc; text-decoration: underline; }
        #sidebar a.active-page { color: #0052cc; font-weight: bold; }
        #sidebar details > summary { list-style: none; }
        #sidebar details > summary::-webkit-details-marker { display: none; }
        #sidebar details > summary::before { content: '▶'; display: inline-block; font-size: 10px; margin-right: 6px; color: #6b778c; }
        #sidebar details[open] > summary::before { transform: rotate(90deg); }
    """
    soup.head.append(style_tag)

    if css_files:
        for css_path in css_files:
            link_css = soup.new_tag('link', attrs={'rel': 'stylesheet', 'href': css_path, 'type': 'text/css'})
            soup.head.append(link_css)

    # 2. Image Downloading
    for img in soup.find_all('img'):
        src = img.get('src')
        if not src: continue
        if src.startswith('/'):
            full_url = base_url.rstrip('/') + src
        else:
            full_url = src

        if '/download/' in src or '/images/icons/' in src:
            filename = unquote(os.path.basename(urlparse(src).path))
            local_path = os.path.join(outdir_attachments, filename)
            if download_file(full_url, local_path, auth_info):
                img['src'] = f"../attachments/{filename}"

    # 3. Link Rewriting & Anchor Repair
    for a in soup.find_all('a'):
        original_href = a.get('href')
        if not original_href: continue

        # --- A: Calculate Anchor Suffix (Do not modify href yet) ---
        calculated_anchor_suffix = ""

        # Try to match text against Storage Format candidates
        if anchor_repair_queue:
            link_text = a.get_text(" ", strip=True)
            # Peek at first candidate (FIFO based on document order)
            if link_text and anchor_repair_queue:
                candidate = anchor_repair_queue[0]
                if candidate['text'] == link_text:
                    # Match found!
                    matched = anchor_repair_queue.pop(0)
                    page_ref = matched['target_title'] if matched['target_title'] else current_page_title
                    calculated_anchor_suffix = f"#{generate_confluence_anchor(page_ref, matched['anchor'])}"

        # --- B: Extract Target ID using ORIGINAL href ---
        target_id = None
        linked_id = a.get('data-linked-resource-id')
        resource_type = a.get('data-linked-resource-type')

        # Priority 1: Data attributes (most reliable if present)
        if linked_id and (not resource_type or resource_type == 'page'):
            target_id = linked_id

        # Priority 2: Try for pageId in query params (typical Viewpage link)
        if not target_id:
            pid_match = re.search(r'pageId=(\d+)', original_href)
            if pid_match:
                target_id = pid_match.group(1)

        # Priority 3: Try for ID in path (Tiny Links or REST-style)
        if not target_id:
            # Look for /pages/ followed specifically by digits
            # Note: We use search to find it anywhere in the path
            path_match = re.search(r'/pages/(\d+)', original_href)
            if path_match:
                target_id = path_match.group(1)

        # --- C: Construct Final URL ---
        # Check if target is in current export list OR exists on disk from previous run
        is_local_page = False
        if target_id:
            if target_id in valid_ids:
                is_local_page = True
            elif os.path.exists(os.path.join(outdir_pages, f"{target_id}.html")):
                is_local_page = True

        if is_local_page:
            # Case: Local Link found
            # 1. Start with the calculated anchor from storage format
            final_anchor = calculated_anchor_suffix

            # 2. Fallback: If no calculated anchor, preserve existing one
            if not final_anchor and '#' in original_href:
                final_anchor = "#" + original_href.split('#')[1]

            a['href'] = f"{target_id}.html{final_anchor}"

        else:
            # Case: External or Server Link
            # Apply calculated anchor to original href if meaningful and missing
            current_href = original_href
            if calculated_anchor_suffix and calculated_anchor_suffix not in current_href:
                current_href += calculated_anchor_suffix

            # Fix relative paths to absolute for server links
            if current_href.startswith('/'):
                a['href'] = base_url.rstrip('/') + current_href
            else:
                a['href'] = current_href

    # 4. Sidebar Injection
    if sidebar_html:
        soup = inject_sidebar(soup, sidebar_html, page_id)

    return str(soup)


# --- API Calls ---
# Updated get_page_full to fetch storage format as well
def get_page_full(pageId, base_url, platform_config, auth_info, context_path_override):
    # CHANGED: Request body.storage, body.export_view, body.view, and body.styled_view
    # This allows the main script to optionally save "debug" views if flags are set.
    # Note: 'styled_view' might not be available on all Confluence versions, but requesting it is usually safe.
    params_export = {
        'expand': 'body.export_view,body.storage,body.view,body.styled_view,version,ancestors,space,metadata.labels'}
    path_params = {'pageId': pageId}
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_get_page', path_params)
    return _execute_get_request(url, auth_info, params=params_export)


# ... (rest of API calls unchanged) ...
def get_child_pages(pageId, base_url, platform_config, auth_info, context_path_override):
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_get_child_pages', {'pageId': pageId})
    # Add extensions.position to expand to get the manual Confluence tree order
    params = {'limit': 200, 'expand': 'ancestors,metadata.labels,extensions.position'}
    response = _execute_get_request(url, auth_info, params=params)
    
    # Ensure the children are sorted by their manual position, or naturally by title ("2." before "10.")
    if response and 'results' in response:
        def sort_key(item):
            pos = item.get('extensions', {}).get('position')
            if pos is not None:
                try:
                    return (0, int(pos))
                except (ValueError, TypeError):
                    pass
            
            # Fallback: Natural String Sort
            title = item.get('title', '')
            natural_key = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', title)]
            return (1, natural_key)
            
        response['results'].sort(key=sort_key)
        
    return response


def get_space_homepage(spaceKey, base_url, platform_config, auth_info, context_path_override):
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_get_space', {'spaceKey': spaceKey})
    space_info = _execute_get_request(url, auth_info, {'expand': 'homepage'})
    if space_info and 'homepage' in space_info:
        return space_info['homepage']
    return None


def get_page_basic(pageId, base_url, platform_config, auth_info, context_path_override):
    path_params = {'pageId': pageId}
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_get_page', path_params)
    return _execute_get_request(url, auth_info)


def get_page_children(pageId, base_url, platform_config, auth_info, context_path_override):
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_cql_search')
    params = {'cql': f'parent={pageId}', 'limit': 200, 'expand': 'ancestors'}
    return _execute_get_request(url, auth_info, params=params)


def get_page_attachments(pageId, base_url, platform_config, auth_info, context_path_override):
    path_params = {'pageId': pageId}
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_get_attachments', path_params)
    params = {'limit': 200}
    return _execute_get_request(url, auth_info, params=params)


def get_pages_from_space(spaceKey, start, limit, base_url, platform_config, auth_info, context_path_override):
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_cql_search')
    params = {'cql': f'space="{spaceKey}"', 'start': start, 'limit': limit, 'expand': 'ancestors'}
    return _execute_get_request(url, auth_info, params=params)


def get_pages_by_label(label, start, limit, base_url, platform_config, auth_info, context_path_override):
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_cql_search')
    params = {'cql': f'label="{label}"', 'start': start, 'limit': limit, 'expand': 'ancestors'}
    return _execute_get_request(url, auth_info, params=params)


def get_all_spaces(base_url, platform_config, auth_info, context_path_override):
    url = _build_api_url(base_url, platform_config, context_path_override, 'url_get_all_spaces')
    params = {'limit': 200}
    return _execute_get_request(url, auth_info, params=params)
