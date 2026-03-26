# -*- coding: utf-8 -*-
"""
Unit-Tests für Manifest-Management.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import json
from datetime import datetime

from confluence_dump.api.manifest import Manifest


@pytest.fixture
def temp_dir():
    """Erstellt temporäres Verzeichnis für Tests."""
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


def test_manifest_creates_new_if_not_exists(temp_dir):
    """Test: Neues Manifest wird erstellt wenn nicht vorhanden."""
    manifest = Manifest(temp_dir)
    
    assert manifest.data['version'] == '1.0'
    assert manifest.data['pages'] == {}
    assert manifest.data['deleted_pages'] == []
    assert manifest.data['last_sync'] is None


def test_manifest_loads_existing(temp_dir):
    """Test: Bestehendes Manifest wird geladen."""
    manifest_path = temp_dir / 'manifest.json'
    existing_data = {
        'version': '1.0',
        'last_sync': '2026-01-01T12:00:00',
        'space_key': 'TEST',
        'pages': {'123': {'title': 'Test', 'version': 1}},
        'deleted_pages': []
    }
    manifest_path.write_text(json.dumps(existing_data), encoding='utf-8')
    
    manifest = Manifest(temp_dir)
    
    assert manifest.data['space_key'] == 'TEST'
    assert '123' in manifest.data['pages']


def test_manifest_update_page(temp_dir):
    """Test: Seite wird korrekt aktualisiert."""
    manifest = Manifest(temp_dir)
    
    manifest.update_page('123', 'Test Page', 5, '2026-01-01T10:00:00', None)
    
    assert '123' in manifest.data['pages']
    page = manifest.data['pages']['123']
    assert page['title'] == 'Test Page'
    assert page['version'] == 5
    assert page['parent_id'] is None
    assert page['status'] == 'current'
    assert page['needs_mhtml'] is False


def test_manifest_update_page_with_mhtml(temp_dir):
    """Test: Seite mit MHTML-Flag wird korrekt gespeichert."""
    manifest = Manifest(temp_dir)
    
    manifest.update_page('456', 'Complex Page', 3, '2026-01-01T11:00:00', '123', needs_mhtml=True)
    
    page = manifest.data['pages']['456']
    assert page['needs_mhtml'] is True
    assert page['parent_id'] == '123'


def test_manifest_needs_update_new_page(temp_dir):
    """Test: Neue Seite benötigt Update."""
    manifest = Manifest(temp_dir)
    
    assert manifest.needs_update('999', 1) is True


def test_manifest_needs_update_same_version(temp_dir):
    """Test: Seite mit gleicher Version benötigt kein Update."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 5, '2026-01-01', None)
    
    assert manifest.needs_update('123', 5) is False


def test_manifest_needs_update_newer_version(temp_dir):
    """Test: Seite mit neuerer Version benötigt Update."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 5, '2026-01-01', None)
    
    assert manifest.needs_update('123', 6) is True


def test_manifest_needs_update_older_version(temp_dir):
    """Test: Seite mit älterer Version benötigt kein Update."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 5, '2026-01-01', None)
    
    assert manifest.needs_update('123', 4) is False


def test_manifest_mark_deleted(temp_dir):
    """Test: Seite wird als gelöscht markiert."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 1, '2026-01-01', None)
    
    manifest.mark_deleted('123')
    
    assert '123' not in manifest.data['pages']
    assert '123' in manifest.data['deleted_pages']


def test_manifest_mark_deleted_twice(temp_dir):
    """Test: Doppeltes Löschen ist idempotent."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 1, '2026-01-01', None)
    
    manifest.mark_deleted('123')
    manifest.mark_deleted('123')
    
    assert manifest.data['deleted_pages'].count('123') == 1


def test_manifest_get_mhtml_pages(temp_dir):
    """Test: MHTML-Seiten werden korrekt gefiltert."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Normal', 1, '2026-01-01', None, needs_mhtml=False)
    manifest.update_page('456', 'Complex', 1, '2026-01-01', None, needs_mhtml=True)
    manifest.update_page('789', 'Also Complex', 1, '2026-01-01', None, needs_mhtml=True)
    
    mhtml_pages = manifest.get_mhtml_pages()
    
    assert len(mhtml_pages) == 2
    assert '456' in mhtml_pages
    assert '789' in mhtml_pages
    assert '123' not in mhtml_pages


def test_manifest_set_needs_mhtml(temp_dir):
    """Test: MHTML-Flag kann nachträglich gesetzt werden."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 1, '2026-01-01', None)
    
    manifest.set_needs_mhtml('123', True)
    
    assert manifest.data['pages']['123']['needs_mhtml'] is True


def test_manifest_save_creates_file(temp_dir):
    """Test: Manifest wird als Datei gespeichert."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'Test', 1, '2026-01-01', None)
    
    manifest.save()
    
    manifest_path = temp_dir / 'manifest.json'
    assert manifest_path.exists()


def test_manifest_save_updates_timestamp(temp_dir):
    """Test: last_sync wird beim Speichern aktualisiert."""
    manifest = Manifest(temp_dir)
    
    before = datetime.now()
    manifest.save()
    after = datetime.now()
    
    last_sync = datetime.fromisoformat(manifest.data['last_sync'])
    assert before <= last_sync <= after


def test_manifest_get_all_page_ids(temp_dir):
    """Test: Alle Page IDs werden zurückgegeben."""
    manifest = Manifest(temp_dir)
    manifest.update_page('123', 'A', 1, '2026-01-01', None)
    manifest.update_page('456', 'B', 1, '2026-01-01', None)
    manifest.update_page('789', 'C', 1, '2026-01-01', None)
    
    page_ids = manifest.get_all_page_ids()
    
    assert len(page_ids) == 3
    assert page_ids == {'123', '456', '789'}


def test_manifest_set_space_key(temp_dir):
    """Test: Space Key wird gesetzt."""
    manifest = Manifest(temp_dir)
    
    manifest.set_space_key('MYSPACE')
    
    assert manifest.data['space_key'] == 'MYSPACE'


def test_manifest_roundtrip(temp_dir):
    """Test: Manifest kann gespeichert und wieder geladen werden."""
    manifest1 = Manifest(temp_dir)
    manifest1.set_space_key('TEST')
    manifest1.update_page('123', 'Page 1', 5, '2026-01-01', None, needs_mhtml=True)
    manifest1.update_page('456', 'Page 2', 3, '2026-01-02', '123')
    manifest1.save()
    
    manifest2 = Manifest(temp_dir)
    
    assert manifest2.data['space_key'] == 'TEST'
    assert len(manifest2.data['pages']) == 2
    assert manifest2.data['pages']['123']['needs_mhtml'] is True
    assert manifest2.data['pages']['456']['parent_id'] == '123'
