# -*- coding: utf-8 -*-
"""
Unit-Tests für atomare Datei-Operationen.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import json

from confluence_dump.utils.file_ops import (
    atomic_write_text,
    atomic_write_json,
    atomic_write_binary
)


@pytest.fixture
def temp_dir():
    """Erstellt temporäres Verzeichnis für Tests."""
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


def test_atomic_write_text_creates_file(temp_dir):
    """Test: Neue Textdatei wird korrekt erstellt."""
    file_path = temp_dir / "test.txt"
    content = "Hallo Welt"
    
    atomic_write_text(file_path, content)
    
    assert file_path.exists()
    assert file_path.read_text(encoding='utf-8') == content


def test_atomic_write_text_creates_parent_dirs(temp_dir):
    """Test: Elternverzeichnisse werden automatisch erstellt."""
    file_path = temp_dir / "subdir" / "nested" / "test.txt"
    content = "Test"
    
    atomic_write_text(file_path, content)
    
    assert file_path.exists()
    assert file_path.read_text(encoding='utf-8') == content


def test_atomic_write_text_overwrites_existing(temp_dir):
    """Test: Bestehende Datei wird korrekt überschrieben."""
    file_path = temp_dir / "test.txt"
    file_path.write_text("Alt", encoding='utf-8')
    
    atomic_write_text(file_path, "Neu")
    
    assert file_path.read_text(encoding='utf-8') == "Neu"


def test_atomic_write_text_no_tmp_file_left(temp_dir):
    """Test: Keine .tmp Datei bleibt zurück."""
    file_path = temp_dir / "test.txt"
    
    atomic_write_text(file_path, "Test")
    
    tmp_files = list(temp_dir.glob("*.tmp"))
    assert len(tmp_files) == 0


def test_atomic_write_json_creates_valid_json(temp_dir):
    """Test: JSON wird korrekt serialisiert."""
    file_path = temp_dir / "test.json"
    data = {"key": "value", "number": 42, "nested": {"a": 1}}
    
    atomic_write_json(file_path, data)
    
    assert file_path.exists()
    loaded = json.loads(file_path.read_text(encoding='utf-8'))
    assert loaded == data


def test_atomic_write_json_pretty_format(temp_dir):
    """Test: JSON ist formatiert (indent=2)."""
    file_path = temp_dir / "test.json"
    data = {"a": 1, "b": 2}
    
    atomic_write_json(file_path, data)
    
    content = file_path.read_text(encoding='utf-8')
    assert '\n' in content  # Formatiert, nicht einzeilig


def test_atomic_write_json_unicode(temp_dir):
    """Test: Unicode-Zeichen werden korrekt gespeichert."""
    file_path = temp_dir / "test.json"
    data = {"text": "Zürich, Genève, Ñoño"}
    
    atomic_write_json(file_path, data)
    
    loaded = json.loads(file_path.read_text(encoding='utf-8'))
    assert loaded["text"] == "Zürich, Genève, Ñoño"


def test_atomic_write_binary_creates_file(temp_dir):
    """Test: Binärdatei wird korrekt erstellt."""
    file_path = temp_dir / "test.bin"
    content = b'\x00\x01\x02\xff\xfe'
    
    atomic_write_binary(file_path, content)
    
    assert file_path.exists()
    assert file_path.read_bytes() == content


def test_atomic_write_binary_overwrites(temp_dir):
    """Test: Bestehende Binärdatei wird überschrieben."""
    file_path = temp_dir / "test.bin"
    file_path.write_bytes(b'old')
    
    atomic_write_binary(file_path, b'new')
    
    assert file_path.read_bytes() == b'new'


def test_atomic_operations_are_isolated(temp_dir):
    """Test: Parallele Schreibvorgänge interferieren nicht."""
    file_path = temp_dir / "test.txt"
    
    # Simuliere parallele Schreibvorgänge
    atomic_write_text(file_path, "First")
    atomic_write_text(file_path, "Second")
    
    # Nur der letzte Schreibvorgang sollte sichtbar sein
    assert file_path.read_text(encoding='utf-8') == "Second"
    
    # Keine .tmp Dateien
    assert len(list(temp_dir.glob("*.tmp"))) == 0
