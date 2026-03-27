# -*- coding: utf-8 -*-
"""
Link Rewriting Module for Transform Phase.
Handles link fixing, anchor repair, and image path rewriting.
"""

from bs4 import BeautifulSoup
from typing import Set, Optional, Dict, Any
from pathlib import Path
import re


class LinkRewriter:
    """
    Rewrites links and anchors in HTML content.
    Operates entirely offline - no network calls.
    """
    
    def __init__(self, pages_dir: Path, exported_page_ids: Set[str]):
        """
        Initialize Link Rewriter.
        
        Args:
            pages_dir: Path to output pages/ directory
            exported_page_ids: Set of all page IDs in current export
        """
        self.pages_dir = pages_dir
        self.exported_page_ids = exported_page_ids
    
    def rewrite_links(self, soup: BeautifulSoup, current_page_id: str, 
                     current_page_title: str, anchor_repair_queue: list) -> BeautifulSoup:
        """
        Rewrites all links in the HTML soup.
        
        Args:
            soup: BeautifulSoup object
            current_page_id: ID of the current page
            current_page_title: Title of the current page
            anchor_repair_queue: List of anchor candidates from storage format
            
        Returns:
            Modified BeautifulSoup object
        """
        for a in soup.find_all('a'):
            original_href = a.get('href')
            if not original_href:
                continue
            
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
                        calculated_anchor_suffix = f"#{self._generate_confluence_anchor(page_ref, matched['anchor'])}"
            
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
                path_match = re.search(r'/pages/(\d+)', original_href)
                if path_match:
                    target_id = path_match.group(1)
            
            # --- C: Construct Final URL ---
            # Check if target is in current export list OR exists on disk from previous run
            is_local_page = False
            if target_id:
                if target_id in self.exported_page_ids:
                    is_local_page = True
                elif (self.pages_dir / f"{target_id}.html").exists():
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
                
                # Keep as-is (no base_url rewriting in offline mode)
                a['href'] = current_href
        
        return soup
    
    def rewrite_images(self, soup: BeautifulSoup) -> BeautifulSoup:
        """
        Rewrites image src attributes to point to local attachments.
        
        Args:
            soup: BeautifulSoup object
            
        Returns:
            Modified BeautifulSoup object
        """
        for img in soup.find_all('img'):
            src = img.get('src')
            if not src:
                continue
            
            # Rewrite to local attachment path (including Confluence REST API images like PlantUML)
            if '/download/' in src or '/images/icons/' in src or '/rest/plantuml/' in src:
                from urllib.parse import unquote, urlparse
                import os
                filename = unquote(os.path.basename(urlparse(src).path))
                img['src'] = f"../attachments/{filename}"
        
        return soup
    
    def parse_anchors_from_storage(self, storage_xml: str) -> list:
        """
        Parses Confluence Storage Format to extract anchor links.
        Returns list of dicts with 'text', 'anchor', 'target_title'.
        
        Args:
            storage_xml: Confluence Storage Format XML
            
        Returns:
            List of anchor candidates
        """
        if not storage_xml:
            return []
        
        # Wrap content in a dummy root tag
        wrapped_xml = f"<root>{storage_xml}</root>"
        
        try:
            # Use XML parser if possible to handle namespaces correctly
            soup = BeautifulSoup(wrapped_xml, 'xml')
        except:
            # Fallback
            soup = BeautifulSoup(storage_xml, 'html.parser')
        
        anchor_candidates = []
        
        # Search for link tags (with and without 'ac:' prefix)
        links = soup.find_all(['ac:link', 'AC:LINK', 'link'])
        
        for link in links:
            # Check anchor attribute
            anchor = link.get('ac:anchor') or link.get('AC:ANCHOR') or link.get('anchor')
            
            if anchor:
                # Check if it links to another page
                target_title = None
                ri_page = link.find(['ri:page', 'RI:PAGE', 'page'])
                if ri_page:
                    target_title = ri_page.get('ri:content-title') or ri_page.get('RI:CONTENT-TITLE') or ri_page.get('content-title')
                
                # Extract Link Text
                text = link.get_text(" ", strip=True)
                if text:
                    anchor_candidates.append({
                        'text': text,
                        'anchor': anchor,
                        'target_title': target_title
                    })
        
        return anchor_candidates
    
    def _generate_confluence_anchor(self, page_title: str, anchor_name: str) -> str:
        """
        Simulates Confluence ID generation: PageTitle (no spaces) + '-' + AnchorName
        
        Args:
            page_title: Page title
            anchor_name: Anchor name
            
        Returns:
            Generated anchor ID
        """
        if not page_title:
            return anchor_name  # Fallback: just the anchor if local
        
        # Remove spaces from title
        clean_title = page_title.replace(" ", "")
        return f"{clean_title}-{anchor_name}"
