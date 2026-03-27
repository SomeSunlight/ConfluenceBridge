# -*- coding: utf-8 -*-
"""
MHTML Downloader Module for Playwright Phase.
Downloads complex pages containing specific macros as complete MHTML files.
"""

from pathlib import Path
from typing import Set, Dict, Any
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


class MHTMLDownloader:
    """
    Downloads Confluence pages via Playwright as MHTML.
    """
    
    _global_auth_verified = False
    
    def __init__(self, output_dir: Path, base_url: str):
        """
        Initialize the MHTML Downloader.
        
        Args:
            output_dir: Path to the workspace output directory.
            base_url: The base URL of the Confluence instance.
        """
        self.output_dir = output_dir
        self.raw_data_dir = output_dir / 'raw-data'
        self.base_url = base_url.rstrip('/')
        
    def verify_playwright_auth(self) -> bool:
        """
        Opens a browser and asks the user to manually log in to Confluence.
        Waits until the user closes the browser.
        """
        if MHTMLDownloader._global_auth_verified:
            return True

        print("\n" + "="*70)
        print("[!] CONFLUENCE AUTHENTICATION REQUIRED FOR PLAYWRIGHT")
        print("="*70)
        print("1. A browser window will now open. This might take a minute or two")
        print(f"2. Please log in to: {self.base_url}")
        print("3. Solve any MFA/SSO challenges.")
        print("4. Close the browser window completely when you are fully logged in.")
        print("="*70 + "\n")
        
        try:
            with sync_playwright() as p:
                user_data_dir = self.output_dir / '.playwright_auth'
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=False,
                    viewport={'width': 1280, 'height': 800}
                )
                page = browser.new_page()
                page.goto(self.base_url)
                
                print("Waiting for you to log in and close the browser...")
                try:
                    # Wait for the user to close the page/browser
                    page.wait_for_event("close", timeout=0)
                except PlaywrightTimeoutError:
                    pass
                
                # Make sure context is closed to save states
                browser.close()
                
            print("✅ Authentication window closed. Proceeding with downloads.")
            MHTMLDownloader._global_auth_verified = True
            return True
        except Exception as e:
            print(f"❌ Error during authentication: {e}")
            return False

    def download_pages(self, page_ids: Set[str], manifest_data: Dict[str, Any], verbose: bool = True) -> Dict[str, int]:
        """
        Downloads the specified pages as MHTML.
        """
        stats = {'success': 0, 'failed': 0, 'skipped': 0}
        
        if not page_ids:
            return stats
            
        if not MHTMLDownloader._global_auth_verified:
            success = self.verify_playwright_auth()
            if not success:
                print("⚠️ Warning: Could not verify authentication. The downloaded pages might be login screens.")
                
        print(f"\nStarting Playwright download for {len(page_ids)} complex pages...")
        
        try:
            with sync_playwright() as p:
                user_data_dir = self.output_dir / '.playwright_auth'
                # Launch headless for the actual batch download
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=True,
                    viewport={'width': 1920, 'height': 1080}
                )
                page = browser.new_page()
                
                for i, page_id in enumerate(page_ids):
                    page_dir = self.raw_data_dir / page_id
                    page_dir.mkdir(parents=True, exist_ok=True)
                    mhtml_path = page_dir / "content.mhtml"
                    
                    if mhtml_path.exists():
                        if verbose:
                            print(f"  [{i+1}/{len(page_ids)}] ⏭️  Skipping {page_id} (already downloaded)")
                        stats['skipped'] += 1
                        continue
                        
                    try:
                        url = f"{self.base_url}/pages/viewpage.action?pageId={page_id}"
                        if verbose:
                            print(f"  [{i+1}/{len(page_ids)}] 🌐 Downloading {page_id} via Playwright...")
                            
                        # Navigate and wait for network activity to settle
                        page.goto(url, wait_until='networkidle', timeout=60000)
                        
                        # Wait an extra 5 seconds to ensure JavaScript macros (like Table Filter) fully render
                        page.wait_for_timeout(5000)
                        
                        cdp = page.context.new_cdp_session(page)
                        mhtml = cdp.send('Page.captureSnapshot', {'format': 'mhtml'})
                        
                        # WICHTIG: newline='' verhindert, dass Windows aus \r\n ein \r\r\n macht!
                        with open(mhtml_path, 'w', encoding='utf-8', newline='') as f:
                            f.write(mhtml['data'])
                        
                        stats['success'] += 1
                        if verbose:
                            print(f"    ✅ Saved MHTML to {mhtml_path.name}")
                            
                    except Exception as e:
                        print(f"    ❌ Error downloading {page_id}: {e}")
                        stats['failed'] += 1
                        
                browser.close()
        except Exception as e:
            print(f"Playwright execution error: {e}")
            
        return stats
