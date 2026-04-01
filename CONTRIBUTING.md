# Contributing Guide

This document explains the internal architecture of the toolbox for contributors.

## Architectural Overview

The toolbox utilizes an idempotent **ETL (Extract, Transform, Load) Pipeline** architecture. This ensures stability, enables offline rebuilds, and supports features like Delta-Sync and Playwright fallback. 
The components share a common data structure (the Output Directory) which is split into a staging area (`raw-data/`) and a presentation area (`pages/`).

### 1\. Data Acquisition & ETL Pipeline (`confluenceDumpToHTML.py`)

The extraction and processing is divided into 5 distinct phases:

1. **Extract Phase (Network I/O):**
   - Connects to Confluence via `ConfluenceClient` and fetches pages (parallelized).
   - Saves raw data (`content.html`, `meta.json`, `attachments/`) exactly as provided by the API into the `raw-data/[page_id]/` staging area.
   - **Delta-Sync:** Compares Confluence server versions against the local `manifest.json`. Only new or changed pages are downloaded. Deleted pages are tracked and pruned.

2. **Analysis Phase (Offline):**
   - Scans the downloaded HTML in `raw-data/` to identify complex client-side macros (like dynamically filtered tables).
   - Flags these pages in `manifest.json` (`needs_mhtml: true`).

3. **Playwright Phase (Selective MHTML Download):**
   - For flagged pages, launches a headless Chromium browser via Playwright.
   - Waits for the page to render (executing heavy JavaScript) and saves an MHTML snapshot to `raw-data/[page_id]/content.mhtml`.
   - *Manual Fallback:* If automated headless rendering is not possible (e.g., due to MFA), users can manually place MHTML files in the `full-pages/` directory.

4. **Transform Phase (Offline Data Processing):**
   - Reads the raw data entirely offline. No network calls are made.
   - The `HTMLProcessor` parses MHTML or standard HTML, strips unwanted Confluence UI artifacts, and extracts embedded MHTML attachments.
   - The `LinkRewriter` localizes links and fixes anchors.
   - The `SidebarBuilder` generates a hierarchical navigation tree based on metadata.

5. **Load Phase (Disk I/O):**
   - The `PageBuilder` injects the sidebar and CSS into the processed HTML.
   - Writes final HTML to the `pages/` directory and copies attachments to the `attachments/` directory.
   - **Transaction Safety:** All write operations use atomic writes (`.tmp` to `rename`). If the script crashes, no corrupted files are left behind.

### 2\. Structural Editing (`create_editor.py` / `patch_sidebar.py`)

- **Zero-Dependency:** The editor is a self-contained HTML file generated via string concatenation (to avoid Python formatting issues with JS code).
    
- **Logic:** The structure is parsed from Markdown into a DOM tree, manipulated via vanilla JS (Drag & Drop), and exported back to Markdown.
    
- **Patching:** The patcher parses the modified Markdown (`sidebar_edit.md`) and re-injects the navigation tree into all static HTML files.
    

### 3\. Document Composition (`htmlToDoc.py`)

- **Separation:** Kept separate to avoid heavy dependencies (`weasyprint`/GTK) for users who only want HTML.
    
- **Assembly:**
    
    1. Reads `sidebar.md` to determine order.
        
    2. Extracts `<main id="content">` from every page (ignoring the sidebar).
        
    3. Rewrites `href="page.html"` to internal anchors `href="#page-anchor"`.
        
    4. Wraps content in `div.chapter` with orientation classes.
        
- **Styling & Orientation:**
    
    - WeasyPrint does not support mixing orientations easily via global CSS.
        
    - **Solution:** We scan the source HTML for `size: landscape`. If found, we wrap the content in a specific div (`.landscape-wrapper`) which maps to a named page `@page landscape` in the CSS.
        
    - **CSS Priority:** The order of inclusion determines the priority (later rules overwrite earlier ones):
        1. `site.css` (Confluence defaults)
        2. `pdf_base.css` (`DEFAULT_PDF_BASE_CSS` - Toolbox base styles)
        3. Custom CSS files (any user-provided `*.css` in `styles/`)
        4. `pdf_settings.css` (`DEFAULT_PDF_SETTINGS` - Page configs & WeasyPrint workarounds, highest priority)
