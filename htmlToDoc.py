#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
HTML to Document Converter (PDF / Single-HTML / Preview)
--------------------------------------------------------
Part of the confluenceDump toolbox.
Merges dumped HTML pages into a single, hierarchical document.

Features:
- **PDF Output:** High-quality print output with TOC and bookmarks.
- **HTML Output:** Single-file "Master HTML" for easy searching, reading, or LLM ingestion.
- **Preview Output:** Linked HTML for CSS debugging and layout testing.
- **Smart Structure:** Respects 'sidebar.md' hierarchy.
- **Mixed Orientation:** Supports Portrait/Landscape pages.
- **Table/Image Optimization:** Ensures content fits on A4 pages (PDF only).

Requirements:
    pip install tqdm
    pip install weasyprint (Optional, only for PDF)
    (Windows PDF: GTK3 Runtime required)

Usage:
    python3 htmlToDoc.py --site-dir "./output/TIMESTAMP Space X" --html --pdf
"""

import os
import sys
import argparse
import re
import html
import datetime
import io
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup
from tqdm import tqdm

# --- Default CSS Content (Used to generate initial files) ---
DEFAULT_PDF_BASE_CSS = """/* BASE PDF LAYOUT 
   ---------------
   Defines the fundamental look & feel for the PDF export.
   This file is overwritten on every run to ensure updates.
*/

/* --- Global Reset & Print Overrides --- */
/* We must override Confluence's default print styles which force B/W */
@media print {
    body, h1, h2, h3, h4, h5, h6, p, li, span, div, td, th {
        color: #172b4d !important;
        background-color: transparent;
    }

    a, a:visited, a:focus, a:hover, a:active {
        color: #0052cc !important;
        text-decoration: none !important;
    }
}

body { 
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Segoe UI Emoji", "Apple Color Emoji", Roboto, Helvetica, Arial, sans-serif; 
    font-size: 10pt; 
    line-height: 1.5; 
    color: #172b4d; 
}

/* --- Headers --- */
h1, h2, h3, h4, h5, h6 { bookmark-level: none; color: #172b4d; }
h1 { font-size: 16pt; border-bottom: 2px solid #0052cc; margin-top: 0; padding-bottom: 5px; }
h2 { font-size: 15pt; margin-top: 1.5em; border-bottom: 1px solid #eee; }
h3 { font-size: 14pt; margin-top: 1.2em; }
h4, h5 { font-size: 11pt; font-weight: bold; margin-top: 1em; }

/* --- Links --- */
/* High specificity to beat site.css */
body a, body a:visited, body a:active {
    color: #0052cc !important;
    text-decoration: none;
}

/* External Links: Add arrow (usually robust/bold) */
/* We target both http and https to be safe. */
a[href^="http"]::after, a[href^="https"]::after { 
    content: " \\2197"; 
    font-size: 0.8em; 
    display: inline-block;
    padding-left: 2px;
    color: #0052cc !important;
}

/* Internal Links (within PDF): Fine arrow, no frame */
/* We target .chapter to exclude the Table of Contents */
.chapter a[href^="#"]::after {
    content: " \\2197";
    font-size: 0.6em;     /* Finer/Smaller than external */
    font-weight: normal;  /* Lighter weight */
    display: inline-block;
    vertical-align: super; /* Slight lift to differentiate */
    margin-left: 1px;
    color: #0052cc !important;
    text-decoration: none;
    border: none !important; /* Ensure no frame */
    background: none !important;
}

/* --- Images --- */
img { 
    max-width: 100%; 
    max-height: 90vh; /* Verhindert das Abschneiden unten: Skaliert hohe Bilder maximal auf Seitenhöhe */
    object-fit: contain; /* Behält die Proportionen beim Skalieren bei */
    height: auto; 
    display: block; 
    margin: 10px 0; 
    page-break-inside: avoid; /* Zwingt WeasyPrint, das Bild ggf. komplett auf die nächste Seite zu schieben */
}

/* --- SVGs & Draw.io --- */
/* Erlaubt es WeasyPrint, inline SVGs (insb. von Draw.io) korrekt auf die Seite zu skalieren */
svg {
    max-width: 100% !important;
    page-break-inside: avoid;
}
.drawio-macro {
    max-width: 100% !important;
    overflow: visible !important;
    page-break-inside: avoid;
}
.drawio-macro svg {
    min-width: 0 !important;
    min-height: 0 !important;
}

/* --- Tables --- */
table { 
    border-collapse: collapse; 
    width: 100% !important; 
    max-width: 100% !important;
    margin: 1em 0; 
    font-size: 9pt; 
    page-break-inside: auto; 
    table-layout: fixed; 
}

tr { page-break-inside: avoid; page-break-after: auto; }

th, td { 
    border: 1px solid #dfe1e6; 
    padding: 8px; 
    text-align: left; 
    vertical-align: top;
    overflow-wrap: break-word; 
    word-wrap: break-word;
    hyphens: auto;
}

th { background-color: #f4f5f7 !important; font-weight: bold; }

td img { 
    max-width: 100% !important; 
    max-height: 85vh !important; /* Auch in Tabellen: Höhe begrenzen */
    object-fit: contain;
    height: auto !important; 
    display: inline-block; 
    margin: 0;
}

/* --- Metadata Box --- */
.page-metadata { 
    display: block; font-size: 8pt; color: #6b778c !important; border-bottom: 1px solid #eee; 
    padding-bottom: 10px; margin-bottom: 35px; font-style: italic; line-height: 1.4;
}
.page-metadata ul { display: block; list-style: none; padding: 0; margin: 0; }
.page-metadata li { display: block; margin-bottom: 5px; }

/* --- Code Blocks --- */
pre, code { font-family: monospace; background: #f4f5f7 !important; padding: 2px 4px; border-radius: 3px; font-size: 9pt; }
pre { padding: 10px; overflow-x: hidden; white-space: pre-wrap; border: 1px solid #ddd; }

/* --- TOC --- */
.toc { page-break-after: always; }
.toc h1 { border: none; text-align: center; }
.toc ul { list-style: none; padding-left: 0; }
.toc li { margin: 5px 0; border-bottom: 1px dotted #ccc; list-style: none; }
/* Use blue for TOC links to match preview */
.toc a { text-decoration: none; display: flex; justify-content: space-between; color: #0052cc !important; }
.toc a::after { content: target-counter(attr(href), page); color: #172b4d; font-size: 10pt; font-weight: normal; }

/* --- Layout --- */
.chapter { page-break-before: always; margin-bottom: 3em; }
h1, h2, h3, h4 { page-break-after: avoid; }
.pdf-bookmark { display: block; height: 0; overflow: hidden; color: transparent; border: none !important; margin: 0 !important; padding: 0 !important; }

/* --- UI Artifacts (Hidden) --- */
.aui-dialog, .aui-layer, .aui-dialog2, .cp-control-panel, .tf-macro-filter, .tf-overview-macro, .tablesorter-filter-row, .noprint {
    display: none !important;
}

/* --- MIXED ORIENTATION CLASSES --- */
.portrait-wrapper { page: portrait; width: 100%; }
.landscape-wrapper { page: landscape; width: 100%; }
.default-wrapper { page: auto; width: 100%; }

/* ==========================================================================
   CONFLUENCE PDF EXPORT: LANDSCAPE TABLES
   Fix for rigid elements (preformatted text, code blocks, and images) 
   that break the horizontal boundaries of table cells.
   ========================================================================== */

/* 1. Force preformatted text and code blocks to wrap */
.div-landscape table pre, 
.div-landscape table .code,
.div-landscape table .code-block {
    /* Preserve original indentation but allow text to wrap */
    white-space: pre-wrap !important;       
    
    /* Break long continuous strings (e.g., URLs, log paths) to prevent overflow */
    word-wrap: break-word !important;       
    
    /* Reduce font size for print readability and space efficiency */
    font-size: 8pt !important;              
    
    /* Ensure line height remains compact after line breaks */
    line-height: 1.2 !important;            
    
    /* Restrict maximum width to the parent cell */
    max-width: 100% !important;
}

/* 2. Make images responsive within table cells */
.div-landscape table img,
.div-landscape table .confluence-embedded-image {
    /* Prevent the image from exceeding the cell width */
    max-width: 100% !important;             
    
    /* Override Confluence's hardcoded inline width attributes (e.g., width: 500px) */
    width: auto !important;                 
    
    /* Maintain the original aspect ratio when the image scales down */
    height: auto !important;                
    
    /* Include padding and borders in the element's total width/height calculations */
    box-sizing: border-box !important;
}
"""

DEFAULT_PDF_SETTINGS = """/* PDF PAGE CONFIGURATION */

@page {
    size: A4 portrait;
    margin: 10mm;
    @bottom-center { content: "Page " counter(page); font-size: 8pt; }
}

@page landscape {
    size: A4 landscape;
    margin: 10mm;
    @bottom-center { content: "Page " counter(page); font-size: 8pt; }
}

@page portrait {
    size: A4 portrait;
    margin: 10mm;
    @bottom-center { content: "Page " counter(page); font-size: 8pt; }
}

@page chapter { size: A4 portrait; margin: 10mm; }
@page section { size: A4 portrait; margin: 10mm; }
@page body    { size: A4 portrait; margin: 10mm; }

/* --- Parts of confluence pages, which are printed in landscape (important for LLM, to get content without additional cr) --- */
.div-landscape {
    page: landscape;
    page-break-before: always;
    page-break-after: always;
}

/* removes restrictions from scroll-containers */
.div-landscape .table-wrap {
    width: 100% !important;
    overflow: visible !important;
    margin: 0 !important; /* Verhindert seitliche Verschiebungen durch den Wrapper */
}

/* Enforces all tables to adapt strict to width of page, to prevent they get clipped */
.div-landscape table,
.div-landscape .confluenceTable {
    width: 100% !important;
    max-width: 100% !important;
    table-layout: auto !important;
}

/* --- WEASYPRINT WORKAROUNDS --- */
/* Prevent the TOC from dictating the page break in a portrait context */
.toc {
    page-break-after: auto !important;
}

/* Use modern "break" properties for a hard context switch */
.chapter.landscape-wrapper {
    break-before: right !important; /* Often forces a clean new page context in WeasyPrint */
}
"""

# --- Screen Optimization CSS (Injected only for --html) ---
SCREEN_CSS_OVERRIDE = """
/* Optimization for Screen Reading / LLM */
body { 
    max-width: 1200px; 
    margin: 0 auto; 
    padding: 40px; 
    background-color: #fff;
    box-shadow: 0 0 20px rgba(0,0,0,0.05);
}

/* Relax Table Constraints for Screen */
table { 
    width: auto !important; 
    table-layout: auto !important;
}

/* Visual Separation */
.chapter { 
    page-break-before: auto; 
    border-bottom: 1px solid #eee; 
    padding-bottom: 50px; 
    margin-bottom: 50px; 
}

.toc { 
    background: #f9f9f9; 
    padding: 20px; 
    border-radius: 8px; 
    margin-bottom: 50px;
}
"""


# --- Context Manager to Suppress C-Level Stderr ---
class SuppressStderr:
    """ Redirects stderr to devnull to silence GTK/GIO warnings. """

    def __enter__(self):
        sys.stderr.flush()
        self.original_stderr_fd = sys.stderr.fileno()
        self.devnull = os.open(os.devnull, os.O_WRONLY)
        self.saved_stderr_fd = os.dup(self.original_stderr_fd)
        os.dup2(self.devnull, self.original_stderr_fd)

    def __exit__(self, exc_type, exc_val, exc_tb):
        os.dup2(self.saved_stderr_fd, self.original_stderr_fd)
        os.close(self.saved_stderr_fd)
        os.close(self.devnull)


class Node:
    def __init__(self, title, page_id=None, level=0):
        self.title = title
        self.page_id = page_id
        self.level = level
        self.children = []


def parse_markdown_structure(md_path):
    with open(md_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    root = Node("ROOT", level=-1)
    stack = [root]
    link_pattern = re.compile(r'\[(.*?)\]\((.*?)\)')
    for line in lines:
        stripped = line.strip()
        if not stripped or not stripped.startswith('-'): continue
        raw_indent = line[:line.find('-')]
        level = raw_indent.count('\t') + (raw_indent.count(' ') // 2)
        content = stripped[1:].strip()
        match = link_pattern.search(content)
        if match:
            title = match.group(1)
            raw_href = match.group(2)
            try:
                path = unquote(urlparse(raw_href).path)
                filename = os.path.basename(path)
                page_id = os.path.splitext(filename)[0]
            except:
                page_id = None
        else:
            title = content
            page_id = None
        node = Node(title, page_id, level)
        while len(stack) > 1 and stack[-1].level >= level: stack.pop()
        stack[-1].children.append(node)
        stack.append(node)
    return root


def count_nodes(node):
    count = 1
    for child in node.children: count += count_nodes(child)
    return count


def clean_content(soup):
    for tag in soup(['script', 'style', 'noscript', 'iframe']): tag.decompose()
    ui_classes = ['aui-dialog', 'aui-dialog2', 'aui-layer', 'cp-control-panel', 'tf-macro-filter', 'tf-overview-macro',
                  'tablesorter-filter-row', 'noprint', 'copy-heading-link-container']
    for cls in ui_classes:
        for tag in soup.find_all(class_=cls): tag.decompose()
    for tag in soup.find_all(['div', 'span'], attrs={'aria-hidden': 'true'}): tag.decompose()
    for tag in soup.find_all('img', id=re.compile(r'^comments-icon')): tag.decompose()

    # --- SVG / Draw.io responsive fix ---
    # Draw.io macros often use fixed pixel sizes. We must strip them to prevent cropping.
    for svg in soup.find_all('svg'):
        style = svg.get('style', '')
        w, h = None, None
        
        # 1. Find intrinsic dimensions
        if svg.has_attr('viewBox'):
            parts = svg['viewBox'].split()
            if len(parts) == 4:
                w, h = parts[2], parts[3]
        
        if not w or not h:
            m_w = re.search(r'(?:min-)?width:\s*([0-9.]+)px', style)
            m_h = re.search(r'(?:min-)?height:\s*([0-9.]+)px', style)
            if m_w and m_h:
                w, h = m_w.group(1), m_h.group(1)
            elif svg.has_attr('width') and svg.has_attr('height'):
                w_attr = svg['width'].replace('px', '')
                h_attr = svg['height'].replace('px', '')
                if w_attr.replace('.', '').isdigit() and h_attr.replace('.', '').isdigit():
                    w, h = w_attr, h_attr
                    
        # 2. Apply intrinsic dimensions for WeasyPrint and clean fixed CSS
        if w and h:
            if not svg.has_attr('viewBox'):
                svg['viewBox'] = f"0 0 {w} {h}"
            svg['width'] = w
            svg['height'] = h
            
        svg['style'] = re.sub(r'(?:min-)?(?:width|height):\s*[0-9.]+px;?', '', style)
        
        # 3. Clean fixed dimensions from the parent wrapper
        parent = svg.find_parent('div', class_='drawio-macro')
        if parent:
            p_style = parent.get('style', '')
            parent['style'] = re.sub(r'(?:min-)?(?:width|height):\s*[0-9.]+px;?', '', p_style)

        # 4. WeasyPrint Compatibility: Clean modern CSS & unsupported SVG tags
        temp_soup = BeautifulSoup("", "html.parser")
        for element in svg.find_all(True):
            if getattr(element, 'attrs', None) is None:
                continue

            # WeasyPrint does not render HTML inside SVGs. Extract text as fallback.
            if element.name == 'foreignobject':
                x_val = element.get('x')
                y_val = element.get('y')
                
                # Draw.io often hides coordinates in inner div styles (margin-left, padding-top)
                if x_val is None or y_val is None:
                    inner = element.find('div')
                    if inner and inner.has_attr('style'):
                        st = inner['style']
                        ml = re.search(r'margin-left:\s*([0-9.]+)px', st)
                        pt = re.search(r'padding-top:\s*([0-9.]+)px', st)
                        if ml: x_val = ml.group(1)
                        if pt: y_val = pt.group(1)
                        
                x_val = x_val or '0'
                y_val = y_val or '0'

                text_content = element.get_text(separator=' ', strip=True)
                if text_content:
                    text_tag = temp_soup.new_tag('text')
                    text_tag.string = text_content
                    text_tag['x'] = x_val
                    try:
                        # SVG text is positioned by baseline, add offset
                        text_tag['y'] = str(float(y_val) + 10)
                    except:
                        text_tag['y'] = str(y_val)
                    text_tag['font-size'] = '9px'
                    text_tag['font-family'] = 'sans-serif'
                    text_tag['fill'] = '#000'
                    element.insert_after(text_tag)
                element.decompose()
                continue

            if element.has_attr('style'):
                style_str = element['style']
                if 'light-dark' in style_str:
                    style_str = re.sub(r'light-dark\(\s*(rgba?\([^)]+\)|#[a-zA-Z0-9]+|[a-zA-Z]+|var\([^)]+\))\s*,\s*(?:rgba?\([^)]+\)|#[a-zA-Z0-9]+|[a-zA-Z]+|var\([^)]+\))\s*\)', r'\1', style_str)
                if 'var(' in style_str:
                    style_str = re.sub(r'var\([^,]+,\s*([^)]+)\)', r'\1', style_str)
                element['style'] = style_str
            
            # SVG drop-shadow filters often crash WeasyPrint
            if element.has_attr('filter'):
                del element['filter']
            # Non-standard Draw.io attribute
            if element.has_attr('transformorigin'):
                del element['transformorigin']

    return soup


def get_clean_body(html_path, page_id):
    if not os.path.exists(html_path):
        print(f"Warning: Page file missing: {html_path}", file=sys.stderr)
        return (f"<div class='error'>Page file missing: {os.path.basename(html_path)}</div>", "default-wrapper")
    with open(html_path, 'r', encoding='utf-8') as f:
        full_html = f.read()

    is_landscape = False
    if "size: landscape" in full_html or "size:landscape" in full_html:
        is_landscape = True

    soup = BeautifulSoup(full_html, 'html.parser')
    content_node = soup.find('main', id='content')
    if not content_node: content_node = soup.body
    if not content_node: return ("", "default-wrapper")

    clean_content(content_node)

    # --- UPDATED LINK REWRITING ---
    for a in content_node.find_all('a', href=True):
        href = a['href']
        # Check for local file links (ignoring http, mailto, etc.)
        if not href.startswith(('http', 'https', 'ftp', 'mailto')):
            try:
                # Parse URL components
                parsed = urlparse(href)
                path = parsed.path
                fragment = parsed.fragment

                # Detect if it points to a local HTML file (digits + .html)
                match = re.search(r'(\d+)\.html$', path)
                if match:
                    target_id = match.group(1)

                    # LOGIC:
                    # 1. If Anchor exists (#ITOPGlossar-LRS), use it directly.
                    #    (The anchor ID exists globally in the merged doc)
                    # 2. If NO Anchor, jump to the Page Wrapper (#page-1234)

                    if fragment:
                        a['href'] = f"#{fragment}"
                    else:
                        a['href'] = f"#page-{target_id}"
            except Exception:
                # Fallback for weird URLs
                pass

    if is_landscape:
        wrapper_class = "landscape-wrapper"
    else:
        wrapper_class = "default-wrapper"

    return (content_node.decode_contents(), wrapper_class)


def generate_merged_html(root_node, pages_dir, pbar=None):
    full_html_parts = []
    toc_html = ["<div class='toc'><h1>Table of Contents</h1><ul>"]

    def walk(node, level):
        if pbar: pbar.update(1)
        indent_style = f"style='padding-left: {level * 15}px'"
        safe_title = html.escape(node.title)
        bookmark_html = f'<h1 class="pdf-bookmark" style="bookmark-level: {level + 1}; bookmark-label: \'{safe_title}\'">{safe_title}</h1>'

        if node.page_id:
            toc_html.append(f"<li {indent_style}><a href='#page-{node.page_id}'>{node.title}</a></li>")
            html_path = os.path.join(pages_dir, f"{node.page_id}.html")
            content_html, orientation_class = get_clean_body(html_path, node.page_id)
            wrapper = f"""
             <div id="page-{node.page_id}" class="chapter {orientation_class}">
                {bookmark_html}
                {content_html}
             </div>
             """
            full_html_parts.append(wrapper)
        else:
            toc_html.append(f"<li {indent_style}><strong>{node.title}</strong></li>")
            full_html_parts.append(bookmark_html)

        for child in node.children:
            walk(child, level + 1)

    for child in root_node.children:
        walk(child, 0)

    toc_html.append("</ul></div>")
    return "".join(toc_html) + "".join(full_html_parts)


def ensure_css_file(styles_dir, filename, content, force=False):
    if not os.path.exists(styles_dir): os.makedirs(styles_dir, exist_ok=True)
    path = os.path.join(styles_dir, filename)
    if force or not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f: f.write(content)
    return path


def process_tree(root_node, output_base, pages_dir, css_files, do_pdf, do_preview, do_html):
    # 1. Merge HTML
    total_nodes = count_nodes(root_node) - 1
    print(f"  Merging {total_nodes} pages...")
    with tqdm(total=total_nodes, unit="page") as pbar:
        merged_body = generate_merged_html(root_node, pages_dir, pbar)

    # 2. Build CSS Content (for Embedding in Master HTML & PDF)
    # Start empty, then append all files (including base if it's in css_files)
    all_css_embedded = ""
    for css_file in css_files:
        try:
            with open(css_file, 'r', encoding='utf-8') as f:
                all_css_embedded += f"\n/* --- {os.path.basename(css_file)} --- */\n{f.read()}\n"
        except:
            pass

    # 3. Build CSS Links (for Preview HTML)
    base_dir = os.path.dirname(output_base)  # e.g. output/TimeStamp/
    css_links_html = ""

    for css_file in css_files:
        try:
            # Calculate relative path from output file to style file
            rel_path = os.path.relpath(css_file, base_dir).replace("\\", "/")
            css_links_html += f'<link rel="stylesheet" href="{rel_path}">\n'
        except ValueError:
            pass

    # Correct image paths for root-level HTML files
    html_body_root_level = merged_body.replace('../attachments/', 'attachments/')

    # --- OUTPUT 1: Master HTML (Screen Optimized) ---
    if do_html:
        html_out_path = output_base + ".html"
        full_html_doc = f"""<!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>Documentation</title>
        <style>
            {all_css_embedded}
            {SCREEN_CSS_OVERRIDE}
        </style>
        </head><body>{html_body_root_level}</body></html>"""

        with open(html_out_path, 'w', encoding='utf-8') as f:
            f.write(full_html_doc)
        print(f"  [HTML] Saved: {os.path.basename(html_out_path)}")

    # --- OUTPUT 2: PDF Preview (Debug Mode) ---
    if do_preview:
        preview_out_path = output_base + "_preview.html"
        preview_doc = f"""
        <!DOCTYPE html><html><head><meta charset="utf-8"><title>PDF Preview (Debug)</title>
        {css_links_html}
        <style>
            body {{ background: #ccc; }} 
            .chapter {{ background: white; margin: 20px auto; padding: 1.5cm; max-width: 21cm; box-shadow: 0 0 10px rgba(0,0,0,0.5); }}
            .preview-warning {{ background: #fff3cd; color: #856404; padding: 15px; text-align: center; font-family: sans-serif; font-size: 14px; border-bottom: 1px solid #ffeeba; margin-bottom: 20px; }}
        </style>
        </head><body>
        <div class="preview-warning noprint"><strong>Tipp fürs CSS-Debugging:</strong> Aktiviere in den Browser-Entwicklertools (F12) unter <em>Rendering</em> die Option <strong>Emulate CSS media: print</strong>, um die exakten Schriftgrössen und Abstände des PDFs zu sehen!</div>
        {html_body_root_level}
        </body></html>
        """
        with open(preview_out_path, 'w', encoding='utf-8') as f:
            f.write(preview_doc)
        print(f"  [PREVIEW] Saved: {os.path.basename(preview_out_path)}")
        print(f"Please note: You can safely ignore the following possible GLib-GIO-WARNINGS. They are currently unavoidable")

    # --- OUTPUT 3: PDF ---
    if do_pdf:
        try:
            from weasyprint import HTML, CSS
        except ImportError:
            print("  [PDF] Skipping PDF (WeasyPrint not found).")
            return

        pdf_out_path = output_base + ".pdf"
        print("  [PDF] Rendering... (This may take several minutes, where nothing seems to happen. Take a coffee)")

        full_pdf_doc = f"""<!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>Export</title>
        <style>{all_css_embedded}</style>
        </head><body>{merged_body}</body></html>"""

        try:
            with SuppressStderr():
                # Base URL is pages_dir, so "../attachments" works correctly
                HTML(string=full_pdf_doc, base_url=pages_dir).write_pdf(pdf_out_path)
            print(f"  [PDF] Saved: {os.path.basename(pdf_out_path)}. Enjoy the final result!")
        except Exception as e:
            sys.stderr = sys.__stderr__
            print(f"\n  [PDF] ERROR: {e}")


def main():
    parser = argparse.ArgumentParser(description="HTML to Document Converter")
    parser.add_argument('--site-dir', required=True, help="Base directory of the dump")
    parser.add_argument('--out', help="Explicit output filename (without extension)")
    parser.add_argument('--split-by-root', action='store_true', help="Generate one file per top-level folder")

    # Explicit output flags
    parser.add_argument('--html', action='store_true', help="Generate Single-Page Master HTML (Screen)")
    parser.add_argument('--pdf', action='store_true', help="Generate PDF")
    parser.add_argument('--preview', action='store_true', help="Generate PDF Preview HTML (Debug)")

    args = parser.parse_args()

    # Defaults
    do_pdf = args.pdf
    do_html = args.html
    do_preview = args.preview

    if not (do_pdf or do_html or do_preview):
        print("Warning: No output format selected.")
        print("Please use one or more of: --html, --pdf, --preview")
        sys.exit(0)

    pages_dir = os.path.join(args.site_dir, "pages")
    styles_dir = os.path.join(args.site_dir, "styles")

    # Check Inputs
    md_path = os.path.join(args.site_dir, "sidebar.md")
    if os.path.exists(os.path.join(args.site_dir, "sidebar_edit.md")):
        md_path = os.path.join(args.site_dir, "sidebar_edit.md")
    elif not os.path.exists(md_path):
        print("Error: sidebar.md not found.")
        sys.exit(1)

    print(f"Using structure: {os.path.basename(md_path)}")

    # CSS Setup
    # Force update pdf_base.css to apply new styles
    pdf_base_path = ensure_css_file(site_styles_dir := styles_dir, "pdf_base.css", DEFAULT_PDF_BASE_CSS, force=True)
    pdf_settings_path = ensure_css_file(styles_dir, "pdf_settings.css", DEFAULT_PDF_SETTINGS)

    # CSS Collection: [Site, Base, Custom, Settings]
    css_files = []

    # 1. Site CSS (Confluence Dump Defaults) - Load first
    site_css_path = os.path.join(styles_dir, "site.css")
    if os.path.exists(site_css_path):
        css_files.append(site_css_path)

    # 2. PDF Base (Our Overrides) - Load second to win over site.css
    css_files.append(pdf_base_path)

    # 3. Custom CSS (User Manual Overrides)
    if os.path.exists(styles_dir):
        all_css = [f for f in os.listdir(styles_dir) if f.endswith(".css")]
        for f in sorted(all_css):
            if f not in ["site.css", "pdf_base.css", "pdf_settings.css"]:
                css_files.append(os.path.join(styles_dir, f))

    # 4. Settings (Technical Page Setup)
    css_files.append(pdf_settings_path)

    # Process
    root = parse_markdown_structure(md_path)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H%M")

    if args.split_by_root:
        children = [c for c in root.children if c.children or c.page_id]
        print(f"Split Mode: Generating {len(children)} documents...")
        for node in children:
            safe_title = re.sub(r'[<>:"/\\|?*]', '_', node.title).strip()
            out_base = os.path.join(args.site_dir, f"{timestamp} {safe_title}")
            branch_root = Node("VirtualRoot")
            branch_root.children = [node]
            process_tree(branch_root, out_base, pages_dir, css_files, do_pdf, do_preview, do_html)
    else:
        if args.out:
            out_base = os.path.splitext(args.out)[0]
        else:
            main_title = "Full Export"
            valid_children = [c for c in root.children if c.page_id or c.children]
            if len(valid_children) == 1:
                main_title = valid_children[0].title
            elif len(valid_children) > 1:
                main_title = os.path.basename(os.path.normpath(args.site_dir))
                m = re.match(r'\d{4}-\d{2}-\d{2} \d{4} (.*)', main_title)
                if m: main_title = m.group(1)

            safe_title = re.sub(r'[<>:"/\\|?*]', '_', main_title).strip()
            out_base = os.path.join(args.site_dir, f"{timestamp} {safe_title}")

        process_tree(root, out_base, pages_dir, css_files, do_pdf, do_preview, do_html)


if __name__ == '__main__':
    main()
