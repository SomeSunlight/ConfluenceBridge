# -*- coding: utf-8 -*-
"""
MHTML Detector: Analyzes downloaded HTML to identify pages requiring Playwright fallback.

This module implements the Analysis phase of the ETL pipeline. It reads raw HTML from
the staging area (raw-data/) and detects pages with complex client-side macros that
cannot be fully captured via the REST API.

Detected patterns:
- Table Filter macros (ac:name="table-filter")
- Dynamically filtered tables
- Other complex client-side rendering (extensible)

The detector updates the manifest with 'needs_mhtml' flags, which triggers the
Playwright phase for selective MHTML downloads.
"""

from pathlib import Path
from typing import Set, Dict, Any
from bs4 import BeautifulSoup
import json
import re


class MHTMLDetector:
    """
    Detects pages with complex client-side macros that require Playwright rendering.
    
    This class operates entirely offline - it reads from raw-data/ and updates the manifest.
    No network calls are made during analysis.
    
    Attributes:
        raw_data_dir: Path to raw-data/ staging area
        manifest: Manifest instance for tracking MHTML requirements
    """
    
    def __init__(self, raw_data_dir: Path, manifest, mhtml_jira: bool = False):
        """
        Initialize MHTML detector.
        
        Args:
            raw_data_dir: Path to raw-data/ directory
            manifest: Manifest instance (will be updated with needs_mhtml flags)
            mhtml_jira: If True, flags pages with Jira macros for MHTML download
        """
        self.raw_data_dir = raw_data_dir
        self.manifest = manifest
        self.mhtml_jira = mhtml_jira
    
    def analyze_all_pages(self, verbose: bool = True) -> Dict[str, Any]:
        """
        Analyzes all pages in raw-data/ and updates manifest with MHTML requirements.
        
        Args:
            verbose: If True, print progress information
            
        Returns:
            Statistics dictionary with:
            - total: Total pages analyzed
            - needs_mhtml: Number of pages requiring MHTML
            - patterns: Dictionary of detected pattern counts
        """
        stats = {
            'total': 0,
            'needs_mhtml': 0,
            'patterns': {
                'table_filter': 0,
                'jira_macro': 0,
                'complex_macros': 0,
                'manual_force': 0
            }
        }
        
        if verbose:
            print("\n[Analysis Phase] Detecting pages requiring MHTML download...")
        
        # Iterate through all page directories in raw-data/
        for page_dir in self.raw_data_dir.iterdir():
            if not page_dir.is_dir() or not page_dir.name.isdigit():
                continue
            
            page_id = page_dir.name
            stats['total'] += 1
            
            try:
                needs_mhtml, detected_patterns = self.analyze_page(page_id)
                
                # Check if the user forced the MHTML download in the manifest
                page_data = self.manifest.data['pages'].get(page_id, {})
                if page_data.get('force_mhtml', False):
                    needs_mhtml = True
                    if 'manual_force' not in detected_patterns:
                        detected_patterns.append('manual_force')
                
                # IMPORTANT: Always set the flag (even to False) to overwrite old flags (unless force_mhtml is True)
                self.manifest.set_needs_mhtml(page_id, needs_mhtml)
                
                if needs_mhtml:
                    stats['needs_mhtml'] += 1
                    
                    # Update pattern statistics
                    for pattern in detected_patterns:
                        if pattern in stats['patterns']:
                            stats['patterns'][pattern] += 1
                    
                    if verbose:
                        if 'manual_force' in detected_patterns:
                            print(f"  ⚠️ Page {page_id}: Requires MHTML (Manually forced via force_mhtml in manifest)")
                        elif 'jira_macro' in detected_patterns:
                            print(f"  ⚠️ Page {page_id}: Requires MHTML (Jira Macro and --mhtml-jira flag set)")
                        else:
                            print(f"  ⚠️ Page {page_id}: Requires MHTML (Table Filter with problematic filters)")
                elif detected_patterns:
                    # Log detected patterns that don't require MHTML
                    if verbose:
                        print(f"  ℹ️ Page {page_id}: Complex macros detected (logged only, no MHTML): {', '.join(detected_patterns)}")
                
            except Exception as e:
                if verbose:
                    print(f"  ❌ Error analyzing page {page_id}: {e}")
        
        if verbose:
            print(f"\n[Analysis Complete] {stats['needs_mhtml']}/{stats['total']} pages require MHTML download")
            if stats['patterns']['table_filter'] > 0:
                print(f"  • Table Filter with problematic filters (numberfilter/iconfilter/userfilter/datefilter/hideColumns): {stats['patterns']['table_filter']}")
            if stats['patterns'].get('jira_macro', 0) > 0:
                print(f"  • Jira Macros (--mhtml-jira): {stats['patterns']['jira_macro']}")
            if stats['patterns'].get('manual_force', 0) > 0:
                print(f"  • Manually forced via manifest (force_mhtml): {stats['patterns']['manual_force']}")
            if stats['patterns']['complex_macros'] > 0:
                print(f"  • Other complex macros (logged only, no MHTML): {stats['patterns']['complex_macros']}")
        
        return stats
    
    def analyze_page(self, page_id: str) -> tuple[bool, list[str]]:
        """
        Analyzes a single page for complex macros.
        
        Args:
            page_id: Confluence page ID
            
        Returns:
            Tuple of (needs_mhtml: bool, detected_patterns: list[str])
        """
        page_dir = self.raw_data_dir / page_id
        content_path = page_dir / 'content.html'
        storage_path = page_dir / 'storage.xml'
        
        if not content_path.exists():
            return False, []
        
        detected_patterns = []
        
        # Read HTML content
        html_content = content_path.read_text(encoding='utf-8')
        
        # Read storage format (if available) for more accurate detection
        storage_content = None
        if storage_path.exists():
            storage_content = storage_path.read_text(encoding='utf-8')
        
        # Check for Table Filter macros
        if self._detect_table_filter(html_content, storage_content):
            detected_patterns.append('table_filter')
            
        # Check for Jira macros if opt-in is enabled
        if self.mhtml_jira and self._detect_jira_macro(storage_content):
            detected_patterns.append('jira_macro')
        
        # Check for other complex macros (extensible)
        if self._detect_complex_macros(html_content, storage_content):
            detected_patterns.append('complex_macros')
        
        # We only force MHTML for certain patterns
        needs_mhtml = 'table_filter' in detected_patterns or 'jira_macro' in detected_patterns or 'manual_force' in detected_patterns
        return needs_mhtml, detected_patterns
    
    def _detect_table_filter(self, html_content: str, storage_content: str = None) -> bool:
        """
        Detects Table Filter macros with problematic filter parameters.
        
        Only Table Filter macros with specific filter types (numberfilter, iconfilter, 
        userfilter, datefilter, hideColumns) require MHTML download, as these cause slow JavaScript 
        filtering that leads to backend timeouts.
        
        Args:
            html_content: Raw HTML from export_view
            storage_content: Optional storage format XML
            
        Returns:
            True if Table Filter macro with problematic filters detected
        """
        # Check storage format (most reliable)
        if not storage_content:
            return False
        
        # Check if table-filter macro exists
        if 'ac:name="table-filter"' not in storage_content and 'ac:name="tablefilter"' not in storage_content:
            return False
        
        # Check for problematic filter parameters
        # These filters cause slow client-side JavaScript that leads to backend timeouts.
        # We check if the parameter is present AND has a non-empty value.
        problematic_filters = [
            'numberfilter',
            'iconfilter',
            'userfilter',
            'datefilter',
            'hideColumns'
        ]

        for filter_name in problematic_filters:
            # We only search for content without angle brackets to avoid matching across tag boundaries.
            # Self-closing tags like <ac:parameter ... /> are ignored because the closing tag is missing.
            pattern = re.compile(rf'<ac:parameter[^>]*ac:name="{filter_name}"[^>]*>([^<]*)</ac:parameter>', re.IGNORECASE)
            matches = pattern.finditer(storage_content)
            for match in matches:
                if match.group(1).strip():
                    return True
        
        return False
    
    def _detect_jira_macro(self, storage_content: str = None) -> bool:
        """
        Detects Jira macros.
        """
        if storage_content and 'ac:name="jira"' in storage_content:
            return True
        return False

    def _detect_complex_macros(self, html_content: str, storage_content: str = None) -> bool:
        """
        Detects other complex client-side macros (for logging only).
        
        These macros are logged for information purposes, but do NOT trigger MHTML download.
        Only Table Filter macros with specific filter parameters require MHTML.
        
        Args:
            html_content: Raw HTML from export_view
            storage_content: Optional storage format XML
            
        Returns:
            False (always) - complex macros are logged but don't require MHTML
        """
        # Note: This method is kept for future extensibility and logging purposes.
        # Currently, only Table Filter with specific parameters requires MHTML.
        
        # We still detect these patterns for logging, but return False
        # so they don't trigger MHTML download
        
        detected = False
        
        # Check storage format for known complex macros (for logging)
        if storage_content:
            complex_macro_names = [
                'jira',  # JIRA issue macros with dynamic content
                'chart',  # Dynamic charts
                'drawio',  # Draw.io diagrams (if interactive)
                'iframe',  # Embedded iframes
            ]
            
            for macro_name in complex_macro_names:
                if f'ac:name="{macro_name}"' in storage_content:
                    detected = True
                    break
        
        # Check HTML for dynamic content indicators (for logging)
        if not detected:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Look for JIRA macros with dynamic loading
            if soup.find('div', class_='jira-issue'):
                detected = True
            
            # Look for embedded iframes (might need full rendering)
            if soup.find('iframe'):
                detected = True
        
        # Return False - we log these, but don't require MHTML
        # Only Table Filter with specific parameters requires MHTML
        return False
    
    def get_mhtml_pages(self) -> Set[str]:
        """
        Returns set of page IDs that require MHTML download.
        
        Returns:
            Set of page IDs marked with needs_mhtml=True in manifest
        """
        return self.manifest.get_mhtml_pages()
