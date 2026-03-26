# -*- coding: utf-8 -*-
"""
Configuration Manager for Self-Contained Workspaces.
Manages config.json with hash validation for Delta-Sync.
"""

from pathlib import Path
from typing import Dict, Any, Optional
import json
import hashlib
from datetime import datetime

from confluence_dump.utils.file_ops import atomic_write_json


class ConfigManager:
    """
    Manages workspace configuration in config.json.
    Enables Zero-Config Sync and prevents parameter conflicts.
    """
    
    # Fields that are NOT saved in config.json
    EXCLUDED_FIELDS = {
        'no_vpn_reminder',  # Transient flag
        'outdir',           # Derived from workspace path
        'func',             # Internal argparse function
        'use_etl',          # Always set to True for ETL
    }
    
    # Fields relevant for hash calculation (content parameters)
    HASH_RELEVANT_FIELDS = {
        'command', 'base_url', 'profile', 'context_path',
        'space_key', 'label', 'pageid', 'exclude_page_id', 'exclude_label'
    }
    
    def __init__(self, workspace_dir: Path):
        """
        Initializes ConfigManager.
        
        Args:
            workspace_dir: Workspace directory (contains config.json)
        """
        self.workspace_dir = workspace_dir
        self.config_path = workspace_dir / 'config.json'
    
    def exists(self) -> bool:
        """
        Checks if config.json exists.
        
        Returns:
            True if workspace is already configured
        """
        return self.config_path.exists()
    
    def save_config(self, args: Any) -> None:
        """
        Saves CLI arguments as config.json.
        
        Args:
            args: argparse.Namespace with CLI arguments
        """
        config = {
            'version': '1.0',
            'created': datetime.now().isoformat(),
        }
        
        # Convert argparse.Namespace to Dict
        args_dict = vars(args)
        
        # Filter relevant fields
        for key, value in args_dict.items():
            if key not in self.EXCLUDED_FIELDS:
                config[key] = value
        
        # Calculate hash over content parameters
        config['config_hash'] = self._compute_config_hash(config)
        
        # Save atomically
        atomic_write_json(self.config_path, config)
    
    def load_config(self) -> Dict[str, Any]:
        """
        Loads config.json.
        
        Returns:
            Dictionary with configuration
            
        Raises:
            FileNotFoundError: If config.json does not exist
            json.JSONDecodeError: If config.json is corrupt
        """
        if not self.exists():
            raise FileNotFoundError(f"config.json not found in {self.workspace_dir}")
        
        return json.loads(self.config_path.read_text(encoding='utf-8'))
    
    def validate_config_hash(self, args: Any) -> tuple[bool, Optional[str]]:
        """
        Validates if CLI arguments are compatible with saved config.
        
        Args:
            args: argparse.Namespace with CLI arguments
            
        Returns:
            Tuple (is_valid, error_message)
            - is_valid: True if compatible
            - error_message: Actionable Error Message on conflict, otherwise None
        """
        try:
            stored_config = self.load_config()
        except Exception as e:
            return False, f"Could not load config.json: {e}"
        
        # Extract only hash-relevant fields from CLI-Args
        args_dict = vars(args)
        cli_config = {k: v for k, v in args_dict.items() if k in self.HASH_RELEVANT_FIELDS}
        
        # Calculate hash of CLI parameters
        cli_hash = self._compute_config_hash(cli_config)
        stored_hash = stored_config.get('config_hash')
        
        if cli_hash != stored_hash:
            # Find differing fields for helpful, actionable error message
            conflicts = []
            for field in self.HASH_RELEVANT_FIELDS:
                cli_val = cli_config.get(field)
                stored_val = stored_config.get(field)
                if cli_val != stored_val and cli_val is not None:
                    # Special handling for common conflicts
                    if field == 'command':
                        conflicts.append(
                            f"  • Command conflict: Workspace was created with '{stored_val}', "
                            f"but '{cli_val}' was specified"
                        )
                    elif field == 'pageid' and stored_val is None and cli_val is not None:
                        conflicts.append(
                            f"  • Page-ID conflict: Workspace was created without specific Page-ID, "
                            f"but --pageid {cli_val} was specified"
                        )
                    elif field == 'space_key' and stored_val is None and cli_val is not None:
                        conflicts.append(
                            f"  • Space-Key conflict: Workspace was created without Space-Key, "
                            f"but --space-key {cli_val} was specified"
                        )
                    else:
                        conflicts.append(f"  • {field}: '{stored_val}' (saved) ≠ '{cli_val}' (specified)")
            
            if not conflicts:
                conflicts.append("  • Unknown deviation in configuration")
            
            error_msg = (
                "The specified parameters differ from the saved workspace configuration:\n" + 
                "\n".join(conflicts)
            )
            return False, error_msg
        
        return True, None
    
    def _compute_config_hash(self, config: Dict[str, Any]) -> str:
        """
        Calculates SHA256 hash over relevant configuration fields.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Hex string of hash
        """
        # Extract only hash-relevant fields, sorted for determinism
        relevant = {k: config.get(k) for k in sorted(self.HASH_RELEVANT_FIELDS) if k in config}
        
        # Convert to JSON string (sorted keys for determinism)
        config_str = json.dumps(relevant, sort_keys=True, ensure_ascii=False)
        
        # Calculate hash
        return hashlib.sha256(config_str.encode('utf-8')).hexdigest()
    
    def merge_with_cli_args(self, args: Any) -> Any:
        """
        Merges saved config with CLI-Args.
        CLI-Args take precedence for flags like --threads.
        
        Args:
            args: argparse.Namespace with CLI arguments
            
        Returns:
            Merged argparse.Namespace
        """
        stored_config = self.load_config()
        args_dict = vars(args)
        
        # Overwrite with saved values (except explicitly set CLI flags)
        for key, value in stored_config.items():
            if key in ('version', 'created', 'config_hash'):
                continue  # Skip metadata
            
            # Only overwrite if CLI value is default
            if key not in args_dict or args_dict[key] is None or args_dict[key] == False:
                args_dict[key] = value
        
        # Convert back to Namespace
        import argparse
        return argparse.Namespace(**args_dict)
