# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/ "null"), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html "null").

## [3.0.1] - 2026-03-27

Refinements for offline rendering and user experience.

### Added
- **Jira Macro Opt-In:** Added `--mhtml-jira` flag to force Playwright rendering for fully populated Jira inline macros (titles and status).

### Changed
- **Unified Pre-flight Checks:** Combined VPN and Playwright authentication checks into a single interactive prompt, allowing users to safely connect to VPN before browser launch or skip re-authentication.
- **Log Localization:** Translated all `html_processor.py` log messages and warnings to English for consistency.

### Fixed
- **PlantUML Images:** Fixed an issue where dynamically rendered Confluence REST images (like PlantUML) were missing in offline exports. They are now explicitly downloaded and linked locally.
- **Jira Macro Placeholders:** Aggressively cleaned up incomplete API placeholders ("Getting issue details...", "STATUS") from Jira macros when not using the `--mhtml-jira` flag.

## [3.0.0] - 2026-03-24

Major architectural redesign to a resilient ETL (Extract, Transform, Load) Pipeline.

### Added
- **ETL-Pipeline Architecture:** Strict separation of Data Extraction, Analysis, Transformation, and Load phases for maximum stability and offline capabilities.
- **Delta-Sync:** Introduced `manifest.json` as the single source of truth. The script now compares page versions and only downloads changed or new pages, significantly speeding up subsequent syncs.
- **Playwright MHTML Fallback:** Automated headless browser rendering for complex pages (e.g., Table Filters) that fail to render correctly via the standard Confluence REST API.
- **Offline Rebuild:** Added `--build-only` flag to regenerate final HTML files and navigation directly from the local `raw-data/` staging area without any network calls.
- **Self-Contained Workspaces:** Added `config.json` to store all download parameters. Future syncs require only the output directory path (Zero-Config Sync).
- **Workspace Reset:** Added `--init` flag to cleanly reset a workspace (useful for using a workspace as a template) while preserving configuration.
- **Skip MHTML Flag:** Added `--skip-mhtml` flag to bypass the automated Playwright rendering phase.
- **Transaction Safety:** All disk write operations are now atomic, preventing data corruption upon unexpected script termination.

### Changed
- **Staging Area (`raw-data/`):** Raw API responses are now saved untouched before processing.
- **File Structure:** Replaced `manual_overrides/` with `full-pages/` for manual MHTML fallback.

## \[2.6.0\] - 2025-01-26

Added professional PDF publication capabilities.

### Added

- **PDF Generator:** Introduced `htmlToPDF.py`. Converts the dumped HTML structure into a single, hierarchical PDF document.
    
- **PDF Features:**
    
    - **Smart Splitting:** Option `--split-by-root` to generate separate PDFs for each top-level folder (scalable for 4000+ pages).
        
    - **Mixed Orientation:** Supports mixing Portrait and Landscape pages within the same PDF based on source HTML hints.
        
    - **Bookmarks:** Generates PDF Outlines/Bookmarks matching the sidebar structure.
        
    - **Link Rewriting:** Converts HTML links to internal PDF anchors for seamless navigation.
        
- **PDF Configuration:** Auto-generates `styles/pdf_settings.css` for user-definable page layouts (A4/Letter, Margins).
    

## \[2.5.0\] - 2025-11-22

Introduction of the "Architecture Sandbox" for offline restructuring.

### Added

- **Architecture Sandbox:** Introduced `create_editor.py` and `patch_sidebar.py`. Users can now generate a visual Drag & Drop editor (`editor_sidebar.html`) to restructure the exported documentation offline.
    
- **Editor Features:**
    
    - **Zero-Dependency:** The editor is a self-contained HTML file requiring no internet access.
        
    - **Drag & Drop:** Robust reordering of pages and folders.
        
    - **Working Copy:** Supports a `sidebar_edit.md` workflow to keep the original structure safe.
        

### Changed

- **CSS Strategy:** Refined the "Two-Layer" styling approach (Standard + Custom) to be more robust.
    

## \[2.4.1\] - 2025-11-21

UI/UX Improvements and Bug Fixes.

### Added

- **Metadata Injection:** Page Title, Author, and Modification Date are now injected directly into the HTML Body (top of the page) for better readability.
    
- **Automatic Time-stamping:** Output folders are now automatically named with `YYYY-MM-DD HHMM [Title]` to support clean versioned backups.
    
- **Persistent Sidebar:** The sidebar width is now remembered across page loads using `localStorage`.
    
- **Absolute Links in Markdown:** The generated `sidebar.md` uses absolute file URIs to support opening links in external editors like Logseq or WebStorm directly.
    

### Fixed

- **Empty Page Bug:** Fixed an issue where pages with empty bodies (folders) resulted in 0-byte HTML files. Now generates a proper HTML skeleton with title and sidebar.
    
- **Markdown Patching:** Updated `patch_sidebar.py` to handle absolute file URIs correctly.
    
- **UI Layout:** Optimized Sidebar/Content padding and Hamburger button alignment.
    

## \[2.4.0\] - 2025-11-21

Advanced Filtering and Tree Logic Update.

### Added

- **Label Forest Mode:** The `label` command now supports deep recursion ("Forest Export"). It finds all pages with the include-label and treats them as roots for full tree exports.
    
- **Label Pruning:** Added `--exclude-label` to prune subtrees based on a specific label (e.g., 'archived') during recursion.
    

## \[2.3.0\] - 2025-11-21

Enterprise Performance & Usability Release.

### Added

- **Recursive Inventory:** Changed scanning logic to use `/child/page` API endpoints. This ensures the export respects the **manual sort order** of Confluence.
    
- **Multithreading:** Added `-t/--threads` argument to parallelize page downloads (Phase 2), significantly improving performance on large spaces.
    
- **Tree Pruning (ID):** Added `--exclude-page-id` to skip specific branches during recursion.
    
- **JS Resizer:** The sidebar now has a robust JavaScript-based drag-handle for resizing.
    
- **UX Improvements:**
    
    - Fixed Hamburger position (top-left).
        
    - Added "Heartbeat" visualization during inventory scan.
        
    - Added VPN Reminder for Data Center profiles.
        

### Changed

- **Architecture:** Split process into a strict "Inventory Phase" (Serial, Recursive for sorting) and "Download Phase" (Parallel).
    

## \[2.2.0\] - 2025-11-20

Introduction of Static Sidebar Injection.

### Added

- **Static Sidebar Injection:** Automatically generates a hierarchical navigation tree and injects it into every HTML page.
    
- **Inventory Phase:** Scans all pages/metadata _before_ downloading content to allow for accurate progress bars (`tqdm`) and global tree generation.
    
- **Smart Linking:** Improved detection of dead/external links vs. local links based on the inventory.
    
- **CSS Auto-Discovery:** The script automatically detects and applies `site.css` from the local `styles/` directory.
    
- **Multi-CSS Support:** Allows layering multiple CSS files (Standard + Custom).
    
- **`sidebar.html` Export:** Saves the generated sidebar tree as a separate file.
    

### Changed

- **HTML Layout:** Pages are now wrapped in a Flexbox layout container to support the sidebar.
    
- **Logging:** Cleaned up library logging to support progress bars.
    

## \[2.1.0\] - 2025-11-19

Major functionality restore and improvement ("Visual Copy" release).

### Added

- **HTML Processing with BeautifulSoup:** Re-introduced intelligent HTML parsing.
    
    - **Image Downloading:** Automatically detects embedded images/emoticons, downloads them, and rewrites HTML links to local paths (`../attachments/`).
        
    - **Link Sanitizing:** Attempts to rewrite Confluence internal links to relative filenames.
        
    - **Metadata Injection (Head):** Injects Title, Page ID, and Labels into the HTML `<head>`.
        
- **Export View:** Switched API fetch from `storage` format to `export_view` (or `view`) to get rendered HTML (resolves macros like TOC).
    
- **Attachment Downloading:** Downloads _all_ attachments of a page via API list, not just those embedded in the text.
    

### Changed

- **HTML First:** The primary output format is now processed HTML (`export_view`). RST export is optional via `-R`.
    
- **Dependencies:** Added `beautifulsoup4` to requirements.
    
- **CSS handling:** Improved relative pathing for robust offline viewing.
    

## \[2.0.0\] - 2025-11-17

This version introduces a major architectural refactoring to support both Confluence Cloud and Data Center.

### Added

- **Confluence Data Center Support:** The script now supports both Confluence Cloud (`--profile cloud`) and Data Center (`--profile dc`).
    
- **Configuration File (`confluence_products.ini`):** All platform-specific values (API URL templates, auth methods, base paths) are now defined in this external INI file.
    
- **Data Center Authentication:** Added support for Bearer Token (Personal Access Token) authentication.
    
- **New `label` Command:** Added support for dumping all pages with a specific label.
    
- **Troubleshooting Hints:** Added specific error messages for Data Center users when authentication fails (Intranet/VPN warning).
    
- **Documentation:** Added `CONTRIBUTING.md` and `CHANGELOG.md`.
    

### Changed

- **\[BREAKING CHANGE\] CLI Architecture (Sub-Commands):** The script's interface has been completely modernized, replacing the `-m`/`--mode` flag with sub-commands (like `git`).
    
    - **REMOVED:** The `-m`/`--mode` flag.
        
    - **REMOVED:** The `-s`/`--site` argument.
        
    - **ADDED:** Sub-commands: `single`, `tree`, `space`, `all-spaces`, `label`.
        
    - **ADDED (Global):** `--base-url`, `--profile`, `--context-path`.
        
- **Refactored `myModules.py`:** All API functions are now platform-agnostic. Hardcoded URLs removed.
    
- **Internationalization:** All code comments translated to English.
    

_History below this line is from the original author (jgoldin-skillz)._

## \[1.0.2\] - 2022-03-03

- Bugfixes
    

## \[1.0.1\] - 2022-03-03

- Added `confluenceDumpWithPython.py`
    

## \[1.0.0\] - 2022-03-01

- Initial version
