# -*- coding: utf-8 -*-
"""
Page Extractor for Confluence Dump.
Downloads page data and saves it to raw-data/.
"""

from pathlib import Path
from typing import Optional
import sys

from confluence_dump.api.manifest import Manifest
from confluence_dump.utils.file_ops import atomic_write_text, atomic_write_json, atomic_write_binary


class PageExtractor:
    """
    Extracts page data from Confluence and saves it to raw-data/.
    Supports Delta-Sync via Manifest.
    """
    
    def __init__(self, raw_data_dir: Path, api_client, manifest: Manifest):
        """
        Initializes PageExtractor.
        
        Args:
            raw_data_dir: Directory for raw-data
            api_client: ConfluenceClient instance
            manifest: Manifest instance for state tracking
        """
        self.raw_data_dir = raw_data_dir
        self.api = api_client
        self.manifest = manifest
        
        # Ensure raw-data directory exists
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
    
    def extract_page(self, page_id: str, force: bool = False, verbose: bool = True) -> bool:
        """
        Downloads a page and saves it to raw-data/[page_id]/.
        
        Args:
            page_id: Confluence Page ID
            force: Forces download even if version unchanged
            verbose: Outputs status messages
            
        Returns:
            True if downloaded, False if skipped
        """
        try:
            # 1. LIGHTWEIGHT version check (metadata only, no rendering)
            page_basic = self.api.get_page_basic(page_id)
            if not page_basic:
                if verbose:
                    print(f"  ⚠️  Warning: Page {page_id} could not be loaded (possibly deleted or no permission). Skipping.", file=sys.stderr)
                return False
            
            version = page_basic.get('version', {}).get('number', 0)
            title = page_basic.get('title', 'Untitled')
            
            # 2. Delta-Check (BEFORE we render the full page)
            if not force and not self.manifest.needs_update(page_id, version):
                if verbose:
                    print(f"  [SKIP] {page_id} ({title}) - Version {version} already present")
                return False  # Skip - saves expensive get_page_full()
            
            # 3. Only if changed: Fetch FULL page (with rendering)
            if verbose:
                print(f"  ⬇️  [DOWNLOAD] {page_id} ({title}) - Version {version}")
            
            page_full = self.api.get_page_full(page_id)
            if not page_full:
                if verbose:
                    print(f"  ❌ Error: Full page {page_id} could not be loaded.", file=sys.stderr)
                    print(f"     Possible causes: Network error, missing permission, or page was deleted during download.", file=sys.stderr)
                return False
            
            # 4. Create directory structure
            page_dir = self.raw_data_dir / page_id
            page_dir.mkdir(parents=True, exist_ok=True)
            
            # 5. Save raw data
            meta_path = page_dir / 'meta.json'
            content_path = page_dir / 'content.html'
            storage_path = page_dir / 'storage.xml'
            
            atomic_write_json(meta_path, page_full)
            
            # HTML Content (prefer export_view, otherwise view)
            html_content = page_full.get('body', {}).get('export_view', {}).get('value', '')
            if not html_content:
                html_content = page_full.get('body', {}).get('view', {}).get('value', '')
            atomic_write_text(content_path, html_content)
            
            # Storage Format (optional)
            storage_content = page_full.get('body', {}).get('storage', {}).get('value', '')
            if storage_content:
                atomic_write_text(storage_path, storage_content)
            
            # 6. Download attachments
            self._download_attachments(page_id, page_dir, verbose)
            self._download_embedded_rest_images(html_content, page_dir, verbose)
            
            # 7. Update manifest (preserve needs_mhtml flag from analysis phase)
            parent_id = None
            ancestors = page_full.get('ancestors', [])
            if ancestors:
                parent_id = ancestors[-1].get('id')
            
            self.manifest.update_page(
                page_id,
                title,
                version,
                page_full.get('version', {}).get('when', ''),
                parent_id,
                needs_mhtml=False  # Will be set by analysis phase
            )
            
            return True
            
        except Exception as e:
            print(f"  ❌ Error extracting page {page_id}: {e}", file=sys.stderr)
            print(f"     This is an internal error. Please check network connection and authentication.", file=sys.stderr)
            return False
    
    def _download_attachments(self, page_id: str, page_dir: Path, verbose: bool = True) -> None:
        """
        Downloads all attachments of a page.
        
        Args:
            page_id: Confluence Page ID
            page_dir: Page directory in raw-data
            verbose: Outputs status messages
        """
        attachments_dir = page_dir / 'attachments'
        attachments_dir.mkdir(exist_ok=True)
        
        try:
            attachments = self.api.get_page_attachments(page_id)
            if not attachments or 'results' not in attachments:
                return
            
            results = attachments['results']
            if not results:
                return
            
            if verbose:
                print(f"    Loading {len(results)} attachment(s)...")
            
            for att in results:
                download_path = att.get('_links', {}).get('download')
                filename = att.get('title')
                
                if download_path and filename:
                    # Construct full URL
                    if download_path.startswith('/'):
                        full_url = self.api.base_url + download_path
                    else:
                        full_url = download_path
                    
                    local_path = attachments_dir / filename
                    self._download_file(full_url, local_path, verbose)
                    
        except Exception as e:
            print(f"    ⚠️  Warning: Attachments could not be loaded: {e}", file=sys.stderr)
            print(f"       Page will still be saved, but without attachments.", file=sys.stderr)
    
    def _download_file(self, url: str, local_path: Path, verbose: bool = True) -> bool:
        """
        Downloads a file (atomically).
        
        Args:
            url: Download URL
            local_path: Local target path
            verbose: Outputs status messages
            
        Returns:
            True on success, False on error
        """
        try:
            import requests
            
            headers = {}
            auth_obj = None
            if isinstance(self.api.auth_info, dict):
                headers.update(self.api.auth_info)
            else:
                auth_obj = self.api.auth_info
            
            with requests.get(url, headers=headers, auth=auth_obj, stream=True, timeout=30) as r:
                r.raise_for_status()
                content = b''.join(chunk for chunk in r.iter_content(chunk_size=8192))
                atomic_write_binary(local_path, content)
            
            return True
            
        except Exception as e:
            if verbose:
                print(f"    ⚠️  Download error for attachment '{local_path.name}': {e}", file=sys.stderr)
                print(f"       Possible causes: Network error, missing permission, or file was deleted.", file=sys.stderr)
            return False

    def _download_embedded_rest_images(self, html_content: str, page_dir: Path, verbose: bool = True) -> None:
        """
        Downloads images embedded via REST API (like PlantUML) that are not listed as regular attachments.
        
        Args:
            html_content: The HTML content of the page
            page_dir: Page directory in raw-data
            verbose: Outputs status messages
        """
        if not html_content:
            return
            
        import re
        from urllib.parse import urlparse, unquote
        import os
        
        attachments_dir = page_dir / 'attachments'
        
        # Find all embedded REST image sources (e.g. PlantUML) and cross-page attachments
        urls = re.findall(r'src=["\']([^"\']*?(?:/rest/plantuml/|/download/attachments/|/download/thumbnails/)[^"\']*)["\']', html_content)
        
        if urls:
            attachments_dir.mkdir(exist_ok=True)
            # Use set() to remove duplicates (multiple uses of the same image)
            unique_urls = set(urls)
            if verbose:
                print(f"    Loading {len(unique_urls)} embedded image(s) (PlantUML / cross-page attachments)...")
                
            for url in unique_urls:
                # Construct full URL if relative
                if url.startswith('/'):
                    full_url = self.api.base_url.rstrip('/') + url
                else:
                    full_url = url
                    
                # Extract filename to match LinkRewriter (e.g. "3c895135e84e4a8c8a30896a5e997abe")
                parsed_url = urlparse(full_url)
                filename = unquote(os.path.basename(parsed_url.path))
                
                if filename:
                    local_path = attachments_dir / filename
                    if not local_path.exists():
                        self._download_file(full_url, local_path, verbose=False)
