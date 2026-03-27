# -*- coding: utf-8 -*-
"""
Manifest management for Delta-Sync and state tracking.
The manifest stores version numbers of all downloaded pages.
"""

from pathlib import Path
from typing import Dict, Optional, Set, Any, List
from datetime import datetime
import json


class Manifest:
    """
    Manages the state of all downloaded pages.
    Enables Delta-Sync and tracking of deleted pages.
    
    Attributes:
        path: Path to manifest.json file
        data: Dictionary with manifest data
    """
    
    def __init__(self, raw_data_dir: Path):
        """
        Initializes Manifest.
        
        Args:
            raw_data_dir: Directory for raw-data (contains manifest.json)
        """
        self.path = raw_data_dir / 'manifest.json'
        self.data = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """
        Loads existing manifest or creates a new one.
        
        Returns:
            Dictionary with manifest structure
        """
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding='utf-8'))
            except (json.JSONDecodeError, OSError) as e:
                print(f"Warning: Could not load manifest ({e}). Creating new manifest.")
        
        return {
            'version': '1.0',
            'last_sync': None,
            'space_key': None,
            'tree_order': [],
            'pages': {},
            'deleted_pages': []
        }
    
    def save(self) -> None:
        """
        Saves manifest atomically.
        Automatically updates last_sync timestamp.
        
        Raises:
            OSError: On filesystem errors
        """
        from confluence_dump.utils.file_ops import atomic_write_json
        self.data['last_sync'] = datetime.now().isoformat()
        atomic_write_json(self.path, self.data)
    
    def set_tree_order(self, ordered_ids: List[str]) -> None:
        """
        Saves the original hierarchical page order from Confluence.
        
        Args:
            ordered_ids: List of Page IDs in correct manual order
        """
        self.data['tree_order'] = ordered_ids
    
    def update_page(self, page_id: str, title: str, version: int, 
                    last_modified: str, parent_id: Optional[str],
                    needs_mhtml: bool = False) -> None:
        """
        Updates or creates page entry.
        
        Args:
            page_id: Confluence Page ID
            title: Page title
            version: Version number
            last_modified: ISO timestamp of last modification
            parent_id: ID of parent page (None for root pages)
            needs_mhtml: Flag for Playwright download
        """
        # Preserve existing needs_mhtml flag if already set by analysis phase
        existing_needs_mhtml = False
        existing_force_mhtml = False
        if page_id in self.data['pages']:
            existing_needs_mhtml = self.data['pages'][page_id].get('needs_mhtml', False)
            existing_force_mhtml = self.data['pages'][page_id].get('force_mhtml', False)
        
        self.data['pages'][page_id] = {
            'title': title,
            'version': version,
            'last_modified': last_modified,
            'parent_id': parent_id,
            'status': 'current',
            'needs_mhtml': needs_mhtml or existing_needs_mhtml or existing_force_mhtml,
            'force_mhtml': existing_force_mhtml
        }
    
    def mark_deleted(self, page_id: str) -> None:
        """
        Marks page as deleted.
        Removes page from pages and adds it to deleted_pages.
        
        Args:
            page_id: Confluence Page ID
        """
        if page_id in self.data['pages']:
            del self.data['pages'][page_id]
        if page_id not in self.data['deleted_pages']:
            self.data['deleted_pages'].append(page_id)
    
    def needs_update(self, page_id: str, current_version: int) -> bool:
        """
        Checks if page needs to be downloaded.
        
        Args:
            page_id: Confluence Page ID
            current_version: Current version number in Confluence
        
        Returns:
            True if download needed, False if page is current
        """
        if page_id not in self.data['pages']:
            return True  # New page
        return self.data['pages'][page_id]['version'] < current_version
    
    def get_mhtml_pages(self) -> Set[str]:
        """
        Returns all pages that need MHTML download.
        
        Returns:
            Set of Page IDs with needs_mhtml flag
        """
        return {pid for pid, data in self.data['pages'].items() 
                if data.get('needs_mhtml', False)}
    
    def set_needs_mhtml(self, page_id: str, needs: bool) -> None:
        """
        Sets MHTML flag for a page.
        Respects force_mhtml flag if set manually by user.
        
        Args:
            page_id: Confluence Page ID
            needs: True if MHTML download is needed
        """
        if page_id in self.data['pages']:
            force = self.data['pages'][page_id].get('force_mhtml', False)
            self.data['pages'][page_id]['needs_mhtml'] = needs or force
    
    def get_all_page_ids(self) -> Set[str]:
        """
        Returns all known Page IDs.
        
        Returns:
            Set of all Page IDs in manifest
        """
        return set(self.data['pages'].keys())
    
    def set_space_key(self, space_key: str) -> None:
        """
        Sets the Space Key in manifest.
        
        Args:
            space_key: Confluence Space Key
        """
        self.data['space_key'] = space_key
