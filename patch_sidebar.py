#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Confluence Sidebar Patcher (Site-Dir Aware)
-------------------------------------------
Applies the structure from 'sidebar.md' (or 'sidebar_edit.md') to all HTML files.
Supports automatic root-unwrapping for Space exports via magic comments.

Usage:
    python3 patch_sidebar.py --site-dir "./output/TIMESTAMP Space X"
"""

import os
import sys
import argparse
import re
import copy
from urllib.parse import unquote, urlparse
from bs4 import BeautifulSoup, Comment


class Node:
    def __init__(self, title, page_id=None, level=0):
        self.title = title
        self.page_id = page_id
        self.level = level
        self.children = []


def parse_markdown_to_tree(md_content):
    """
    Parses markdown into a Node tree.
    Returns the root Node and a detected config dictionary.
    """
    lines = md_content.splitlines()
    root = Node("root", level=-1)
    stack = [root]

    config = {'mode': 'default'}

    link_pattern = re.compile(r'\[(.*?)\]\((.*?)\)')
    config_pattern = re.compile(r'<!--\s*(.*?)\s*-->')

    for line in lines:
        stripped = line.strip()

        # Check for config comments (e.g. <!-- mode: space -->)
        if stripped.startswith('<!--'):
            match = config_pattern.search(stripped)
            if match:
                content = match.group(1)
                if 'mode:' in content:
                    key, val = content.split(':', 1)
                    config[key.strip()] = val.strip()
            continue

        if not stripped or not stripped.startswith('-'): continue

        raw_indent = line[:line.find('-')]
        # level calculation: 2 spaces or 1 tab = 1 level step
        level = raw_indent.count('\t') + (raw_indent.count(' ') // 2)

        content = stripped[1:].strip()

        match = link_pattern.search(content)
        if match:
            title = match.group(1)
            href = match.group(2)
            try:
                path = unquote(urlparse(href).path)
                filename = os.path.basename(path)
                page_id = os.path.splitext(filename)[0]
            except:
                page_id = None
        else:
            title = content
            page_id = None

        node = Node(title, page_id, level)

        # Adjust stack based on level
        while len(stack) > 1 and stack[-1].level >= level:
            stack.pop()

        stack[-1].children.append(node)
        stack.append(node)

    return root, config


def render_tree_to_html(root):
    """ Renders the Node tree to the HTML structure required by the CSS. """

    def render_node(n):
        if not n.children:
            # Leaf
            if n.page_id:
                link = f'<a href="{n.page_id}.html">{n.title}</a>'
                return f'<li class="leaf">{link}</li>'
            else:
                return f'<li class="leaf"><span>{n.title}</span></li>'
        else:
            # Folder
            inner_html = "".join([render_node(c) for c in n.children])
            if n.page_id:
                link = f'<a href="{n.page_id}.html">{n.title}</a>'
                # Use details/summary for collapsible folder
                return f'<li class="folder"><details><summary>{link}</summary><ul>{inner_html}</ul></details></li>'
            else:
                return f'<li class="folder"><details><summary>{n.title}</summary><ul>{inner_html}</ul></details></li>'

    sidebar_content = "<ul>" + "".join([render_node(c) for c in root.children]) + "</ul>"
    return f'<div class="sidebar-tree">{sidebar_content}</div>'


def apply_active_state(sidebar_soup, current_page_id):
    """ Sets 'active-page' class and expands details for the current path. """
    for tag in sidebar_soup.find_all(attrs={"class": "active-page"}):
        tag['class'].remove("active-page")
    for tag in sidebar_soup.find_all('details', attrs={"open": True}):
        del tag['open']

    target_href = f"{current_page_id}.html"
    active_link = sidebar_soup.find('a', href=target_href)

    if active_link:
        active_link['class'] = active_link.get('class', []) + ['active-page']
        parent = active_link.parent
        while parent:
            if parent.name == 'details':
                parent['open'] = ''
            parent = parent.parent
    return sidebar_soup


def patch_page(file_path, sidebar_soup_template):
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        soup = BeautifulSoup(content, 'html.parser')

        meta_id = soup.find('meta', attrs={'name': 'confluence-page-id'})
        if meta_id and meta_id.get('content'):
            page_id = meta_id['content']
        else:
            page_id = os.path.splitext(os.path.basename(file_path))[0]

        aside = soup.find('aside', id='sidebar')
        if not aside: return False

        sidebar_instance = copy.copy(sidebar_soup_template)
        apply_active_state(sidebar_instance, page_id)

        aside.clear()
        aside.append(Comment(" CONFLUENCE-SIDEBAR-START "))
        if sidebar_instance.body:
            for child in list(sidebar_instance.body.children): aside.append(child)
        else:
            for child in list(sidebar_instance.children): aside.append(child)
        aside.append(Comment(" CONFLUENCE-SIDEBAR-END "))

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
        return True
    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Patch Sidebar")
    parser.add_argument('--site-dir', required=True, help="Base directory of the dump")
    parser.add_argument('--restore-original', action='store_true', help="Use sidebar_orig.md")
    parser.add_argument('--unwrap', action='store_true', help="Force unwrap of root node (promote children)")

    args = parser.parse_args()

    pages_dir = os.path.join(args.site_dir, "pages")

    if args.restore_original:
        source_path = os.path.join(args.site_dir, "sidebar_orig.md")
        print("Mode: Restoring Original Sidebar")
    else:
        edit_path = os.path.join(args.site_dir, "sidebar_edit.md")
        orig_path = os.path.join(args.site_dir, "sidebar.md")
        if os.path.exists(edit_path):
            source_path = edit_path
            print("Mode: Applying Edited Sidebar (sidebar_edit.md)")
        else:
            source_path = orig_path
            print("Mode: Applying Standard Sidebar (sidebar.md)")

    if not os.path.exists(pages_dir):
        print(f"Error: Pages dir not found: {pages_dir}")
        sys.exit(1)
    if not os.path.exists(source_path):
        print(f"Error: Source file not found: {source_path}")
        sys.exit(1)

    print(f"Reading source: {source_path}")
    with open(source_path, 'r', encoding='utf-8') as f:
        # 1. Parse
        root, config = parse_markdown_to_tree(f.read())

    # 2. Logic: Should we unwrap the root?
    # Condition: (Flag set OR Magic Comment 'mode: space') AND (Root has exactly 1 child)
    should_unwrap = args.unwrap or (config.get('mode') == 'space')

    if should_unwrap:
        if len(root.children) == 1:
            print(f"Unwrapping root node: '{root.children[0].title}' -> Children promoted to top level.")
            root = root.children[0]
            # We don't change root.level here because render starts inside root.children
        else:
            print("Unwrap requested but root has multiple (or zero) children. Skipping unwrap.")

    # 3. Render
    html_content = render_tree_to_html(root)
    sidebar_template = BeautifulSoup(html_content, 'html.parser')

    files = [f for f in os.listdir(pages_dir) if f.endswith('.html')]
    total = len(files)
    count = 0

    print(f"Patching {total} files...")
    for filename in files:
        if patch_page(os.path.join(pages_dir, filename), sidebar_template):
            count += 1
        if count % 100 == 0: print(f"  {count}...")

    print(f"Done. Patched {count}/{total} files.")


if __name__ == '__main__':
    main()