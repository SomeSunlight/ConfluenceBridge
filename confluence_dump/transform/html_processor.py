# -*- coding: utf-8 -*-
"""
HTML Processing Module for Transform Phase.
Reads from raw-data/ and generates processed HTML (no network calls).
"""

from pathlib import Path
from bs4 import BeautifulSoup, Comment
from datetime import datetime
from typing import Set, Optional, Dict, Any
import json
import email
import re
from confluence_dump.transform.link_rewriter import LinkRewriter


class HTMLProcessor:
    """
    Processes raw HTML from staging area into final presentation format.
    Operates entirely offline - no network calls.
    """
    
    def __init__(self, raw_data_dir: Path, pages_dir: Path, 
                 attachments_dir: Path, sidebar_html: str = ""):
        """
        Initialize HTML Processor.
        
        Args:
            raw_data_dir: Path to raw-data/ directory
            pages_dir: Path to output pages/ directory
            attachments_dir: Path to output attachments/ directory
            sidebar_html: Pre-generated sidebar HTML
        """
        self.raw_data_dir = raw_data_dir
        self.pages_dir = pages_dir
        self.attachments_dir = attachments_dir
        self.sidebar_html = sidebar_html
        self.link_rewriter = None  # Will be initialized in process_page
    
    def process_page(self, page_id: str, exported_page_ids: Set[str], 
                     css_files: Optional[list] = None, force_api: bool = False) -> str:
        """
        Processes a single page from raw-data/ into final HTML.
        
        Args:
            page_id: Confluence Page ID
            exported_page_ids: Set of all page IDs in current export
            css_files: List of CSS file paths to inject
            force_api: If True, ignores MHTML and forces API fallback
            
        Returns:
            Processed HTML as string
        """
        # 1. Load raw data from staging area
        page_dir = self.raw_data_dir / page_id
        meta_path = page_dir / 'meta.json'
        content_path = page_dir / 'content.html'
        
        # MHTML can come from two sources: Manual (full-pages) or automatic (raw-data)
        mhtml_auto_path = page_dir / 'content.mhtml'
        mhtml_manual_path = self.raw_data_dir.parent / 'full-pages' / f"{page_id}.mhtml"
        
        storage_path = page_dir / 'storage.xml'
        
        if not meta_path.exists():
            raise FileNotFoundError(f"Raw data not found for page {page_id}")
            
        page_metadata = json.loads(meta_path.read_text(encoding='utf-8'))
        
        # Prefer MHTML if available and not explicitly ignored
        mhtml_bytes = None
        if not force_api:
            if mhtml_manual_path.exists():
                print(f"    [MHTML] Page {page_id} generated from manual MHTML download")
                mhtml_bytes = mhtml_manual_path.read_bytes()
            elif mhtml_auto_path.exists():
                print(f"    [MHTML] Page {page_id} generated from Playwright MHTML download")
                mhtml_bytes = mhtml_auto_path.read_bytes()
            
        if mhtml_bytes:
            raw_html = self._extract_and_clean_mhtml(mhtml_bytes, page_id)
            
            # Fallback + Error message if MHTML is corrupted
            if not raw_html:
                print(f"    [WARNING] Could not parse MHTML! Falling back to standard HTML.")
                if content_path.exists():
                    raw_html = content_path.read_text(encoding='utf-8')
                else:
                    raise ValueError(f"MHTML is corrupted and no fallback HTML exists for page {page_id}")
                    
        elif content_path.exists():
            raw_html = content_path.read_text(encoding='utf-8')
        else:
            raise FileNotFoundError(f"Neither content.html nor content.mhtml found for page {page_id}")
            
        storage_content = storage_path.read_text(encoding='utf-8') if storage_path.exists() else None
        
        # 2. Process HTML (offline transformation)
        processed_html = self._transform_html(
            raw_html,
            page_metadata,
            page_id,
            exported_page_ids,
            css_files,
            storage_content
        )
        
        return processed_html
    
    def _extract_and_clean_mhtml(self, mhtml_bytes: bytes, page_id: str) -> str:
        """
        Extracts the HTML part from an MHTML file, extracts embedded attachments,
        and cleans out Confluence UI wrappers so it blends seamlessly into our generated HTML layout.
        """
        message = email.message_from_bytes(mhtml_bytes)
        html_content = ""
        css_content = ""
        
        attachments_dir = self.raw_data_dir / page_id / 'attachments'
        attachments_dir.mkdir(parents=True, exist_ok=True)
        
        if message.is_multipart():
            for part in message.walk():
                content_type = part.get_content_type()
                if content_type == "text/html" and not html_content:
                    charset = part.get_content_charset() or 'utf-8'
                    html_content = part.get_payload(decode=True).decode(charset, errors='replace')
                elif content_type == "text/css":
                    charset = part.get_content_charset() or 'utf-8'
                    css_part = part.get_payload(decode=True).decode(charset, errors='replace')
                    css_content += f"\n{css_part}\n"
                elif content_type.startswith("image/") or part.get_filename():
                    # Extract attachments
                    filename = part.get_filename()
                    if not filename:
                        # Try to extract filename from Content-Location
                        location = part.get("Content-Location", "")
                        if location:
                            filename = location.split('/')[-1]
                            # Remove query parameters
                            filename = filename.split('?')[0]
                    if filename:
                        file_path = attachments_dir / filename
                        payload = part.get_payload(decode=True)
                        if payload:
                            try:
                                from confluence_dump.utils.file_ops import atomic_write_binary
                                atomic_write_binary(file_path, payload)
                            except Exception as e:
                                print(f"      [WARNING] Could not save attachment {filename}: {e}")
        else:
            if message.get_content_type() == "text/html":
                charset = message.get_content_charset() or 'utf-8'
                html_content = message.get_payload(decode=True).decode(charset, errors='replace')
                
        if not html_content:
            print("      [ERROR] No text/html part found in MHTML file!")
            return ""
            
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Confluence MHTML often contains the entire UI (Sidebar, Header, etc.)
        # We only want the main content area.
        content_node = soup.find('div', id='main-content') or soup.find('div', class_='wiki-content') or soup.body or soup
        
        # Remove unwanted UI elements that Playwright captured (scripts, global styles)
        # Note: 'style' is removed from this list so we preserve actual CSS blocks
        for tag in content_node.find_all(['script', 'meta', 'link', 'noscript', 'iframe']):
            tag.decompose()
            
        # Clean specific Confluence UI artifacts that shouldn't be in the final export
        for tag in content_node.find_all(class_=re.compile(r'(aui-sidebar|ia-fixed-sidebar|aui-header)')):
            tag.decompose()
            
        # Clean Table Headers (The "Rectangle" Fix)
        for btn in content_node.find_all('button', class_='headerButton'):
            btn.replace_with(btn.get_text(strip=True))

        # Remove Specific Confluence UI Artifacts and Warnings
        error_texts = ["Ups, es scheint", "Die Tabelle wird gerade geladen", "Diese Seite enthält komplexe Makros"]
        for text in error_texts:
            for element in content_node.find_all(string=re.compile(re.escape(text))):
                wrapper = element.find_parent('div', class_=re.compile(r'(error|warning|message|aui-message|panel|confluence-information-macro)', re.IGNORECASE))
                if wrapper:
                    wrapper.decompose()
                elif element.parent:
                    # 'div', 'td', 'th' were removed to prevent accidentally deleting large containers
                    if element.parent.name in ['p', 'span', 'b', 'strong', 'em', 'i']:
                        element.parent.decompose()
                    else:
                        element.extract()

        # Protect expand buttons from being removed by aui-button cleanup
        for expand_btn in content_node.find_all(class_='expand-control'):
            btn = expand_btn.find(class_=re.compile(r'aui-button'))
            if btn:
                btn['class'] = [c for c in btn.get('class', []) if 'aui-button' not in c]

        for tag in content_node.find_all(class_=re.compile(r'(aui-icon|icon-macro|refresh-macro|macro-placeholder|aui-button|tf-filter-button|copy-heading-link-container|aui-inline-dialog-contents|tableFilterCbStyle)')):
            tag.decompose()

        # Hide elements that are visually hidden (fixes table filter config columns)
        def is_hidden(t):
            if not t or not hasattr(t, 'attrs') or t.attrs is None: return False
            classes = t.get('class', [])
            if any(c in ['tf-hidden-column', 'hidden', 'hide', 'invisible', 'aui-hide'] for c in classes): return True
            style = t.get('style', '').replace(' ', '').lower()
            return 'display:none' in style or t.get('aria-hidden') == 'true'

        for table in content_node.find_all('table'):
            indices_to_remove = set()
            colgroup = table.find('colgroup')
            if colgroup:
                cols = colgroup.find_all('col')
                for idx, col in enumerate(cols):
                    if is_hidden(col): indices_to_remove.add(idx)
            thead = table.find('thead')
            if thead:
                for tr in thead.find_all('tr'):
                    cells = tr.find_all(['th', 'td'])
                    for idx, cell in enumerate(cells):
                        if is_hidden(cell): indices_to_remove.add(idx)
            if indices_to_remove:
                for tr in table.find_all('tr'):
                    cells = tr.find_all(['td', 'th'])
                    for i in sorted(indices_to_remove, reverse=True):
                        if i < len(cells): cells[i].decompose()
                if colgroup:
                    cols = colgroup.find_all('col')
                    for i in sorted(indices_to_remove, reverse=True):
                        if i < len(cols): cols[i].decompose()
                        
        for tag in list(content_node.find_all(['tr', 'span'])):
            if is_hidden(tag):
                tag.decompose()
                
        if css_content:
            style_tag = soup.new_tag('style', type='text/css')
            style_tag.string = css_content
            content_node.insert(0, style_tag)
            
        return content_node.decode_contents()

    def _transform_html(self, html_content: str, page_metadata: Dict[str, Any],
                       page_id: str, exported_page_ids: Set[str],
                       css_files: Optional[list], storage_content: Optional[str]) -> str:
        """
        Core HTML transformation logic (extracted from myModules.process_page_content).
        All network-dependent code removed.
        """
        soup = BeautifulSoup(html_content or "", 'html.parser')
        current_page_title = page_metadata.get('title', 'Untitled')
        
        # 0. Initialize Link Rewriter and Anchor Repair
        if not self.link_rewriter:
            self.link_rewriter = LinkRewriter(self.pages_dir, exported_page_ids)
        
        anchor_repair_queue = []
        if storage_content:
            anchor_repair_queue = self.link_rewriter.parse_anchors_from_storage(storage_content)
        
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
        meta_li.append("Last updated by ")
        span_author = soup.new_tag('span', attrs={'class': 'author'})
        span_author.string = author_name
        meta_li.append(span_author)
        meta_li.append(" on ")
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

            details.confluence-expand { margin-bottom: 10px; border: 1px solid #dfe1e6; border-radius: 3px; }
            details.confluence-expand > summary { cursor: pointer; font-weight: 600; padding: 10px; background: #f4f5f7; outline: none; list-style: none; }
            details.confluence-expand > summary::-webkit-details-marker { display: none; }
            details.confluence-expand > summary::before { content: '▶'; display: inline-block; font-size: 12px; margin-right: 8px; color: #6b778c; transition: transform 0.2s; }
            details.confluence-expand[open] > summary::before { transform: rotate(90deg); }
            details.confluence-expand > .expand-content { padding: 10px; border-top: 1px solid #dfe1e6; }
        """
        soup.head.append(style_tag)
        
        if css_files:
            for css_path in css_files:
                link_css = soup.new_tag('link', attrs={'rel': 'stylesheet', 'href': css_path, 'type': 'text/css'})
                soup.head.append(link_css)
        
        # 1.5 Clean up Jira Macro API Placeholders (Confluence REST API renders these incompletely)
        for jira_span in soup.find_all('span', class_='jira-issue'):
            summary = jira_span.find('span', class_='summary')
            if summary and "Getting issue details" in summary.get_text():
                summary.decompose()
                # Clean up dangling hyphen text nodes (e.g. " - ")
                for text_node in jira_span.find_all(string=re.compile(r'^\s*-\s*$')):
                    text_node.extract()
                    
            for placeholder in jira_span.find_all(class_='issue-placeholder'):
                placeholder.decompose()

        # 1.6 Convert Confluence Expand Macros to HTML5 details/summary
        for expand in soup.find_all(class_=re.compile(r'\bexpand-container\b')):
            details = soup.new_tag('details', attrs={'class': 'confluence-expand'})
            
            summary = soup.new_tag('summary')
            
            control_text = expand.find(class_=re.compile(r'\bexpand-control-text\b'))
            if control_text:
                summary.string = control_text.get_text(strip=True)
            else:
                summary.string = "Expand"
                
            details.append(summary)
            
            content = expand.find(class_=re.compile(r'\bexpand-content\b'))
            if content:
                content_div = soup.new_tag('div', attrs={'class': 'expand-content'})
                for child in list(content.contents):
                    content_div.append(child)
                details.append(content_div)
                
            expand.replace_with(details)

        # 1.7 Repair Draw.io Macros in MHTML (Reconstruct missing image tags)
        for drawio_macro in soup.find_all(class_=re.compile(r'\bconf-macro\b'), attrs={'data-macro-name': 'drawio'}):
            # Der Name des Diagramms ist oft in einem unsichtbaren div versteckt
            name_div = drawio_macro.find('div', style=lambda s: s and 'display:none' in s.replace(' ', '').lower())
            if name_div and name_div.string:
                diagram_name = name_div.string.strip()
                if not diagram_name.lower().endswith('.png'):
                    diagram_name += '.png'
                
                # Erstelle ein sauberes img-Tag, das auf das Attachment verweist
                img_tag = soup.new_tag('img', src=f"../attachments/{diagram_name}", attrs={'class': 'drawio-diagram-image', 'style': 'max-width: 100%;'})
                
                # Ersetze den kaputten Makro-Inhalt durch das Bild
                drawio_macro.clear()
                drawio_macro.append(img_tag)

        # 2. Image Rewriting (local paths only - no downloads)
        soup = self.link_rewriter.rewrite_images(soup)
        
        # 3. Link Rewriting & Anchor Repair
        soup = self.link_rewriter.rewrite_links(
            soup, 
            page_id, 
            current_page_title, 
            anchor_repair_queue
        )
        
        # 4. Sidebar Injection
        if self.sidebar_html:
            soup = self._inject_sidebar(soup, page_id)
        
        return str(soup)
    
    def _inject_sidebar(self, soup: BeautifulSoup, current_page_id: str) -> BeautifulSoup:
        """Injects sidebar HTML and wrapper (extracted from myModules)."""
        if not self.sidebar_html:
            return soup
        
        sidebar_soup = BeautifulSoup(self.sidebar_html, 'html.parser')
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
                for child in list(sidebar_soup.body.children):
                    aside.append(child)
            else:
                for child in list(sidebar_soup.children):
                    aside.append(child)
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
    
