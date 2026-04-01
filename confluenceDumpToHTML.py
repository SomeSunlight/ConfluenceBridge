#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
This script dumps content from a Confluence instance (Cloud or Data Center) to HTML.
Features:
- Recursive Inventory Scan (Correct Sort Order)
- Multithreaded Downloading
- HTML Processing with BeautifulSoup (Images, Links, Sidebar, Resizer)
- Static Sidebar Injection
- CSS Auto-Discovery
- Label-based Tree Pruning
- Automatic Timestamped Subdirectories
- Manual Overrides (HTML & MHTML) with aggressive cleaning (Data Diet)
"""

import argparse
import os
import sys
import json
import shutil
import glob
import time
import re
import email  # Required for MHTML parsing
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from confluence_dump import myModules
from confluence_dump.utils.config_manager import ConfigManager
from confluence_dump.utils.file_ops import atomic_write_text

# --- External Libraries ---
try:
    import pypandoc
except ImportError:
    pypandoc = None

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        return iterable
try:
    from bs4 import BeautifulSoup, Comment, NavigableString, Tag
except ImportError:
    print("Error: beautifulsoup4 not installed", file=sys.stderr)
    sys.exit(1)

# --- Global Config & State ---
platform_config = {}
auth_info = {}
all_pages_metadata = []
seen_metadata_ids = set()
global_sidebar_html = ""


# --- Helper Functions ---

def sanitize_filename(filename):
    """ Sanitizes a string to be safe for directory names. """
    s = re.sub(r'[<>:"/\\|?*]', '_', filename)
    return s.strip().strip('.')


def get_run_title(args, base_url, platform_config, auth_info):
    if args.command == 'all-spaces':
        return "all spaces"
    elif args.command == 'space':
        return f"Space {args.space_key}"
    elif args.command == 'label':
        return f"Export {args.label}"
    elif args.command in ('single', 'tree'):
        page_ids = [pid.strip() for pid in args.pageid.split(',')]
        first_page_id = page_ids[0]
        try:
            from confluence_dump.api.client import ConfluenceClient
            client = ConfluenceClient(base_url, platform_config, auth_info, args.context_path)
            page_data = client.get_page_basic(first_page_id)
            title = page_data['title'] if page_data and 'title' in page_data else f"Page {first_page_id}"
            if len(page_ids) > 1:
                return f"{title} and {len(page_ids)-1} others"
            return title
        except Exception as e:
            print(f"Warning: Could not fetch page title: {e}", file=sys.stderr)
            if len(page_ids) > 1:
                return f"Pages {first_page_id} and others"
            return f"Page {first_page_id}"
    return "Export"


# --- Content Cleaning (The "Data Diet") ---

def extract_html_from_mhtml(file_path):
    """ Extracts the main HTML part and CSS from a MHTML file. """
    try:
        with open(file_path, 'rb') as f:
            message = email.message_from_bytes(f.read())

        html_content = None
        css_content = ""

        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                if content_type == "text/html":
                    charset = part.get_content_charset() or 'utf-8'
                    html_content = part.get_payload(decode=True).decode(charset, errors='replace')
                elif content_type == "text/css":
                    charset = part.get_content_charset() or 'utf-8'
                    css_part = part.get_payload(decode=True).decode(charset, errors='replace')
                    css_content += f"\n<style type='text/css'>\n{css_part}\n</style>\n"
            
            if html_content and css_content:
                if "<body>" in html_content:
                    html_content = html_content.replace("<body>", f"<body>\n{css_content}")
                elif "<body " in html_content:
                    html_content = re.sub(r'(<body[^>]*>)', rf'\1\n{css_content}', html_content, count=1)
                else:
                    html_content += css_content
            return html_content
        else:
            if message.get_content_type() == "text/html":
                charset = message.get_content_charset() or 'utf-8'
                return message.get_payload(decode=True).decode(charset, errors='replace')

    except Exception as e:
        print(f"Error parsing MHTML {file_path}: {e}", file=sys.stderr)
        return None
    return None


def is_hidden(tag):
    """ Helper to detect if a tag is visually hidden via common attributes. Robust version. """
    if not isinstance(tag, Tag): return False

    if not hasattr(tag, 'attrs') or tag.attrs is None:
        return False

    classes = tag.get('class', [])
    if any(c in ['tf-hidden-column', 'hidden', 'hide', 'invisible', 'aui-hide'] for c in classes):
        return True

    style = tag.get('style', '')
    if 'display: none' in style.replace(' ', '').lower():
        return True

    if 'display:none' in style.replace(' ', '').lower():
        return True

    if tag.get('aria-hidden') == 'true':
        return True

    return False


def clean_manual_html(html_content):
    """
    Aggressively cleans manually saved HTML.
    Includes smart table column pruning based on headers/colgroups.
    """
    if not html_content: return ""

    soup = BeautifulSoup(html_content, 'html.parser')

    # 1. Identify Content Area
    content_node = soup.find('div', id='main-content') or \
                   soup.find('div', class_='wiki-content') or \
                   soup.body or \
                   soup

    # 2. Recover CSS rendered as text
    for tag in content_node.find_all(['p', 'div']):
        text = tag.get_text(strip=True)
        if text.startswith('/*') and '{' in text and '}' in text and ('@page' in text or 'size:' in text or 'landscape' in text):
            style_tag = soup.new_tag('style', type='text/css')
            style_tag.string = tag.get_text(separator='\n').replace('\xa0', ' ')
            tag.replace_with(style_tag)

    # 3. Remove Junk Tags (excluding 'style' to preserve CSS)
    for tag in content_node.find_all(['script', 'meta', 'link', 'noscript', 'iframe', 'svg']):
        tag.decompose()

    for comment in content_node.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # 3. Smart Table Pruning
    for table in content_node.find_all('table'):
        indices_to_remove = set()

        colgroup = table.find('colgroup')
        if colgroup:
            cols = colgroup.find_all('col')
            for idx, col in enumerate(cols):
                if is_hidden(col):
                    indices_to_remove.add(idx)

        thead = table.find('thead')
        if thead:
            header_rows = thead.find_all('tr')
            for tr in header_rows:
                cells = tr.find_all(['th', 'td'])
                for idx, cell in enumerate(cells):
                    if is_hidden(cell):
                        indices_to_remove.add(idx)

        # If we found columns to prune, go through ALL rows (head and body)
        if indices_to_remove:
            for tr in table.find_all('tr'):
                cells = tr.find_all(['td', 'th'])
                for i in sorted(indices_to_remove, reverse=True):
                    if i < len(cells):
                        cells[i].decompose()

        # Also remove the <col> tags themselves if marked
        if colgroup:
            cols = colgroup.find_all('col')
            for i in sorted(indices_to_remove, reverse=True):
                if i < len(cols): cols[i].decompose()

    # 4. General Cleanup (Rows/Divs explicitly hidden)
    # Use list() to avoid modification during iteration issues
    for tag in list(content_node.find_all(['tr', 'div', 'span'])):
        if is_hidden(tag):
            tag.decompose()

    # 5. Clean Table Headers (The "Rectangle" Fix)
    for btn in content_node.find_all('button', class_='headerButton'):
        btn.replace_with(btn.get_text(strip=True))

    # 6. Remove Specific Confluence UI Artifacts
    error_texts = ["Ups, es scheint", "Die Tabelle wird gerade geladen", "Table Filter", "Tabelle filtern", "Diese Seite enthält komplexe Makros"]
    for text in error_texts:
        for element in content_node.find_all(string=re.compile(re.escape(text))):
            wrapper = element.find_parent('div', class_=re.compile(r'(error|warning|message|macro|aui-message|panel|confluence-information-macro)', re.IGNORECASE))
            if wrapper:
                wrapper.decompose()
            elif element.parent:
                if element.parent.name in ['p', 'span', 'b', 'strong', 'em', 'i', 'div', 'td', 'th']:
                    element.parent.decompose()
                else:
                    element.extract()

    # Protect expand buttons from being removed by aui-button cleanup
    for expand_btn in content_node.find_all(class_='expand-control'):
        btn = expand_btn.find(class_=re.compile(r'aui-button'))
        if btn:
            btn['class'] = [c for c in btn.get('class', []) if 'aui-button' not in c]

    for tag in content_node.find_all(
            class_=re.compile(r'(aui-icon|icon-macro|refresh-macro|macro-placeholder|aui-button|tf-filter-button|table-filter|copy-heading-link-container|aui-inline-dialog-contents|tableFilterCbStyle)')):
        tag.decompose()

    # 7. Prune Empty Tags
    for _ in range(3):
        for tag in content_node.find_all(['span', 'div', 'p', 'strong', 'em', 'b', 'i']):
            if not tag.get_text(strip=True) and len(tag.find_all()) == 0:
                tag.decompose()

    return content_node.decode_contents()


# --- Processing Helpers ---

def collect_page_metadata(page_full):
    try:
        page_id = page_full.get('id')
        if not page_id or page_id in seen_metadata_ids:
            return
        title = page_full.get('title')
        ancestors = page_full.get('ancestors', [])
        parent_id = ancestors[-1]['id'] if ancestors else None
        all_pages_metadata.append({'id': page_id, 'title': title, 'parent_id': parent_id})
        seen_metadata_ids.add(page_id)
    except Exception as e:
        print(f"Warning: Could not collect metadata for index: {e}", file=sys.stderr)


def save_page_attachments(page_id, attachments, base_url, auth_info):
    if not attachments or 'results' not in attachments: return
    for att in attachments['results']:
        download_path = att.get('_links', {}).get('download')
        filename = att.get('title')
        if download_path and filename:
            if download_path.startswith('/'):
                full_url = base_url.rstrip('/') + download_path
            else:
                full_url = base_url.rstrip('/') + '/' + download_path
            local_path = os.path.join(myModules.outdir_attachments, filename)
            myModules.download_file(full_url, local_path, auth_info)


def convert_rst(page_id, page_body, outdir_pages):
    if pypandoc is None: return
    page_filename_rst = f"{outdir_pages}{page_id}.rst"
    try:
        pypandoc.convert_text(page_body, 'rst', format='html', outputfile=page_filename_rst)
    except Exception as e:
        print(f"  Error converting RST for {page_id}: {e}", file=sys.stderr)


# --- Tree Generation ---

def build_tree_structure(target_ids):
    tree_map = {}
    pages_map = {}
    relevant_pages = [p for p in all_pages_metadata if p['id'] in target_ids]
    for page in relevant_pages:
        pid = page['id']
        parent = page['parent_id']
        pages_map[pid] = page
        if parent not in tree_map: tree_map[parent] = []
        tree_map[parent].append(pid)
    downloaded_ids = set(pages_map.keys())
    root_ids = []
    for page in relevant_pages:
        parent = page['parent_id']
        if parent is None or parent not in downloaded_ids:
            root_ids.append(page['id'])
    return tree_map, pages_map, root_ids


def generate_tree_html(target_ids):
    tree_map, pages_map, root_ids = build_tree_structure(target_ids)

    def build_branch(parent_id):
        if parent_id not in tree_map: return ""
        html = "<ul>\n"
        for child_id in tree_map[parent_id]:
            if child_id not in pages_map: continue
            child = pages_map[child_id]
            title = child['title']
            link = f'<a href="{child_id}.html">{title}</a>'

            if child_id in tree_map:
                sub_tree = build_branch(child_id)
                html += f'<li class="folder"><details><summary>{link}</summary>{sub_tree}</details></li>\n'
            else:
                html += f'<li class="leaf">{link}</li>\n'
        html += "</ul>\n"
        return html

    sidebar = '<div class="sidebar-tree"><ul>\n'
    for rid in root_ids:
        if rid not in pages_map: continue
        page = pages_map[rid]
        title = page['title']
        link = f'<a href="{rid}.html">{title}</a>'
        if rid in tree_map:
            sub_tree = build_branch(rid)
            sidebar += f'<li class="folder"><details open><summary>{link}</summary>{sub_tree}</details></li>\n'
        else:
            sidebar += f'<li class="leaf">{link}</li>\n'
    sidebar += '</ul></div>\n'
    return sidebar


def generate_tree_markdown(target_ids):
    tree_map, pages_map, root_ids = build_tree_structure(target_ids)
    md_lines = []
    pages_dir_abs = os.path.abspath(myModules.outdir_pages)
    pages_uri = Path(pages_dir_abs).as_uri()

    def build_branch_md(parent_id, level):
        if parent_id not in tree_map: return
        indent = "  " * level
        for child_id in tree_map[parent_id]:
            if child_id not in pages_map: continue
            child = pages_map[child_id]
            md_lines.append(f"{indent}- [{child['title']}]({pages_uri}/{child_id}.html)")
            if child_id in tree_map:
                build_branch_md(child_id, level + 1)

    for rid in root_ids:
        if rid not in pages_map: continue
        page = pages_map[rid]
        md_lines.append(f"- [{page['title']}]({pages_uri}/{rid}.html)")
        if rid in tree_map:
            build_branch_md(rid, 1)

    return "\n".join(md_lines)


def save_sidebars(outdir, target_ids):
    global global_sidebar_html
    global_sidebar_html = generate_tree_html(target_ids)
    
    from pathlib import Path
    atomic_write_text(Path(outdir) / 'sidebar.html', global_sidebar_html)

    sidebar_md = generate_tree_markdown(target_ids)
    atomic_write_text(Path(outdir) / 'sidebar.md', sidebar_md)
    atomic_write_text(Path(outdir) / 'sidebar_orig.md', sidebar_md)


# --- Core Logic (With Override Hook) ---

def process_page(page_id, global_args, active_css_files=None, exported_page_ids=None, verbose=True, manifest=None):
    if verbose: print(f"\nProcessing page ID: {page_id}")
    
    # NEW: ETL-Pipeline Integration
    from pathlib import Path
    raw_data_dir = Path(global_args.outdir) / 'raw-data'
    use_etl = hasattr(global_args, 'use_etl') and global_args.use_etl
    
    if use_etl:
        # Phase 1: Extract (Download to raw-data/)
        from confluence_dump.api.client import ConfluenceClient
        from confluence_dump.api.extractor import PageExtractor
        
        if manifest is None:
            print(f"  ERROR: Manifest not provided in ETL mode", file=sys.stderr)
            return
        
        client = ConfluenceClient(
            global_args.base_url,
            platform_config,
            auth_info,
            global_args.context_path
        )
        
        extractor = PageExtractor(raw_data_dir, client, manifest)
        
        # Extract page (saves to raw-data/)
        success = extractor.extract_page(page_id, force=False, verbose=verbose)
        
        # Collect metadata for sidebar generation (always load this, even if download was skipped)
        page_dir = raw_data_dir / page_id
        meta_path = page_dir / 'meta.json'
        if meta_path.exists():
            import json
            try:
                page_meta = json.loads(meta_path.read_text(encoding='utf-8'))
                collect_page_metadata(page_meta)
            except Exception:
                pass
                
        if not success:
            return
        
        # Note: Manifest will be saved after all pages are processed
        return

    # 0. Check for Manual Override
    override_path = None
    full_pages_dir = os.path.join(global_args.outdir, "full_pages")
    if os.path.exists(full_pages_dir):
        cand_mhtml = os.path.join(full_pages_dir, f"{page_id}.mhtml")
        cand_html = os.path.join(full_pages_dir, f"{page_id}.html")
        if os.path.exists(cand_mhtml):
            override_path = cand_mhtml
        elif os.path.exists(cand_html):
            override_path = cand_html

    if override_path:
        if verbose: 
            print(f"\n  ⚠️ [MANUAL OVERRIDE] Using local file from full_pages/: {os.path.basename(override_path)}")
            print(f"     (Remove it from full_pages/ if you want to use the API/Playwright again)")
        
        if use_etl:
            # If using ETL, copy the override into raw-data so the build phase picks it up
            import shutil
            page_dir = raw_data_dir / page_id
            page_dir.mkdir(parents=True, exist_ok=True)
            if override_path.endswith('.mhtml'):
                shutil.copy2(override_path, page_dir / 'content.mhtml')
            else:
                shutil.copy2(override_path, page_dir / 'content.html')
            # Fetch minimal metadata to not break sidebar
            from confluence_dump.api.client import ConfluenceClient
            client = ConfluenceClient(global_args.base_url, platform_config, auth_info, global_args.context_path)
            page_meta = client.get_page_basic(page_id)
            if page_meta:
                collect_page_metadata(page_meta)
                import json
                (page_dir / 'meta.json').write_text(json.dumps(page_meta, ensure_ascii=False), encoding='utf-8')
            return

    page_full = None

    if override_path and not use_etl:
        # CASE A: Manual Override (Legacy Mode)

        try:
            # Metadata Fetch
            page_meta = myModules.get_page_basic(page_id, global_args.base_url, platform_config, auth_info,
                                                 global_args.context_path)

            if not page_meta:
                page_meta = {
                    'id': page_id,
                    'title': f'Override {page_id}',
                    'version': {'by': {'displayName': 'Manual Override'}, 'when': datetime.now().isoformat()}
                }

            raw_manual_html = ""
            if override_path.endswith('.mhtml'):
                raw_manual_html = extract_html_from_mhtml(override_path)
                if not raw_manual_html:
                    print(f"  Error: Could not extract HTML from MHTML {override_path}", file=sys.stderr)
                    return
            else:
                # Read HTML
                with open(override_path, 'r', encoding='utf-8', errors='replace') as f:
                    raw_manual_html = f.read()

            # --- NEW: CLEANING STEP ---
            # Remove hidden elements and junk before processing
            cleaned_manual_html = clean_manual_html(raw_manual_html)

            page_full = page_meta
            # Inject cleaned content
            page_full['body'] = {
                'export_view': {'value': cleaned_manual_html},
                'view': {'value': cleaned_manual_html},
                # Note: Storage format usually not available from override unless fetched separately or mocked
                'storage': {'value': ''}
            }
            if 'version' not in page_full:
                page_full['version'] = {'by': {'displayName': 'Manual Override'}, 'when': datetime.now().isoformat()}

        except Exception as e:
            print(f"  Error processing override for {page_id}: {e}", file=sys.stderr)
            return

    else:
        # CASE B: Standard API Call
        page_full = myModules.get_page_full(page_id, global_args.base_url, platform_config, auth_info,
                                            global_args.context_path)

    if not page_full:
        print(f"  Warning: Could not fetch page {page_id}. Skipping.", file=sys.stderr)
        return
    if verbose: collect_page_metadata(page_full)

    raw_html = page_full.get('body', {}).get('export_view', {}).get('value')
    if not raw_html:
        raw_html = page_full.get('body', {}).get('view', {}).get('value', '')

    # --- Save Storage XML (Source of Truth) ---
    storage_content = page_full.get('body', {}).get('storage', {}).get('value')
    if global_args.debug_storage and storage_content:
        # FIX: Hier Endung .xml anhängen
        storage_filename = os.path.join(myModules.outdir_pages, f"{page_id}.body.storage.xml")
        try:
            with open(storage_filename, 'w', encoding='utf-8') as f:
                f.write(storage_content)
        except Exception as e:
            print(f"  Warning: Could not save storage format for {page_id}: {e}", file=sys.stderr)

    # --- Save Debug Views ---
    if global_args.debug_views:
        # Save raw view (what we normally process)
        view_content = page_full.get('body', {}).get('view', {}).get('value')
        if view_content:
            try:
                with open(os.path.join(myModules.outdir_pages, f"{page_id}.body.view.html"), 'w',
                          encoding='utf-8') as f:
                    f.write(view_content)
            except Exception as e:
                print(f"  Warning: Could not save view format for {page_id}: {e}", file=sys.stderr)

        # Save styled view (Confluence styling included)
        styled_content = page_full.get('body', {}).get('styled_view', {}).get('value')
        if styled_content:
            try:
                with open(os.path.join(myModules.outdir_pages, f"{page_id}.body.styled_view.html"), 'w',
                          encoding='utf-8') as f:
                    f.write(styled_content)
            except Exception as e:
                print(f"  Warning: Could not save styled_view format for {page_id}: {e}", file=sys.stderr)

    # --- Pass storage_content to module (for Anchor repair) ---
    processed_html = myModules.process_page_content(
        raw_html,
        page_full,
        global_args.base_url,
        auth_info,
        active_css_files,
        exported_page_ids,
        global_sidebar_html,
        storage_content=storage_content
    )

    html_filename = os.path.join(myModules.outdir_pages, f"{page_id}.html")
    with open(html_filename, 'w', encoding='utf-8') as f:
        f.write(processed_html)

    page_attachments = myModules.get_page_attachments(page_id, global_args.base_url, platform_config, auth_info,
                                                      global_args.context_path)
    save_page_attachments(page_id, page_attachments, global_args.base_url, auth_info)

    # --- JSON Optional machen ---
    if not global_args.no_metadata_json:
        json_filename = os.path.join(myModules.outdir_pages, f"{page_id}.json")
        page_full['body_processed'] = processed_html
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(page_full, f, indent=4, ensure_ascii=False)

    if global_args.rst:
        convert_rst(page_id, processed_html, myModules.outdir_pages)


# --- Index Generation ---

def build_index_html(output_dir, css_files=None):
    """ Generates an index.html file listing all downloaded pages hierarchically. """
    print("\nGenerating global index.html...")
    tree_map, pages_map, root_ids = build_tree_structure(set(p['id'] for p in all_pages_metadata))

    def build_list_html(parent_id):
        if parent_id not in tree_map: return ""
        html = "<ul>\n"
        for child_id in tree_map[parent_id]:
            if child_id in pages_map:
                child = pages_map[child_id]
                html += f'<li><a href="pages/{child_id}.html">{child["title"]}</a>'
                html += build_list_html(child_id)
                html += '</li>\n'
        html += "</ul>\n"
        return html

    from pathlib import Path
    from confluence_dump.build.index_builder import IndexBuilder
    
    builder = IndexBuilder(Path(output_dir))
    builder.build_index_html(all_pages_metadata, css_files)


# --- Recursive Inventory & Scanning ---

def recursive_scan(client, page_id, exclude_ids, scanned_count, exclude_label=None):
    if page_id in exclude_ids:
        print(f"  [Excluded by ID] Pruning tree at page {page_id}", file=sys.stderr)
        return []

    tree_ids = [page_id]
    scanned_count[0] += 1
    if scanned_count[0] % 10 == 0:
        sys.stderr.write(f"\rScanned {scanned_count[0]} pages...")
        sys.stderr.flush()

    while True:
        children_data = client.get_child_pages(page_id)
        if not children_data or 'results' not in children_data: break
        children = children_data['results']
        if not children: break

        for child in children:
            child_id = child['id']
            if exclude_label:
                labels = [l['name'] for l in child.get('metadata', {}).get('labels', {}).get('results', [])]
                if exclude_label in labels:
                    print(f"  [Excluded by Label '{exclude_label}'] Pruning tree at page {child_id}", file=sys.stderr)
                    continue
            collect_page_metadata(child)
            tree_ids.extend(recursive_scan(client, child_id, exclude_ids, scanned_count, exclude_label))
        break
    return tree_ids


def scan_space_inventory(client, args, exclude_ids):
    print("Phase 1: Recursive Inventory Scan...")
    scanned_count = [0]
    homepage = client.get_space_homepage(args.space_key)
    if not homepage:
        print("Error: Could not find Space Homepage.", file=sys.stderr)
        return [], []
    root_id = homepage['id']
    collect_page_metadata(homepage)
    all_ids_ordered = recursive_scan(client, root_id, exclude_ids, scanned_count)
    print(f"\nInventory complete. Found {len(all_ids_ordered)} pages.")
    return set(all_ids_ordered), all_ids_ordered


def scan_tree_inventory(client, root_id, args, exclude_ids):
    print("Phase 1: Recursive Tree Scan...")
    scanned_count = [0]
    root_page = client.get_page_basic(root_id)
    if root_page: collect_page_metadata(root_page)
    all_ids_ordered = recursive_scan(client, root_id, exclude_ids, scanned_count)
    print(f"\nInventory complete. Found {len(all_ids_ordered)} pages.")
    return set(all_ids_ordered), all_ids_ordered


def scan_label_forest_inventory(client, args, exclude_ids):
    print(f"Phase 1: Label Forest Scan (Roots: '{args.label}')...")
    scanned_count = [0]
    root_pages = []
    start = 0
    while True:
        res = client.get_pages_by_label(args.label, start, 200)
        if not res or not res.get('results'): break
        for p in res['results']:
            if p['id'] in exclude_ids: continue
            root_pages.append(p)
        start += 200

    full_forest_ids = []
    exclude_label = getattr(args, 'exclude_label', None)
    for root in root_pages:
        collect_page_metadata(root)
        branch_ids = recursive_scan(client, root['id'], exclude_ids, scanned_count, exclude_label)
        full_forest_ids.extend(branch_ids)
    unique_ordered = list(dict.fromkeys(full_forest_ids))
    print(f"\nInventory complete. Found {len(unique_ordered)} unique pages.")
    return set(unique_ordered), unique_ordered


def run_analysis_phase(args, manifest, verbose: bool = True):
    """
    Runs Analysis phase (offline detection of complex macros).
    Reads from raw-data/ and updates manifest with needs_mhtml flags.
    
    Args:
        args: Command-line arguments
        manifest: Manifest instance
        verbose: If True, print progress information
        
    Returns:
        Statistics dictionary from analysis
    """
    from pathlib import Path
    from confluence_dump.analysis.mhtml_detector import MHTMLDetector
    
    raw_data_dir = Path(args.outdir) / 'raw-data'
    mhtml_jira = getattr(args, 'mhtml_jira', False)
    
    detector = MHTMLDetector(raw_data_dir, manifest, mhtml_jira=mhtml_jira)
    stats = detector.analyze_all_pages(verbose=verbose)
    
    return stats


def run_playwright_phase(args, manifest, verbose: bool = True):
    """
    Runs Playwright phase (selective MHTML download).
    Downloads pages marked with needs_mhtml in the manifest.
    
    Args:
        args: Command-line arguments
        manifest: Manifest instance
        verbose: If True, print progress information
        
    Returns:
        Statistics dictionary from playwright phase
    """
    if getattr(args, 'skip_mhtml', False):
        print("  Skipping Playwright phase (--skip-mhtml specified)")
        return {'success': 0, 'failed': 0, 'skipped': 0}
        
    mhtml_pages = manifest.get_mhtml_pages()
    if not mhtml_pages:
        if verbose:
            print("  No pages require MHTML download. Skipping phase.")
        return {'success': 0, 'failed': 0, 'skipped': 0}
        
    from pathlib import Path
    from confluence_dump.playwright.mhtml_downloader import MHTMLDownloader
    
    output_dir = Path(args.outdir)
    downloader = MHTMLDownloader(output_dir, args.base_url)
    stats = downloader.download_pages(mhtml_pages, manifest.data, verbose=verbose)
    
    return stats


def run_build_phase(args, target_ids, active_css_files, manifest=None):
    """
    Runs Transform & Load phases (offline HTML generation).
    Reads from raw-data/ and generates final HTML in pages/.
    
    Args:
        args: Command-line arguments
        target_ids: Set of page IDs to build
        active_css_files: List of CSS file paths
        manifest: Optional Manifest instance (for needs_mhtml lookup)
    """
    from pathlib import Path
    from confluence_dump.transform.html_processor import HTMLProcessor
    from confluence_dump.transform.sidebar_builder import SidebarBuilder
    
    raw_data_dir = Path(args.outdir) / 'raw-data'
    pages_dir = Path(args.outdir) / 'pages'
    attachments_dir = Path(args.outdir) / 'attachments'
    
    # Ensure we have metadata (might be empty in build-only mode if not loaded from manifest)
    if not all_pages_metadata:
        print("  Warning: No page metadata available. Sidebar will be empty.")
    
    # 1. Generate sidebar from metadata
    print("  Building sidebar navigation...")
    sidebar_builder = SidebarBuilder(pages_dir)
    sidebar_html = sidebar_builder.build_sidebar_html(all_pages_metadata, target_ids)
    
    # Save sidebar files
    global global_sidebar_html
    global_sidebar_html = sidebar_html
    
    from confluence_dump.utils.file_ops import atomic_write_text
    atomic_write_text(Path(args.outdir) / 'sidebar.html', sidebar_html)
    
    sidebar_md = sidebar_builder.build_sidebar_markdown(all_pages_metadata, target_ids)
    atomic_write_text(Path(args.outdir) / 'sidebar.md', sidebar_md)
    atomic_write_text(Path(args.outdir) / 'sidebar_orig.md', sidebar_md)
    
    print(f"  ✓ Sidebar generated ({len(all_pages_metadata)} pages)")
    
    # 2. Process all pages (Transform & Load)
    print("  Processing HTML content...")
    from confluence_dump.build.page_builder import PageBuilder
    from confluence_dump.api.manifest import Manifest
    
    # Load manifest for needs_mhtml lookup
    manifest_obj = Manifest(raw_data_dir)
    
    builder = PageBuilder(raw_data_dir, Path(args.outdir), manifest_obj)
    stats = builder.build_all(target_ids, sidebar_html, active_css_files)
    
    print(f"  ✓ Build phase complete: {stats['processed']} pages generated")
    if stats['errors'] > 0:
        print(f"  ⚠ {stats['errors']} pages skipped due to errors")
    if stats['attachments_copied'] > 0:
        print(f"  ✓ {stats['attachments_copied']} attachments copied")


# --- Mode Handlers ---

def run_download_phase(args, all_pages_list, target_ids, active_css_files):
    use_etl = hasattr(args, 'use_etl') and args.use_etl
    
    if use_etl:
        # ETL Pipeline: Extract → Transform → Load
        from pathlib import Path
        from confluence_dump.api.manifest import Manifest
        
        raw_data_dir = Path(args.outdir) / 'raw-data'
        
        # Initialize manifest ONCE before download
        manifest = Manifest(raw_data_dir)
        
        # Update manifest with fresh sort order on every sync
        manifest.set_tree_order(all_pages_list)
        
        # Phase 1: Extract (Download)
        print(f"Phase 1 (Extract): Downloading {len(all_pages_list)} pages with {args.threads} threads...")
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = []
            for pid in all_pages_list:
                # Pass manifest to each thread
                futures.append(executor.submit(process_page, pid, args, active_css_files, target_ids, False, manifest))
            for _ in tqdm(as_completed(futures), total=len(futures), desc="Extracting", unit="page"):
                pass
        
        # Save manifest AFTER all extractions
        manifest.save()
        print(f"✓ Extract phase complete. Manifest saved with {len(manifest.data.get('pages', {}))} pages.")
        
        # Phase 2: Analysis (Detect pages needing MHTML)
        print(f"\nPhase 2 (Analysis): Detecting complex macros...")
        analysis_stats = run_analysis_phase(args, manifest, verbose=True)
        
        # Save manifest with updated needs_mhtml flags
        manifest.save()
        
        # Phase 3: Playwright (MHTML Download)
        print(f"\nPhase 3 (Playwright): Downloading complex pages as MHTML...")
        playwright_stats = run_playwright_phase(args, manifest, verbose=True)
        
        # Phase 4: Transform & Load (Build HTML)
        print(f"\nPhase 4 (Transform & Load): Building HTML files...")
        run_build_phase(args, target_ids, active_css_files, manifest)
        
    else:
        # Legacy mode: Download & process in one step
        print(f"Phase 2: Downloading & Processing {len(all_pages_list)} pages with {args.threads} threads...")
        with ThreadPoolExecutor(max_workers=args.threads) as executor:
            futures = []
            for pid in all_pages_list:
                futures.append(executor.submit(process_page, pid, args, active_css_files, target_ids, verbose=False))
            for _ in tqdm(as_completed(futures), total=len(futures), desc="Downloading", unit="page"):
                pass


def handle_space(args, active_css_files, exclude_ids):
    print(f"Starting 'space' dump for {args.space_key}")
    from confluence_dump.api.client import ConfluenceClient
    client = ConfluenceClient(args.base_url, platform_config, auth_info, args.context_path)
    target_ids, all_pages_list = scan_space_inventory(client, args, exclude_ids)
    save_sidebars(args.outdir, target_ids)
    run_download_phase(args, all_pages_list, target_ids, active_css_files)


def handle_tree(args, active_css_files, exclude_ids):
    print(f"Starting 'tree' dump for {args.pageid}")
    from confluence_dump.api.client import ConfluenceClient
    client = ConfluenceClient(args.base_url, platform_config, auth_info, args.context_path)
    
    all_target_ids = set()
    full_pages_list = []
    
    page_ids = [pid.strip() for pid in args.pageid.split(',')]
    for pid in page_ids:
        target_ids, all_pages_list = scan_tree_inventory(client, pid, args, exclude_ids)
        all_target_ids.update(target_ids)
        # Add only new pages to preserve order and avoid duplicates across trees
        for p in all_pages_list:
            if p not in full_pages_list:
                full_pages_list.append(p)
                
    save_sidebars(args.outdir, all_target_ids)
    run_download_phase(args, full_pages_list, all_target_ids, active_css_files)


def handle_label(args, active_css_files, exclude_ids):
    print(f"Starting 'label' dump for {args.label}")
    from confluence_dump.api.client import ConfluenceClient
    client = ConfluenceClient(args.base_url, platform_config, auth_info, args.context_path)
    target_ids, all_pages_list = scan_label_forest_inventory(client, args, exclude_ids)
    save_sidebars(args.outdir, target_ids)
    run_download_phase(args, all_pages_list, target_ids, active_css_files)


def handle_single(args, active_css_files, exclude_ids):
    print(f"Starting 'single' dump for {args.pageid}")
    
    use_etl = hasattr(args, 'use_etl') and args.use_etl
    page_ids = [pid.strip() for pid in args.pageid.split(',')]
    
    if use_etl:
        # ETL mode: Use manifest
        from pathlib import Path
        from confluence_dump.api.manifest import Manifest
        
        raw_data_dir = Path(args.outdir) / 'raw-data'
        manifest = Manifest(raw_data_dir)
        
        # Update manifest with fresh sort order
        manifest.set_tree_order(page_ids)
        
        for pid in page_ids:
            process_page(pid, args, active_css_files, set(page_ids), verbose=True, manifest=manifest)
        
        # Save manifest
        manifest.save()
        print(f"✓ Extract phase complete. Manifest saved.")
        
        # Analysis phase
        print(f"\nPhase 2 (Analysis): Detecting complex macros...")
        analysis_stats = run_analysis_phase(args, manifest, verbose=True)
        manifest.save()
        
        # Playwright phase
        print(f"\nPhase 3 (Playwright): Downloading complex pages as MHTML...")
        playwright_stats = run_playwright_phase(args, manifest, verbose=True)
        
        # Build phase
        print(f"\nPhase 4 (Transform & Load): Building HTML files...")
        run_build_phase(args, set(page_ids), active_css_files, manifest)
    else:
        # Legacy mode
        for pid in page_ids:
            root = myModules.get_page_full(pid, args.base_url, platform_config, auth_info, args.context_path)
            if root: collect_page_metadata(root)
        save_sidebars(args.outdir, set(page_ids))
        for pid in page_ids:
            process_page(pid, args, active_css_files, set(page_ids), verbose=True)


def handle_all_spaces(args, active_css_files, exclude_ids):
    print("Starting 'all-spaces' dump...")
    from confluence_dump.api.client import ConfluenceClient
    client = ConfluenceClient(args.base_url, platform_config, auth_info, args.context_path)
    spaces = client.get_all_spaces()
    if spaces and 'results' in spaces:
        for s in spaces['results']:
            print(f"\n--- Processing Space: {s['key']} ---")
            global all_pages_metadata, global_sidebar_html, seen_metadata_ids
            all_pages_metadata = []
            seen_metadata_ids = set()
            s_args = argparse.Namespace(**vars(args))
            s_args.space_key = s['key']
            handle_space(s_args, active_css_files, exclude_ids)


# --- Main ---

def main():
    # --- EARLY CHECK: Detect redundant parameters in Delta-Sync mode ---
    # This must happen BEFORE argparse, because argparse will fail with cryptic errors
    # if the user passes commands/parameters that should be loaded from config.json
    
    # Extract --outdir from sys.argv (simple parsing before argparse)
    outdir_value = None
    for i, arg in enumerate(sys.argv):
        if arg in ('-o', '--outdir') and i + 1 < len(sys.argv):
            outdir_value = sys.argv[i + 1]
            break
    
    # Check if workspace exists (has config.json)
    if outdir_value:
        workspace_dir = Path(outdir_value)
        config_path = workspace_dir / 'config.json'
        
        if config_path.exists() and '--init' not in sys.argv:
            # This is a SYNC operation - check for redundant parameters
            # Common mistakes: passing commands (space, tree, single, label) or their parameters
            forbidden_in_sync = ['space', 'tree', 'single', 'label', 'all-spaces', 
                                '--pageid', '-p', '--space-key', '-sp', '--label', '-l']
            
            found_redundant = []
            for arg in sys.argv[1:]:  # Skip script name
                if arg in forbidden_in_sync:
                    found_redundant.append(arg)
            
            if found_redundant:
                print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
                print(f"║ ERROR: Redundant parameters detected in Delta-Sync mode      ║", file=sys.stderr)
                print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
                print(f"\n📋 PROBLEM:", file=sys.stderr)
                print(f"  You specified download parameters, but this workspace already exists.", file=sys.stderr)
                print(f"  Detected redundant parameters: {', '.join(found_redundant)}", file=sys.stderr)
                print(f"\n🔍 CAUSE:", file=sys.stderr)
                print(f"  Delta-Sync automatically loads all parameters from the workspace configuration.", file=sys.stderr)
                print(f"  Manually specifying commands or page IDs would create conflicts.", file=sys.stderr)
                print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
                print(f"  1. For Delta-Sync: Only specify the workspace directory:", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl -o \"{workspace_dir}\"", file=sys.stderr)
                print(f"\n  2. To rebuild with NEW parameters: Use --init flag:", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl --init -o \"{workspace_dir}\" [NEW_PARAMETERS]", file=sys.stderr)
                print(f"\n  3. To create a completely new export: Use a different directory:", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl -o \"./output\" [PARAMETERS]", file=sys.stderr)
                print(f"\n💡 TIP: The saved configuration can be found at:", file=sys.stderr)
                print(f"     {config_path}", file=sys.stderr)
                sys.exit(1)
    
    # --- Continue with normal argparse ---
    parser = argparse.ArgumentParser(
        description="Confluence Dump (Cloud/DC) with HTML Processing",
        formatter_class=argparse.RawTextHelpFormatter
    )

    g = parser.add_argument_group('Global Options')
    g.add_argument('-o', '--outdir', required=True, help="Output directory (Workspace)")
    g.add_argument('--base-url', required=False, help="Confluence Base URL (required for initial download)")
    g.add_argument('--profile', required=False, help="cloud or dc (required for initial download)")
    g.add_argument('--context-path', default=None, help="Context path (DC only)")
    g.add_argument('--css-file', default=None, help="Path to custom CSS file")
    g.add_argument('-t', '--threads', type=int, default=1, help="Number of threads for download (Default: 1)")
    g.add_argument('--exclude-page-id', action='append', help="Exclude a page ID and its children")
    g.add_argument('--no-vpn-reminder', action='store_true', help="Skip the VPN check confirmation for Data Center")
    g.add_argument('--debug-storage', action='store_true', help="Save Confluence Storage Format (.storage.xml)")
    g.add_argument('--debug-views', action='store_true', help="Save original/styled HTML views for debugging")
    g.add_argument('--no-metadata-json', action='store_true', help="Do not save the JSON metadata file")
    g.add_argument('--use-etl', action='store_true', help="Use new ETL pipeline (Extract to raw-data/)")
    g.add_argument('--skip-mhtml', action='store_true', help="Skip Playwright MHTML downloads for complex pages")
    g.add_argument('--mhtml-jira', action='store_true', help="Force Playwright MHTML download for Jira Macros (Opt-in for full Jira titles/status)")
    g.add_argument('--init', action='store_true', help="Reset workspace (delete raw-data/, pages/, attachments/)")
    g.add_argument('--build-only', action='store_true', help="Skip download, only rebuild HTML from raw-data/ (offline mode)")

    subs = parser.add_subparsers(dest='command', required=False, title="Commands")

    p_single = subs.add_parser('single', help="Dump a single page (or comma-separated list of pages)")
    p_single.add_argument('-p', '--pageid', required=True, help="Page ID (or comma-separated list of IDs)")
    p_single.set_defaults(func=handle_single)

    p_tree = subs.add_parser('tree', help="Dump a page tree (Recursive, accepts comma-separated list of root IDs)")
    p_tree.add_argument('-p', '--pageid', required=True, help="Root Page ID (or comma-separated list of IDs)")
    p_tree.set_defaults(func=handle_tree)

    p_space = subs.add_parser('space', help="Dump an entire space (Recursive from Homepage)")
    p_space.add_argument('-sp', '--space-key', required=True, help="Space Key")
    p_space.set_defaults(func=handle_space)

    p_label = subs.add_parser('label', help="Dump pages by label (Forest Mode)")
    p_label.add_argument('-l', '--label', required=True, help="Include Label")
    p_label.add_argument('--exclude-label', help="Exclude subtrees with this label")
    p_label.set_defaults(func=handle_label)

    p_all = subs.add_parser('all-spaces', help="Dump all visible spaces")
    p_all.set_defaults(func=handle_all_spaces)

    args = parser.parse_args()

    # --- NEW: Config-Management Integration (VOR Timestamp-Generierung) ---
    from confluence_dump.utils.config_manager import ConfigManager
    
    # Prüfe ob Workspace existiert (config.json im angegebenen Verzeichnis)
    workspace_dir = Path(args.outdir)
    config_manager = ConfigManager(workspace_dir)
    
    # --- NEW: Build-Only Mode (Offline Rebuild) ---
    if args.build_only:
        if not config_manager.exists():
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: --build-only requires an existing workspace           ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  --build-only can only be executed on an existing workspace.", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  Offline rebuild needs raw-data/ and config.json from a previous download.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  1. Run an initial download first:", file=sys.stderr)
            print(f"     python confluenceDumpToHTML.py --use-etl [OPTIONS] -o \"{workspace_dir}\" [COMMAND]", file=sys.stderr)
            print(f"\n  2. Check the workspace path:", file=sys.stderr)
            print(f"     Current path: {workspace_dir}", file=sys.stderr)
            print(f"     Expected file: {workspace_dir / 'config.json'}", file=sys.stderr)
            sys.exit(1)
        
        # Load Config from Workspace
        print(f"[INFO] Build-Only Mode: Loading configuration from {workspace_dir / 'config.json'}...")
        try:
            args = config_manager.merge_with_cli_args(args)
            print(f"[INFO] Configuration loaded. Starting Offline Rebuild...")
        except Exception as e:
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: Workspace configuration could not be loaded            ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  {e}", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  The config.json file might be corrupted.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  1. Check the file: {workspace_dir / 'config.json'}", file=sys.stderr)
            print(f"  2. Run a new download with --init", file=sys.stderr)
            sys.exit(1)
        
        # Check if raw-data/ exists
        raw_data_dir = workspace_dir / 'raw-data'
        if not raw_data_dir.exists():
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: raw-data/ directory not found                          ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  The workspace does not contain raw data for a rebuild.", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  raw-data/ was either deleted or the initial download was unsuccessful.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  1. Run a new download:", file=sys.stderr)
            print(f"     python confluenceDumpToHTML.py --use-etl -o \"{workspace_dir}\"", file=sys.stderr)
            print(f"\n  2. Check the workspace path:", file=sys.stderr)
            print(f"     Expected directory: {raw_data_dir}", file=sys.stderr)
            sys.exit(1)
        
        # Load Manifest
        from confluence_dump.api.manifest import Manifest
        manifest = Manifest(raw_data_dir)
        
        if not manifest.data.get('pages'):
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: Manifest contains no pages                             ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  The manifest is empty or corrupted.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  Run a new download:", file=sys.stderr)
            print(f"     python confluenceDumpToHTML.py --use-etl -o \"{workspace_dir}\"", file=sys.stderr)
            sys.exit(1)
        
        # Collect metadata from manifest respecting original order
        tree_order = manifest.data.get('tree_order', [])
        
        if tree_order:
            for page_id in tree_order:
                if page_id in manifest.data['pages']:
                    page_data = manifest.data['pages'][page_id]
                    all_pages_metadata.append({
                        'id': page_id,
                        'title': page_data['title'],
                        'parent_id': page_data.get('parent_id')
                    })
                    seen_metadata_ids.add(page_id)
            # Fallback for pages that might not be in tree_order
            for page_id, page_data in manifest.data['pages'].items():
                if page_id not in seen_metadata_ids:
                    all_pages_metadata.append({
                        'id': page_id,
                        'title': page_data['title'],
                        'parent_id': page_data.get('parent_id')
                    })
                    seen_metadata_ids.add(page_id)
        else:
            # Fallback for old manifests without tree_order
            for page_id, page_data in manifest.data['pages'].items():
                all_pages_metadata.append({
                    'id': page_id,
                    'title': page_data['title'],
                    'parent_id': page_data.get('parent_id')
                })
                seen_metadata_ids.add(page_id)
        
        target_ids = set(manifest.data['pages'].keys())
        
        print(f"[INFO] Found: {len(target_ids)} pages in raw-data/")
        
        # Analysis phase
        print(f"\n[INFO] Starting Analysis phase...")
        analysis_stats = run_analysis_phase(args, manifest, verbose=True)
        manifest.save()
        
        # Setup output directories
        myModules.setup_output_directories(args.outdir)
        myModules.set_variables()

        # Gather target attachments from raw_data
        attachments_dir = workspace_dir / 'attachments'
        if attachments_dir.exists():
            print(f"[INFO] Pruning attachments/ directory...")
            
            # Identify valid attachments based on raw_data
            valid_attachments = set()
            for page_dir in raw_data_dir.iterdir():
                if page_dir.is_dir() and (page_dir / 'attachments').exists():
                    for att_file in (page_dir / 'attachments').iterdir():
                        if att_file.is_file():
                            valid_attachments.add(att_file.name)
                            
            # Delete orphaned files without removing the directory
            deleted_count = 0
            error_count = 0
            for root, dirs, files in os.walk(attachments_dir):
                for file in files:
                    if file not in valid_attachments:
                        file_path = Path(root) / file
                        try:
                            file_path.unlink()
                            deleted_count += 1
                        except Exception as e:
                            error_count += 1
                            print(f"  ⚠ Could not delete: {file_path.name}")
                            
            if error_count > 0:
                print(f"[WARNING] {error_count} files could not be deleted. Close any applications accessing them.")
            else:
                print(f"[INFO] {deleted_count} orphaned files successfully deleted.")
        
        # Copy CSS files
        active_css_files = []
        local_styles_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'styles')
        if os.path.exists(local_styles_dir):
            for f in glob.glob(os.path.join(local_styles_dir, "*.css")):
                if "site.css" in f:
                    target = os.path.join(myModules.outdir_styles, os.path.basename(f))
                    shutil.copy(f, target)
                    active_css_files.append(f"../styles/{os.path.basename(f)}")
        
        # Execute Build Phase
        try:
            print(f"\n[INFO] Starting Offline Rebuild...")
            run_build_phase(args, target_ids, active_css_files, manifest)
            
            # Generate Index
            build_index_html(args.outdir, active_css_files)
            
            print(f"\n✅ Offline Rebuild complete. Output in: {args.outdir}")
            print(f"\n💡 TIP: Open the homepage:")
            print(f"  {workspace_dir / 'index.html'}")
            sys.exit(0)
        except Exception as e:
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: Offline Rebuild failed                                 ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  {e}", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  The raw data in raw-data/ might be incomplete or corrupted.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  1. Run a new download:", file=sys.stderr)
            print(f"     python confluenceDumpToHTML.py --use-etl -o \"{workspace_dir}\"", file=sys.stderr)
            print(f"\n  2. Check the raw data:", file=sys.stderr)
            print(f"     {raw_data_dir}", file=sys.stderr)
            print(f"\n🔧 TECHNICAL DETAILS:", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
    
    # Handle --init Flag (Workspace Reset)
    if args.init:
        if config_manager.exists():
            print(f"[INFO] Performing Workspace Reset...")
            print(f"[INFO] Deleting raw-data/, pages/, attachments/...")
            
            # Delete data directories
            dirs_to_delete = ['raw-data', 'pages', 'attachments', 'logs']
            for dir_name in dirs_to_delete:
                dir_path = workspace_dir / dir_name
                if dir_path.exists():
                    shutil.rmtree(dir_path)
                    print(f"  ✓ {dir_name}/ deleted")
            
            print(f"[INFO] Workspace cleaned. config.json and styles/ remain intact.")
            print(f"[INFO] Starting rebuild...")
        else:
            print(f"[WARNING] --init without an existing workspace. Treating as initial download.")
    
    is_sync = config_manager.exists() and not args.init
    
    if is_sync:
        # SYNC-Mode: Load Config from Workspace
        print(f"[INFO] Workspace detected. Loading configuration from {workspace_dir / 'config.json'}...")
        try:
            args = config_manager.merge_with_cli_args(args)
            
            # Hash Validation (Fail Fast on conflicts)
            is_valid, error_msg = config_manager.validate_config_hash(args)
            if not is_valid:
                print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
                print(f"║ ERROR: Configuration conflict detected                        ║", file=sys.stderr)
                print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
                print(f"\n📋 PROBLEM:", file=sys.stderr)
                print(f"  {error_msg}", file=sys.stderr)
                print(f"\n🔍 CAUSE:", file=sys.stderr)
                print(f"  Delta-Sync requires identical parameters as the initial download.", file=sys.stderr)
                print(f"  Divergent parameters would lead to inconsistent data.", file=sys.stderr)
                print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
                print(f"  1. For Delta-Sync: Use only the workspace path without additional parameters:", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl -o \"{workspace_dir}\"", file=sys.stderr)
                print(f"\n  2. For rebuild with new parameters: Use --init flag:", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl --init -o \"{workspace_dir}\" [NEW_PARAMETERS]", file=sys.stderr)
                print(f"\n  3. For completely new export: Create new workspace:", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl -o \"./output\" [PARAMETERS]", file=sys.stderr)
                print(f"\n💡 TIP: The saved configuration can be found at:", file=sys.stderr)
                print(f"     {workspace_dir / 'config.json'}", file=sys.stderr)
                sys.exit(1)
                
            print(f"[INFO] Configuration loaded successfully. Delta-Sync active.")
            
            # Wichtig: Setze die func-Methode basierend auf dem geladenen command
            if not hasattr(args, 'command') or not args.command:
                print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
                print(f"║ INTERNER FEHLER: Korrupte Workspace-Konfiguration            ║", file=sys.stderr)
                print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
                print(f"\n📋 PROBLEM:", file=sys.stderr)
                print(f"  Kein Command in config.json gefunden.", file=sys.stderr)
                print(f"\n🔍 URSACHE:", file=sys.stderr)
                print(f"  Die Workspace-Konfiguration ist beschädigt oder unvollständig.", file=sys.stderr)
                print(f"  Dies ist KEIN Anwenderfehler - die Datei wurde möglicherweise manuell bearbeitet.", file=sys.stderr)
                print(f"\n✅ LÖSUNGSOPTIONEN:", file=sys.stderr)
                print(f"  1. Workspace neu initialisieren (empfohlen):", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl --init -o \"{workspace_dir}\" [PARAMETER]", file=sys.stderr)
                print(f"\n  2. config.json manuell prüfen/reparieren:", file=sys.stderr)
                print(f"     {workspace_dir / 'config.json'}", file=sys.stderr)
                print(f"     (Erforderliches Feld: 'command' mit Wert 'space', 'tree', 'single', 'label' oder 'all-spaces')", file=sys.stderr)
                sys.exit(1)
                
            if args.command == 'space':
                args.func = handle_space
            elif args.command == 'tree':
                args.func = handle_tree
            elif args.command == 'single':
                args.func = handle_single
            elif args.command == 'label':
                args.func = handle_label
            elif args.command == 'all-spaces':
                args.func = handle_all_spaces
            else:
                print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
                print(f"║ INTERNAL ERROR: Unknown command in configuration             ║", file=sys.stderr)
                print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
                print(f"\n📋 PROBLEM:", file=sys.stderr)
                print(f"  Unknown command in config.json: '{args.command}'", file=sys.stderr)
                print(f"\n🔍 CAUSE:", file=sys.stderr)
                print(f"  The workspace configuration contains an invalid command value.", file=sys.stderr)
                print(f"  This is NOT a user error - the file might have been edited manually.", file=sys.stderr)
                print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
                print(f"  1. Re-initialize workspace (recommended):", file=sys.stderr)
                print(f"     python confluenceDumpToHTML.py --use-etl --init -o \"{workspace_dir}\" [PARAMETERS]", file=sys.stderr)
                print(f"\n  2. Manually fix config.json:", file=sys.stderr)
                print(f"     {workspace_dir / 'config.json'}", file=sys.stderr)
                print(f"     (Allowed values: 'space', 'tree', 'single', 'label', 'all-spaces')", file=sys.stderr)
                sys.exit(1)
                
        except Exception as e:
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ INTERNAL ERROR: Workspace configuration could not be loaded  ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  Error loading workspace configuration: {e}", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  The config.json file might be corrupted or unreadable.", file=sys.stderr)
            print(f"  This is NOT a user error.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  1. Re-initialize workspace:", file=sys.stderr)
            print(f"     python confluenceDumpToHTML.py --use-etl --init -o \"{workspace_dir}\" [PARAMETERS]", file=sys.stderr)
            print(f"\n  2. Check file permissions:", file=sys.stderr)
            print(f"     {workspace_dir / 'config.json'}", file=sys.stderr)
            print(f"\n🔧 TECHNICAL DETAILS:", file=sys.stderr)
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # INITIAL-Mode: Validate required parameters
        if not args.base_url or not args.profile:
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: Missing required parameters                            ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  Initial download requires --base-url and --profile", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  For the first download, the Confluence URL and platform type must be provided.", file=sys.stderr)
            print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
            print(f"  Example for Confluence Cloud:", file=sys.stderr)
            print(f"    python confluenceDumpToHTML.py --use-etl --base-url \"https://yoursite.atlassian.net\" \\", file=sys.stderr)
            print(f"           --profile cloud -o \"./output\" space --space-key IT", file=sys.stderr)
            print(f"\n  Example for Confluence Data Center:", file=sys.stderr)
            print(f"    python confluenceDumpToHTML.py --use-etl --base-url \"https://confluence.corp.com\" \\", file=sys.stderr)
            print(f"           --profile dc --context-path \"/wiki\" -o \"./output\" tree --pageid 123456", file=sys.stderr)
            sys.exit(1)
        if not hasattr(args, 'command') or not args.command:
            print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
            print(f"║ ERROR: No command specified                                   ║", file=sys.stderr)
            print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
            print(f"\n📋 PROBLEM:", file=sys.stderr)
            print(f"  No download mode (Command) was specified.", file=sys.stderr)
            print(f"\n🔍 CAUSE:", file=sys.stderr)
            print(f"  The downloader needs a Command to know WHAT to download.", file=sys.stderr)
            print(f"\n✅ AVAILABLE COMMANDS:", file=sys.stderr)
            print(f"  • space       - Entire Space (recursive from Homepage)", file=sys.stderr)
            print(f"  • tree        - Page Tree (recursive from a specific page)", file=sys.stderr)
            print(f"  • single      - Single page (no children)", file=sys.stderr)
            print(f"  • label       - All pages with a specific label", file=sys.stderr)
            print(f"  • all-spaces  - All visible spaces", file=sys.stderr)
            print(f"\n💡 EXAMPLES:", file=sys.stderr)
            print(f"  python confluenceDumpToHTML.py --use-etl [OPTIONS] space --space-key IT", file=sys.stderr)
            print(f"  python confluenceDumpToHTML.py --use-etl [OPTIONS] tree --pageid 123456", file=sys.stderr)
            sys.exit(1)
        print(f"[INFO] New workspace. Starting initial download...")

    global platform_config, auth_info
    active_css_files = []
    exclude_ids = set(args.exclude_page_id) if args.exclude_page_id else set()

    try:
        platform_config = myModules.load_platform_config(args.profile)
        auth_info = myModules.get_auth_config(platform_config)

        # --- Auto-Subfolder Generation (nur bei initialem Download) ---
        if not is_sync:
            timestamp = datetime.now().strftime("%Y-%m-%d %H%M")
            run_title = get_run_title(args, args.base_url, platform_config, auth_info)
            safe_title = sanitize_filename(run_title)

            new_outdir = os.path.join(args.outdir, f"{timestamp} {safe_title}")
            print(f"Creating new output directory: {new_outdir}")
            args.outdir = new_outdir
            
            # Config-Manager auf neues Verzeichnis aktualisieren
            workspace_dir = Path(args.outdir)
            config_manager = ConfigManager(workspace_dir)

        myModules.setup_output_directories(args.outdir)
        myModules.set_variables()

        local_styles_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'styles')
        if os.path.exists(local_styles_dir):
            for f in glob.glob(os.path.join(local_styles_dir, "*.css")):
                if "site.css" in f:
                    target = os.path.join(myModules.outdir_styles, os.path.basename(f))
                    shutil.copy(f, target)
                    active_css_files.append(f"../styles/{os.path.basename(f)}")
        if args.css_file and os.path.exists(args.css_file):
            target = os.path.join(myModules.outdir_styles, os.path.basename(args.css_file))
            shutil.copy(args.css_file, target)
            active_css_files.append(f"../styles/{os.path.basename(args.css_file)}")

    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(0)
    except Exception as e:
        print(f"Init Error: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # --- PRE-FLIGHT CHECK: VPN & AUTHENTICATION ---
        requires_playwright = hasattr(args, 'use_etl') and args.use_etl and not getattr(args, 'skip_mhtml', False) and not getattr(args, 'build_only', False) and not getattr(args, 'init', False)
        requires_vpn = args.profile == 'dc' and not args.no_vpn_reminder

        if requires_vpn or requires_playwright:
            print("\n" + "="*60)
            print(" PRE-FLIGHT CHECK: VPN & CONFLUENCE AUTHENTICATION")
            print("="*60)
            print(" • You can activate your VPN connection right now, before proceeding.")
            if requires_playwright:
                print(" • Playwright needs an active browser session to download complex pages.")
            
            print("\nOptions:")
            print("  [1] Abort (Default)")
            if requires_playwright:
                print("  [2] Proceed: I am connected to VPN, launch browser for authentication")
                print("  [3] Proceed: I am connected to VPN, authentication was already done recently")
            else:
                print("  [2] Proceed: I am connected to VPN (or will connect right now)")
            
            choice = input(f"\nSelect an option [{'1-3' if requires_playwright else '1-2'}] (Default: 1): ").strip()
            
            if choice not in ['2', '3']:
                print("Aborting.")
                sys.exit(0)
                
            if choice == '2' and requires_playwright:
                from confluence_dump.playwright.mhtml_downloader import MHTMLDownloader
                print(f"\n[INFO] Initializing Playwright (Early Authentication)...")
                dl = MHTMLDownloader(Path(args.outdir), args.base_url)
                dl.verify_playwright_auth()
                MHTMLDownloader._global_auth_verified = True
            elif choice == '3' and requires_playwright:
                from confluence_dump.playwright.mhtml_downloader import MHTMLDownloader
                MHTMLDownloader._global_auth_verified = True
                print(f"\n[INFO] Skipping Playwright Authentication prompt as requested.")

        args.func(args, active_css_files, exclude_ids)
        
        # --- NEW: Save Config after successful download (before HTML generation) ---
        if not is_sync:
            print(f"\n[INFO] Saving workspace configuration...")
            config_manager.save_config(args)
            print(f"[INFO] Configuration saved to {workspace_dir / 'config.json'}")
            print(f"\n💡 FUTURE SYNCS (Zero-Config):")
            print(f"  python confluenceDumpToHTML.py --use-etl -o \"{workspace_dir}\"")
            print(f"\n💡 REBUILD WORKSPACE:")
            print(f"  python confluenceDumpToHTML.py --use-etl --init -o \"{workspace_dir}\"")
        
        build_index_html(args.outdir, active_css_files)
        print(f"\n✅ Download complete. Output in: {args.outdir}")
    except Exception as e:
        print(f"\n╔════════════════════════════════════════════════════════════════╗", file=sys.stderr)
        print(f"║ INTERNAL ERROR: Unexpected error during execution            ║", file=sys.stderr)
        print(f"╚════════════════════════════════════════════════════════════════╝", file=sys.stderr)
        print(f"\n📋 PROBLEM:", file=sys.stderr)
        print(f"  {e}", file=sys.stderr)
        print(f"\n🔍 CAUSE:", file=sys.stderr)
        print(f"  An unexpected error occurred. This is NOT a user error.", file=sys.stderr)
        print(f"\n✅ SOLUTION OPTIONS:", file=sys.stderr)
        print(f"  1. Check the technical details below", file=sys.stderr)
        print(f"  2. For network errors: Check VPN connection (Data Center) or internet connection (Cloud)", file=sys.stderr)
        print(f"  3. For authentication errors: Check CONFLUENCE_TOKEN Environment Variable", file=sys.stderr)
        print(f"  4. Create a GitHub Issue with the technical details", file=sys.stderr)
        print(f"\n🔧 TECHNICAL DETAILS:", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
