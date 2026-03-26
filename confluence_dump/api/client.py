# -*- coding: utf-8 -*-
"""
Confluence API Client.
Wrapper for all API calls with authentication.
"""

from typing import Dict, Any, Optional
import sys


class ConfluenceClient:
    """
    Client for Confluence REST API.
    Supports Cloud (Basic Auth) and Data Center (Bearer Token).
    """
    
    def __init__(self, base_url: str, platform_config: Dict[str, str], 
                 auth_info: Any, context_path_override: Optional[str] = None):
        """
        Initializes Confluence Client.
        
        Args:
            base_url: Base URL of Confluence instance
            platform_config: Platform configuration from INI
            auth_info: Auth object (HTTPBasicAuth or Bearer header dict)
            context_path_override: Optional context path for Data Center
        """
        self.base_url = base_url.rstrip('/')
        self.platform_config = platform_config
        self.auth_info = auth_info
        self.context_path_override = context_path_override
        
        # Import myModules for API functions (temporary until fully migrated)
        from confluence_dump import myModules
        self.myModules = myModules
    
    def get_page_basic(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Loads basic metadata of a page (without body rendering).
        Faster than get_page_full() for version checks.
        
        Args:
            page_id: Confluence Page ID
            
        Returns:
            Dictionary with basic metadata or None on error
        """
        return self.myModules.get_page_basic(
            page_id,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_page_full(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Loads complete page data including body and metadata.
        
        Args:
            page_id: Confluence Page ID
            
        Returns:
            Dictionary with page data or None on error
        """
        return self.myModules.get_page_full(
            page_id,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_page_attachments(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Loads attachment list of a page.
        
        Args:
            page_id: Confluence Page ID
            
        Returns:
            Dictionary with attachments or None on error
        """
        return self.myModules.get_page_attachments(
            page_id,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_child_pages(self, page_id: str) -> Optional[Dict[str, Any]]:
        """
        Loads direct child pages of a page.
        
        Args:
            page_id: Confluence Page ID
            
        Returns:
            Dictionary with child pages or None on error
        """
        return self.myModules.get_child_pages(
            page_id,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_space_homepage(self, space_key: str) -> Optional[Dict[str, Any]]:
        """
        Loads homepage of a space.
        
        Args:
            space_key: Confluence Space Key
            
        Returns:
            Dictionary with homepage data or None on error
        """
        return self.myModules.get_space_homepage(
            space_key,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_pages_from_space(self, space_key: str, start: int = 0, 
                            limit: int = 200) -> Optional[Dict[str, Any]]:
        """
        Loads pages from a space (paginated).
        
        Args:
            space_key: Confluence Space Key
            start: Start index for pagination
            limit: Number of pages per request
            
        Returns:
            Dictionary with pages or None on error
        """
        return self.myModules.get_pages_from_space(
            space_key,
            start,
            limit,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_pages_by_label(self, label: str, start: int = 0, 
                          limit: int = 200) -> Optional[Dict[str, Any]]:
        """
        Loads pages with specific label (paginated).
        
        Args:
            label: Label name
            start: Start index for pagination
            limit: Number of pages per request
            
        Returns:
            Dictionary with pages or None on error
        """
        return self.myModules.get_pages_by_label(
            label,
            start,
            limit,
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
    
    def get_all_spaces(self) -> Optional[Dict[str, Any]]:
        """
        Loads all visible spaces.
        
        Returns:
            Dictionary with spaces or None on error
        """
        return self.myModules.get_all_spaces(
            self.base_url,
            self.platform_config,
            self.auth_info,
            self.context_path_override
        )
