# -*- coding: utf-8 -*-
"""
Atomare Datei-Operationen für transaktionssichere Schreibvorgänge.
Alle Schreiboperationen verwenden temporäre Dateien und atomares Umbenennen.
"""

from pathlib import Path
import os
import json
from typing import Dict, Any


def atomic_write_text(file_path: Path, content: str, encoding: str = 'utf-8') -> None:
    """
    Schreibt Text atomar via .tmp-Datei.
    
    Bei einem Abbruch während des Schreibvorgangs bleibt die ursprüngliche Datei
    intakt oder es existiert keine Datei (bei Neuanlage).
    
    Args:
        file_path: Ziel-Dateipfad
        content: Zu schreibender Text
        encoding: Zeichenkodierung (Standard: utf-8)
    
    Raises:
        OSError: Bei Dateisystem-Fehlern
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(file_path.suffix + '.tmp')
    
    try:
        tmp_path.write_text(content, encoding=encoding)
        os.replace(tmp_path, file_path)  # Atomare Operation (POSIX & Windows)
    except Exception:
        # Cleanup: Temporäre Datei löschen falls vorhanden
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def atomic_write_json(file_path: Path, data: Dict[str, Any]) -> None:
    """
    Schreibt JSON atomar.
    
    Args:
        file_path: Ziel-Dateipfad
        data: Zu serialisierendes Dictionary
    
    Raises:
        OSError: Bei Dateisystem-Fehlern
        TypeError: Bei nicht-serialisierbaren Daten
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(file_path.suffix + '.tmp')
    
    try:
        with tmp_path.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, file_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def atomic_write_binary(file_path: Path, content: bytes) -> None:
    """
    Schreibt Binärdaten atomar.
    
    Args:
        file_path: Ziel-Dateipfad
        content: Zu schreibende Bytes
    
    Raises:
        OSError: Bei Dateisystem-Fehlern
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(file_path.suffix + '.tmp')
    
    try:
        tmp_path.write_bytes(content)
        os.replace(tmp_path, file_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise
