# -*- coding: utf-8 -*-
"""
Unit-Tests für Configuration Manager.
"""

import pytest
from pathlib import Path
import tempfile
import shutil
import json
import argparse

from confluence_dump.utils.config_manager import ConfigManager


@pytest.fixture
def temp_workspace():
    """Erstellt temporäres Workspace-Verzeichnis."""
    tmp = Path(tempfile.mkdtemp())
    yield tmp
    shutil.rmtree(tmp)


@pytest.fixture
def sample_args():
    """Erstellt Sample argparse.Namespace."""
    return argparse.Namespace(
        command='space',
        base_url='https://confluence.example.com',
        profile='dc',
        context_path='/wiki',
        space_key='IT',
        label=None,
        pageid=None,
        exclude_page_id=['123'],
        exclude_label=None,
        threads=8,
        skip_mhtml=False,
        css_file=None,
        manual_overrides_dir=None,
        debug_storage=False,
        debug_views=False,
        no_metadata_json=False,
        no_vpn_reminder=True,  # Sollte nicht gespeichert werden
        outdir='/some/path',   # Sollte nicht gespeichert werden
        func=lambda: None,     # Sollte nicht gespeichert werden
        use_etl=True           # Sollte nicht gespeichert werden
    )


def test_config_manager_exists_false(temp_workspace):
    """Test: exists() gibt False wenn config.json nicht existiert."""
    cm = ConfigManager(temp_workspace)
    assert cm.exists() is False


def test_config_manager_exists_true(temp_workspace):
    """Test: exists() gibt True wenn config.json existiert."""
    (temp_workspace / 'config.json').write_text('{}', encoding='utf-8')
    cm = ConfigManager(temp_workspace)
    assert cm.exists() is True


def test_save_config_creates_file(temp_workspace, sample_args):
    """Test: save_config() erstellt config.json."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    assert cm.config_path.exists()


def test_save_config_excludes_fields(temp_workspace, sample_args):
    """Test: Transiente Felder werden nicht gespeichert."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    config = json.loads(cm.config_path.read_text(encoding='utf-8'))
    
    assert 'no_vpn_reminder' not in config
    assert 'outdir' not in config
    assert 'func' not in config
    assert 'use_etl' not in config


def test_save_config_includes_relevant_fields(temp_workspace, sample_args):
    """Test: Relevante Felder werden gespeichert."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    config = json.loads(cm.config_path.read_text(encoding='utf-8'))
    
    assert config['command'] == 'space'
    assert config['base_url'] == 'https://confluence.example.com'
    assert config['space_key'] == 'IT'
    assert config['threads'] == 8


def test_save_config_includes_hash(temp_workspace, sample_args):
    """Test: config_hash wird berechnet und gespeichert."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    config = json.loads(cm.config_path.read_text(encoding='utf-8'))
    
    assert 'config_hash' in config
    assert len(config['config_hash']) == 64  # SHA256 hex


def test_load_config_success(temp_workspace, sample_args):
    """Test: load_config() lädt gespeicherte Config."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    loaded = cm.load_config()
    
    assert loaded['command'] == 'space'
    assert loaded['space_key'] == 'IT'


def test_load_config_not_found(temp_workspace):
    """Test: load_config() wirft FileNotFoundError."""
    cm = ConfigManager(temp_workspace)
    
    with pytest.raises(FileNotFoundError):
        cm.load_config()


def test_validate_config_hash_identical(temp_workspace, sample_args):
    """Test: Identische Parameter sind valide."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    is_valid, error = cm.validate_config_hash(sample_args)
    
    assert is_valid is True
    assert error is None


def test_validate_config_hash_conflict(temp_workspace, sample_args):
    """Test: Abweichende Parameter führen zu Konflikt."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    # Ändere inhaltlichen Parameter
    modified_args = argparse.Namespace(**vars(sample_args))
    modified_args.space_key = 'OTHER'
    
    is_valid, error = cm.validate_config_hash(modified_args)
    
    assert is_valid is False
    assert error is not None
    assert 'space_key' in error


def test_validate_config_hash_ignores_threads(temp_workspace, sample_args):
    """Test: Änderung von --threads ist erlaubt (nicht hash-relevant)."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    # Ändere nicht-inhaltlichen Parameter
    modified_args = argparse.Namespace(**vars(sample_args))
    modified_args.threads = 16
    
    is_valid, error = cm.validate_config_hash(modified_args)
    
    assert is_valid is True
    assert error is None


def test_merge_with_cli_args(temp_workspace, sample_args):
    """Test: merge_with_cli_args() kombiniert Config und CLI."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    # Neuer CLI-Aufruf mit nur wenigen Parametern
    minimal_args = argparse.Namespace(
        threads=16,  # Überschreibt gespeicherten Wert
        command=None,
        base_url=None,
        space_key=None
    )
    
    merged = cm.merge_with_cli_args(minimal_args)
    
    # Gespeicherte Werte werden übernommen
    assert merged.command == 'space'
    assert merged.base_url == 'https://confluence.example.com'
    assert merged.space_key == 'IT'
    
    # CLI-Wert hat Vorrang
    assert merged.threads == 16


def test_config_hash_deterministic(temp_workspace, sample_args):
    """Test: Hash ist deterministisch."""
    cm1 = ConfigManager(temp_workspace)
    cm1.save_config(sample_args)
    config1 = cm1.load_config()
    
    cm2 = ConfigManager(temp_workspace)
    cm2.save_config(sample_args)
    config2 = cm2.load_config()
    
    assert config1['config_hash'] == config2['config_hash']


def test_config_roundtrip(temp_workspace, sample_args):
    """Test: Config kann gespeichert und geladen werden."""
    cm = ConfigManager(temp_workspace)
    cm.save_config(sample_args)
    
    loaded = cm.load_config()
    
    assert loaded['version'] == '1.0'
    assert 'created' in loaded
    assert loaded['command'] == sample_args.command
    assert loaded['space_key'] == sample_args.space_key
