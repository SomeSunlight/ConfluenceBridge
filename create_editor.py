#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Confluence Sidebar Editor Generator (Robust Concatenation Version)
----------------------------------------------------------------
Generates a standalone HTML editor ('editor_sidebar.html') from 'sidebar.md'.
Uses direct string concatenation to avoid Python formatting issues with JS syntax.

Usage:
    python3 create_editor.py --site-dir "./output/TIMESTAMP Space X"
"""

import os
import sys
import argparse
import re
import html
import shutil
from urllib.parse import unquote, urlparse

# --- CSS CONTENT ---
CSS_CONTENT = """
    :root {
        --bg-color: #f4f5f7;
        --text-color: #172b4d;
        --link-color: #0052cc;
        --border-color: #dfe1e6;
        --hover-color: #ebecf0;
        --selected-color: #deebff;
        --drop-target-color: #b3d4ff;
        --danger-color: #de350b;
        --folder-line-color: #999; /* Darker line for better visibility */
        --insert-line-color: #0052cc;
    }

    * { box-sizing: border-box; }

    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 0; margin: 0; background: var(--bg-color); height: 100vh; display: flex; flex-direction: column; }

    header { background: white; padding: 10px 20px; border-bottom: 1px solid var(--border-color); display: flex; align-items: center; justify-content: space-between; box-shadow: 0 1px 3px rgba(0,0,0,0.05); z-index: 10; flex: 0 0 auto; }

    .toolbar-group { display: flex; gap: 10px; align-items: center; }

    h1 { margin: 0; font-size: 1.1rem; color: var(--text-color); margin-right: 20px; }

    button { background: white; border: 1px solid var(--border-color); color: var(--text-color); padding: 6px 12px; border-radius: 3px; cursor: pointer; font-size: 13px; }
    button:hover { background: var(--hover-color); }
    button.primary { background: var(--link-color); color: white; border-color: var(--link-color); font-weight: 500; }
    button.primary:hover { background: #0065ff; }

    input[type="text"] { padding: 6px 10px; border: 1px solid var(--border-color); border-radius: 3px; width: 200px; font-size: 13px; }

    .workspace { flex: 1; display: flex; overflow: hidden; }
    .tree-panel { flex: 1; overflow-y: auto; padding: 20px; background: white; }

    /* Tree Structure Styling */
    ul { list-style: none; padding: 0; margin: 0; }

    /* Nested lists indentation logic:
       Shift right and draw a border on the left to create the 'tree line' effect.
    */
    ul li ul { 
        margin-left: 11px; /* Aligns line roughly with center of toggle icon above */
        padding-left: 20px; /* Push content away from the line */
        border-left: 1px solid var(--folder-line-color); 
    }

    #root-tree { border-left: none; margin-left: 0; }

    li { margin: 0; position: relative; }

    .node-row { 
        display: flex; align-items: center; 
        padding: 4px 8px; 
        border-radius: 3px; 
        border: 2px solid transparent; 
        margin-bottom: 2px;
        cursor: default;
        user-select: none;
        transition: background 0.1s;
    }
    .node-row:hover { background: var(--hover-color); }
    .node-row.deleted { opacity: 0.5; text-decoration: line-through; background: #fff0f0; }

    .dragging { opacity: 0.4; background: #eee; }

    /* Drop Zones */
    .drag-over-top { border-top: 3px solid var(--insert-line-color) !important; background: transparent !important; }
    .drag-over-bottom { border-bottom: 3px solid var(--insert-line-color) !important; background: transparent !important; }
    .drag-over-middle { background: var(--drop-target-color) !important; border: 2px dashed var(--insert-line-color) !important; opacity: 0.9; }

    .toggle-icon { width: 24px; height: 24px; text-align: center; cursor: pointer; color: #6b778c; font-size: 12px; line-height: 24px; margin-right: 2px; border-radius: 3px; }
    .toggle-icon:hover { background: rgba(0,0,0,0.1); color: var(--text-color); }
    .toggle-icon.leaf { visibility: hidden; }

    .drag-handle { cursor: grab; color: #b3bac5; margin-right: 8px; font-size: 16px; padding: 0 4px; }
    .drag-handle:hover { color: var(--text-color); background: #eee; border-radius: 3px; }

    .node-icon { margin-right: 8px; font-size: 16px; }
    .node-title { flex: 1; font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; padding: 2px 5px; border-radius: 3px; border: 1px solid transparent; }
    .node-title:focus { border-color: var(--link-color); background: white; outline: none; }

    .actions { display: none; margin-left: 10px; gap: 4px; align-items: center; }
    .node-row:hover .actions { display: flex; }
    .action-btn { padding: 2px 8px; font-size: 11px; border: 1px solid #ccc; background: #fff; color: #42526e; border-radius: 3px; cursor: pointer; }
    .action-btn:hover { background: #ebecf0; color: var(--text-color); }
    .btn-del:hover { background: #ffebe6; color: var(--danger-color); border-color: var(--danger-color); }
    .btn-link { font-weight: bold; color: var(--link-color); }

    .hidden { display: none !important; }

    #toast { position: fixed; bottom: 20px; right: 20px; background: #333; color: white; padding: 10px 20px; border-radius: 4px; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
    #toast.show { opacity: 1; }

    #md-output-container { display: none; position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%); background: white; padding: 20px; box-shadow: 0 5px 20px rgba(0,0,0,0.2); border-radius: 8px; z-index: 100; width: 80%; height: 80%; flex-direction: column; }
    #md-textarea { flex: 1; width: 100%; margin-bottom: 10px; font-family: monospace; }
    #overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 99; }
"""

# --- 2. JS CONTENT ---
JS_CONTENT = """
console.log("0. JS Block Started.");

const app = {};
app.dragSrcEl = null;
app.root = null;

app.init = function() {
    console.log("1. app.init() called");
    this.root = document.getElementById('root-tree');

    if (!this.root) {
        console.error("CRITICAL: #root-tree not found");
        return;
    }

    this.root.addEventListener('click', (e) => {
        const target = e.target;
        if (target.classList.contains('toggle-icon')) {
            this.toggle(target);
        } else if (target.classList.contains('btn-del')) {
            this.deleteNode(target);
        } else if (target.classList.contains('btn-add')) {
            this.addChild(target);
        } else if (target.classList.contains('btn-exp')) {
            this.toggleRecursive(target, true);
        } else if (target.classList.contains('btn-col')) {
            this.toggleRecursive(target, false);
        } else if (target.classList.contains('btn-link')) {
            const row = target.closest('.node-row');
            const titleDiv = row.querySelector('.node-title');
            const href = titleDiv.getAttribute('data-href');
            if (href) window.open(href, '_blank');
        }
    });

    this.refreshDnD();

    const countEl = document.getElementById('node-count-display');
    if(countEl && window.EDITOR_NODE_COUNT) {
        countEl.innerText = window.EDITOR_NODE_COUNT;
    }
    console.log("2. App initialized.");
};

app.updateFolderState = function(li) {
    const ul = li.querySelector('ul');
    const toggle = li.querySelector('.node-row .toggle-icon');
    const icon = li.querySelector('.node-row .node-icon');

    if (!ul || ul.children.length === 0) {
        toggle.classList.add('leaf');
        toggle.innerText = '●';
        icon.innerText = '📄';
    } else {
        toggle.classList.remove('leaf');
        if (ul.classList.contains('hidden')) {
            toggle.innerText = '▶';
        } else {
            toggle.innerText = '▼';
        }
        icon.innerText = '📂';
    }
};

app.refreshDnD = function() {
    const rows = document.querySelectorAll('.node-row');
    rows.forEach(row => {
        row.setAttribute('draggable', 'true');
        row.ondragstart = this.handleDragStart.bind(this);
        row.ondragover = this.handleDragOver;
        row.ondragenter = this.handleDragEnter;
        row.ondragleave = this.handleDragLeave;
        row.ondrop = this.handleDrop.bind(this);
        row.ondragend = this.handleDragEnd;
    });
};

app.handleDragStart = function(e) {
    this.dragSrcEl = e.target.closest('li');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/html', e.target.innerHTML);
    e.target.classList.add('dragging');
};

app.handleDragOver = function(e) {
    if (e.preventDefault) e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    const row = e.currentTarget;
    const rect = row.getBoundingClientRect();
    const relY = e.clientY - rect.top;
    const height = rect.height;

    row.classList.remove('drag-over-top', 'drag-over-bottom', 'drag-over-middle');

    if (relY < height * 0.25) {
        row.classList.add('drag-over-top');
    } else if (relY > height * 0.75) {
        row.classList.add('drag-over-bottom');
    } else {
        row.classList.add('drag-over-middle');
    }
    return false;
};

app.handleDragEnter = function(e) {
    if (e.currentTarget.classList) e.currentTarget.classList.add('drag-over-middle');
};

app.handleDragLeave = function(e) {
    if (e.currentTarget.classList) e.currentTarget.classList.remove('drag-over-top', 'drag-over-bottom', 'drag-over-middle');
};

app.handleDrop = function(e) {
    if (e.stopPropagation) e.stopPropagation();

    const targetRow = e.currentTarget;
    const targetLi = targetRow.closest('li');

    if (this.dragSrcEl === targetLi || this.dragSrcEl.contains(targetLi)) {
        targetRow.classList.remove('drag-over-top', 'drag-over-bottom', 'drag-over-middle');
        return false;
    }

    const rect = targetRow.getBoundingClientRect();
    const relY = e.clientY - rect.top;
    const height = rect.height;

    if (relY < height * 0.25) {
        targetLi.parentNode.insertBefore(this.dragSrcEl, targetLi);
    } else if (relY > height * 0.75) {
        targetLi.parentNode.insertBefore(this.dragSrcEl, targetLi.nextSibling);
    } else {
        let ul = targetLi.querySelector('ul');
        if (!ul) {
            ul = document.createElement('ul');
            targetLi.appendChild(ul);
            const toggle = targetRow.querySelector('.toggle-icon');
            toggle.classList.remove('leaf');
            toggle.innerText = '▼';
            const icon = targetRow.querySelector('.node-icon');
            icon.innerText = '📂';
        }
        ul.classList.remove('hidden');
        ul.appendChild(this.dragSrcEl);
    }

    this.dragSrcEl.querySelector('.node-row').classList.remove('dragging');
    this.updateFolderState(targetLi);
    const oldParent = this.dragSrcEl.parentElement.closest('li');
    if (oldParent) this.updateFolderState(oldParent);

    targetRow.classList.remove('drag-over-top', 'drag-over-bottom', 'drag-over-middle');
    return false;
};

app.handleDragEnd = function(e) {
    document.querySelectorAll('.node-row').forEach(row => {
        row.classList.remove('drag-over-top', 'drag-over-bottom', 'drag-over-middle', 'dragging');
    });
};

app.toggle = function(el) {
    if (el.classList.contains('leaf')) return;
    const li = el.closest('li');
    const ul = li.querySelector('ul');
    if (ul) {
        if (ul.classList.contains('hidden')) {
            ul.classList.remove('hidden');
            el.innerText = '▼';
        } else {
            ul.classList.add('hidden');
            el.innerText = '▶';
        }
    }
};

app.toggleRecursive = function(btn, expand) {
    const rootLi = btn.closest('li');
    const processUl = (ul) => { if (expand) ul.classList.remove('hidden'); else ul.classList.add('hidden'); };
    const processToggle = (t) => { if (!t.classList.contains('leaf')) t.innerText = expand ? '▼' : '▶'; };

    const rootUl = rootLi.querySelector('ul');
    const rootToggle = rootLi.querySelector('.node-row .toggle-icon');
    if (rootUl) processUl(rootUl);
    if (rootToggle) processToggle(rootToggle);

    rootLi.querySelectorAll('ul').forEach(processUl);
    rootLi.querySelectorAll('.toggle-icon').forEach(processToggle);
};

app.expandAll = function() {
    document.querySelectorAll('ul.hidden').forEach(ul => ul.classList.remove('hidden'));
    document.querySelectorAll('.toggle-icon:not(.leaf)').forEach(el => el.innerText = '▼');
};

app.collapseAll = function() {
    document.querySelectorAll('#root-tree ul').forEach(ul => ul.classList.add('hidden'));
    document.querySelectorAll('.toggle-icon:not(.leaf)').forEach(el => el.innerText = '▶');
};

app.expandToLevel = function(level) {
    this.collapseAll();
    const expandRecursive = (ul, currentLevel) => {
        if (currentLevel >= level) return;

        Array.from(ul.children).forEach(li => {
            const childUl = li.querySelector('ul');
            const toggle = li.querySelector('.node-row .toggle-icon');

            if (childUl) {
                childUl.classList.remove('hidden');
                if (toggle && !toggle.classList.contains('leaf')) {
                    toggle.innerText = '▼';
                }
                expandRecursive(childUl, currentLevel + 1);
            }
        });
    };
    if (this.root) expandRecursive(this.root, 0);
};

app.deleteNode = function(btn) {
    const row = btn.closest('.node-row');
    row.classList.toggle('deleted');
};

app.addChild = function(btn) {
    const parentLi = btn.closest('li');
    let ul = parentLi.querySelector('ul');

    if (!ul) {
        ul = document.createElement('ul');
        parentLi.appendChild(ul);
    }
    ul.classList.remove('hidden');

    const newLi = app.createNodeElement("New Page", null);
    ul.prepend(newLi);

    this.updateFolderState(parentLi);
    this.refreshDnD();
};

app.newItem = function() {
    const newLi = app.createNodeElement("New Root Item", null);
    app.root.prepend(newLi);
    app.refreshDnD();
};

app.createNodeElement = function(title, href) {
    const li = document.createElement('li');
    // FIX: Use JS ternary operator for optional href check, not Python 'if'
    // And simple string concatenation for robustness
    const displayStyle = href ? '' : 'style="display:none"';

    li.innerHTML = `
        <div class="node-row" draggable="true">
            <span class="toggle-icon leaf">●</span>
            <span class="drag-handle">☰</span>
            <span class="node-icon">📄</span>
            <div class="node-title" contenteditable="true" data-href="${href || ''}">${title}</div>
            <div class="actions">
                <button class="action-btn btn-link" title="Open Page" ${displayStyle}>↗</button>
                <button class="action-btn btn-add" title="Add Child">+Child</button>
                <button class="action-btn btn-exp" title="Expand Recursive">+ +</button>
                <button class="action-btn btn-col" title="Collapse Recursive">- -</button>
                <button class="action-btn btn-del" title="Mark Deleted">Del</button>
            </div>
        </div>
    `;
    return li;
};

app.filter = function(term) {
    term = term.toLowerCase();
    const items = document.querySelectorAll('li');

    if (!term) {
        items.forEach(li => li.classList.remove('hidden'));
        return;
    }

    items.forEach(li => li.classList.add('hidden'));

    document.querySelectorAll('.node-title').forEach(div => {
        if (div.innerText.toLowerCase().includes(term)) {
            let li = div.closest('li');
            li.classList.remove('hidden');
            let parent = li.parentElement.closest('li');
            while (parent) {
                parent.classList.remove('hidden');
                const ul = parent.querySelector('ul');
                if (ul) ul.classList.remove('hidden');
                parent = parent.parentElement.closest('li');
            }
        }
    });
};

app.generateMarkdown = function() {
    let md = "";
    function walk(ul, level) {
        Array.from(ul.children).forEach(li => {
            const row = li.querySelector('.node-row');
            if (row.classList.contains('deleted')) return;
            const titleDiv = row.querySelector('.node-title');
            const title = titleDiv.innerText.trim();
            const href = titleDiv.getAttribute('data-href');
            const indent = "  ".repeat(level);
            if (href) {
                md += `${indent}- [${title}](${href})\\n`;
            } else {
                md += `${indent}- ${title}\\n`;
            }
            const childUl = li.querySelector('ul');
            if (childUl && childUl.children.length > 0) {
                walk(childUl, level + 1);
            }
        });
    }
    walk(this.root, 0);
    const textarea = document.getElementById('md-textarea');
    textarea.value = md;
    document.getElementById('overlay').style.display = 'block';
    document.getElementById('md-output-container').style.display = 'flex';
    textarea.select();
};

app.copyToClipboard = function() {
    const el = document.getElementById('md-textarea');
    el.select();
    document.execCommand('copy');
    const t = document.getElementById('toast');
    t.classList.add('show');
    setTimeout(() => t.classList.remove('show'), 2000);
};

app.closeModal = function() {
    document.getElementById('overlay').style.display = 'none';
    document.getElementById('md-output-container').style.display = 'none';
};

document.addEventListener('DOMContentLoaded', () => {
    app.init();
});
"""


# --- Python Parser Logic ---

class Node:
    def __init__(self, title, href=None, level=0):
        self.title = title
        self.href = href
        self.level = level
        self.children = []


def parse_markdown(md_content):
    lines = md_content.splitlines()
    root = Node("root", level=-1)
    stack = [root]
    node_count = 0

    link_pattern = re.compile(r'\[(.*?)\]\((.*?)\)')

    for line in lines:
        stripped = line.strip()
        if not stripped or not stripped.startswith('-'):
            continue

        raw_indent = line[:line.find('-')]
        level = raw_indent.count('\t') + (raw_indent.count(' ') // 2)
        content = stripped[1:].strip()

        match = link_pattern.search(content)
        if match:
            title = match.group(1)
            raw_href = match.group(2)
            filename = os.path.basename(unquote(urlparse(raw_href).path))
            href = f"pages/{filename}"
        else:
            title = content
            href = None

        node = Node(title, href, level)
        node_count += 1

        while len(stack) > 1 and stack[-1].level >= level:
            stack.pop()

        stack[-1].children.append(node)
        stack.append(node)

    return root, node_count


def render_editor_html(node):
    if not node.children: return ""

    ul_class = "hidden" if node.level >= 0 else ""
    html_out = f"<ul class='{ul_class}'>\n"

    for child in node.children:
        has_children = len(child.children) > 0
        icon = "📂" if has_children else "📄"
        arrow = "▶" if has_children else "▶"
        toggle_class = "" if has_children else "leaf"

        safe_title = html.escape(child.title)
        safe_href = html.escape(child.href) if child.href else ""
        href_attr = f'data-href="{safe_href}"' if child.href else ""

        html_out += f'<li>\n'
        html_out += f'<div class="node-row">\n'
        html_out += f'<span class="toggle-icon {toggle_class}">{arrow}</span>\n'
        html_out += f'<span class="drag-handle">☰</span>\n'
        html_out += f'<span class="node-icon">{icon}</span>\n'
        html_out += f'<div class="node-title" contenteditable="true" {href_attr}>{safe_title}</div>\n'
        html_out += '<div class="actions">\n'

        # Logic: Show link button only if href is present
        # Since this is Python generating HTML string, we use Python 'if'
        link_style = '' if child.href else 'style="display:none"'
        html_out += f'<button class="action-btn btn-link" title="Open Page" {link_style}>↗</button>\n'

        html_out += '<button class="action-btn btn-add" title="Add Child">+Child</button>\n'
        html_out += '<button class="action-btn btn-exp" title="Expand Recursive">+ +</button>\n'
        html_out += '<button class="action-btn btn-col" title="Collapse Recursive">- -</button>\n'
        html_out += '<button class="action-btn btn-del" title="Mark Deleted">Del</button>\n'
        html_out += '</div>\n'
        html_out += '</div>\n'  # End row

        if has_children:
            html_out += render_editor_html(child)

        html_out += "</li>\n"

    html_out += "</ul>\n"
    return html_out


def main():
    parser = argparse.ArgumentParser(description="Generate Sidebar Editor")
    parser.add_argument('--site-dir', required=True, help="Directory containing sidebar.md")
    args = parser.parse_args()

    site_dir = args.site_dir
    source_path = os.path.join(site_dir, "sidebar.md")
    edit_path = os.path.join(site_dir, "sidebar_edit.md")
    out_html_path = os.path.join(site_dir, "editor_sidebar.html")

    md_to_parse = source_path
    if os.path.exists(edit_path):
        print(f"Found working copy: {edit_path}")
        md_to_parse = edit_path
    elif os.path.exists(source_path):
        print(f"Creating working copy from: {source_path}")
        shutil.copy(source_path, edit_path)
        md_to_parse = edit_path
    else:
        print(f"Error: No sidebar.md found in {site_dir}")
        sys.exit(1)

    with open(md_to_parse, 'r', encoding='utf-8') as f:
        root, count = parse_markdown(f.read())

    tree_html = render_editor_html(root)

    # Fix root ul: ensure it's visible and has ID
    tree_html = tree_html.replace("<ul class='hidden'>", "<ul id='root-tree'>", 1)
    # Also handle the case where root was level -1 (class='')
    tree_html = tree_html.replace("<ul class=''>", "<ul id='root-tree'>", 1)

    # Assembly
    final_html = []
    final_html.append("<!DOCTYPE html><html lang='en'><head>\n")
    final_html.append('<meta charset="UTF-8">\n')
    final_html.append('<title>Sidebar Editor</title>\n')
    final_html.append('<style>\n')
    final_html.append(CSS_CONTENT)
    final_html.append('</style>\n')
    final_html.append('</head><body>\n')

    final_html.append("""
    <header>
        <div class="toolbar-group">
            <h1>Editor <span style="font-size:0.8em;color:#888" id="node-count-display"></span></h1>
            <button onclick="app.expandAll()">Expand All</button>
            <button onclick="app.collapseAll()">Collapse All</button>
            <button onclick="app.expandToLevel(1)">Lvl 1</button>
            <button onclick="app.expandToLevel(2)">Lvl 2</button>
            <button onclick="app.expandToLevel(3)">Lvl 3</button>
            <button onclick="app.expandToLevel(4)">Lvl 4</button>
            <button onclick="app.expandToLevel(5)">Lvl 5</button>
        </div>
        <div class="toolbar-group">
            <input type="text" placeholder="Search..." onkeyup="app.filter(this.value)">
            <button onclick="app.newItem()">+ New Root</button>
            <button class="primary" onclick="app.generateMarkdown()">Copy Markdown</button>
        </div>
    </header>
    \n""")

    final_html.append('<div class="workspace"><div class="tree-panel" id="tree-container">\n')
    final_html.append(tree_html)
    final_html.append('</div></div>\n')

    final_html.append("""
    <div id="overlay" onclick="app.closeModal()"></div>
    <div id="md-output-container">
        <h3>Markdown Result</h3>
        <p>Paste this into <strong>sidebar_edit.md</strong>:</p>
        <textarea id="md-textarea"></textarea>
        <div style="text-align: right;">
            <button onclick="app.closeModal()">Close</button>
            <button class="primary" onclick="app.copyToClipboard()">Copy to Clipboard</button>
        </div>
    </div>
    <div id="toast">Copied!</div>
    \n""")

    final_html.append(f'<script>window.EDITOR_NODE_COUNT = {count};</script>\n')
    final_html.append('<script>\n')
    final_html.append(JS_CONTENT)
    final_html.append('</script>\n')
    final_html.append('</body></html>\n')

    with open(out_html_path, 'w', encoding='utf-8') as f:
        f.write("".join(final_html))

    print(f"Success! Editor generated: {out_html_path}")


if __name__ == '__main__':
    main()