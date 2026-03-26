# -*- coding: utf-8 -*-
"""
Sidebar Builder Module for Transform Phase.
Generates navigation sidebar from page metadata.
"""

from pathlib import Path
from typing import Dict, Set, List, Optional
import os


class SidebarBuilder:
    """
    Builds hierarchical sidebar navigation from page metadata.
    Operates entirely offline - reads from manifest/metadata.
    """
    
    def __init__(self, pages_dir: Path):
        """
        Initialize Sidebar Builder.
        
        Args:
            pages_dir: Path to output pages/ directory
        """
        self.pages_dir = pages_dir
    
    def build_sidebar_html(self, all_pages_metadata: List[Dict], target_ids: Set[str]) -> str:
        """
        Generates sidebar HTML from page metadata.
        
        Args:
            all_pages_metadata: List of page metadata dicts (id, title, parent_id)
            target_ids: Set of page IDs to include in sidebar
            
        Returns:
            Sidebar HTML as string
        """
        tree_map, pages_map, root_ids = self._build_tree_structure(all_pages_metadata, target_ids)
        
        def build_branch(parent_id):
            if parent_id not in tree_map:
                return ""
            html = "<ul>\n"
            for child_id in tree_map[parent_id]:
                if child_id not in pages_map:
                    continue
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
            if rid not in pages_map:
                continue
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
    
    def build_sidebar_markdown(self, all_pages_metadata: List[Dict], target_ids: Set[str]) -> str:
        """
        Generates sidebar Markdown from page metadata.
        
        Args:
            all_pages_metadata: List of page metadata dicts (id, title, parent_id)
            target_ids: Set of page IDs to include in sidebar
            
        Returns:
            Sidebar Markdown as string
        """
        tree_map, pages_map, root_ids = self._build_tree_structure(all_pages_metadata, target_ids)
        md_lines = []
        pages_dir_abs = os.path.abspath(self.pages_dir)
        pages_uri = Path(pages_dir_abs).as_uri()
        
        def build_branch_md(parent_id, level):
            if parent_id not in tree_map:
                return
            indent = "  " * level
            for child_id in tree_map[parent_id]:
                if child_id not in pages_map:
                    continue
                child = pages_map[child_id]
                md_lines.append(f"{indent}- [{child['title']}]({pages_uri}/{child_id}.html)")
                if child_id in tree_map:
                    build_branch_md(child_id, level + 1)
        
        for rid in root_ids:
            if rid not in pages_map:
                continue
            page = pages_map[rid]
            md_lines.append(f"- [{page['title']}]({pages_uri}/{rid}.html)")
            if rid in tree_map:
                build_branch_md(rid, 1)
        
        return "\n".join(md_lines)
    
    def _build_tree_structure(self, all_pages_metadata: List[Dict], target_ids: Set[str]) -> tuple:
        """
        Builds tree structure from page metadata.
        
        Args:
            all_pages_metadata: List of page metadata dicts
            target_ids: Set of page IDs to include
            
        Returns:
            Tuple of (tree_map, pages_map, root_ids)
        """
        tree_map = {}
        pages_map = {}
        relevant_pages = [p for p in all_pages_metadata if p['id'] in target_ids]
        
        for page in relevant_pages:
            pid = page['id']
            parent = page['parent_id']
            pages_map[pid] = page
            if parent not in tree_map:
                tree_map[parent] = []
            tree_map[parent].append(pid)
        
        downloaded_ids = set(pages_map.keys())
        root_ids = []
        for page in relevant_pages:
            parent = page['parent_id']
            if parent is None or parent not in downloaded_ids:
                root_ids.append(page['id'])
        
        return tree_map, pages_map, root_ids
