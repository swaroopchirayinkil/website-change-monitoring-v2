# -*- coding: utf-8 -*-
"""website_change_detect.py
A command‑line utility that tracks visual/layout changes of a website.

Features
--------
* **Cache** – Stores the HTML snapshot of a URL locally.
* **Update cache** – `update` command fetches the current page and overwrites the cached snapshot.
* **Check changes** – `check` command fetches the page again and prints a diff against the cached snapshot.
* **Simple** – Pure Python, only the ``requests`` library is required.

Usage
-----
```bash
# Initialise the cache for a site
python website_change_detect.py update --url https://example.com

# Later, detect any changes since the last update
python website_change_detect.py check --url https://example.com
```

The cache is stored under ``.website_change_cache`` in the directory where the script is run.
If the cache does not exist when ``check`` is executed the tool will exit with a helpful message.
"""

import argparse
import hashlib
import re
import sys
from bs4 import BeautifulSoup
from pathlib import Path
import difflib
import requests

CACHE_DIR_NAME = ".website_change_cache"

def get_cache_dir() -> Path:
    """Return the Path object for the cache directory, creating it if needed."""
    cache_dir = Path.cwd() / CACHE_DIR_NAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def url_to_filename(url: str) -> str:
    """Create a deterministic filename for a URL using SHA‑256.
    The filename is the hex digest with a .html suffix.
    """
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"{digest}.html"

def fetch_html(url: str) -> str:
    """Download the HTML content of *url*.
    Raises ``RuntimeError`` on network failures.
    """
    headers = {"User-Agent": "website-change-detect/1.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        # Parse HTML to safely remove invisible/dynamic elements
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove non-visual elements that change dynamically
        for tag in soup(["script", "style", "meta", "noscript"]):
            tag.decompose()
            
        # Remove all hidden inputs (handles CSRF, __VIEWSTATE, etc.)
        for hidden in soup.find_all("input", type=lambda t: t and t.lower() == "hidden"):
            hidden.decompose()
            
        html = soup.prettify()
        # Remove random GUIDs from image captchas
        html = re.sub(r'guid=[0-9a-fA-F\-]+', 'guid=IGNORED', html, flags=re.IGNORECASE)
        # Normalize newlines so reading/writing cache doesn't cause diffs
        html = html.replace('\r\n', '\n')
        
        return html
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc}") from exc

def cache_path_for_url(url: str) -> Path:
    return get_cache_dir() / url_to_filename(url)

def update_cache(url: str) -> tuple[str, str]:
    """Fetch *url* and store the HTML snapshot in the cache."""
    try:
        html = fetch_html(url)
    except RuntimeError as e:
        return "Failed", str(e)
    cache_path = cache_path_for_url(url)
    cache_path.write_text(html, encoding="utf-8")
    return "Updated", str(cache_path.name)

def check_changes(url: str) -> tuple[str, str]:
    """Compare the live HTML of *url* against the cached version."""
    cache_path = cache_path_for_url(url)
    if not cache_path.is_file():
        return "Failed", "No cached snapshot. Run 'update' first."
    cached_html = cache_path.read_text(encoding="utf-8")
    try:
        live_html = fetch_html(url)
    except RuntimeError as e:
        return "Failed", str(e)
    if cached_html == live_html:
        return "Unchanged", "No changes detected."
    diff = list(difflib.unified_diff(
        cached_html.splitlines(keepends=True),
        live_html.splitlines(keepends=True),
        fromfile="cached",
        tofile="live",
        lineterm="",
    ))
    return "Changed", f"Differences found ({len(diff)} lines in diff)"

def normalize_url(raw_url: str) -> str:
    """Normalize domain/URL input string to standard HTTP/HTTPS format."""
    url = raw_url.strip()
    if not url:
        return ""
    if not (url.startswith("http://") or url.startswith("https://")):
        url = "https://" + url
    if not url.endswith("/") and not Path(url.split("?")[0].split("#")[0]).suffix and "?" not in url and "#" not in url:
        url = url + "/"
    return url

def load_urls_from_file(file_path: Path) -> list[str]:
    """Read URLs from a text file, ignoring empty lines and comments."""
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return [normalize_url(line) for line in lines if line.strip() and not line.strip().startswith("#")]

def add_domains_to_file(
    input_urls: list[str],
    target_file: Path = Path("domain.txt")
) -> tuple[list[str], list[str]]:
    """
    Append new non-duplicate domains to the target domain file.
    Returns (added_urls, duplicate_urls).
    """
    existing_urls = load_urls_from_file(target_file)
    existing_set = {u.rstrip("/").lower() for u in existing_urls}
    
    added_urls = []
    duplicate_urls = []
    
    for raw in input_urls:
        norm = normalize_url(raw)
        if not norm:
            continue
        key = norm.rstrip("/").lower()
        if key in existing_set:
            if norm not in duplicate_urls:
                duplicate_urls.append(norm)
        else:
            added_urls.append(norm)
            existing_set.add(key)
            
    if added_urls:
        content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
        if content and not content.endswith("\n"):
            content += "\n"
        new_content = content + "\n".join(added_urls) + "\n"
        target_file.write_text(new_content, encoding="utf-8")
        
    return added_urls, duplicate_urls

def remove_domains_from_file(
    input_urls: list[str],
    target_file: Path = Path("domain.txt")
) -> list[str]:
    """
    Remove specified domains from target domain file and delete associated HTML cache files.
    Returns list of removed URLs.
    """
    if not target_file.exists():
        return []
        
    existing_urls = load_urls_from_file(target_file)
    remove_keys = {normalize_url(u).rstrip("/").lower() for u in input_urls if u.strip()}
    
    remaining_urls = []
    removed_urls = []
    
    for url in existing_urls:
        key = url.rstrip("/").lower()
        if key in remove_keys:
            removed_urls.append(url)
            cache_file = cache_path_for_url(url)
            if cache_file.exists():
                try:
                    cache_file.unlink()
                except Exception:
                    pass
        else:
            remaining_urls.append(url)
            
    if removed_urls:
        new_content = "\n".join(remaining_urls) + ("\n" if remaining_urls else "")
        target_file.write_text(new_content, encoding="utf-8")
        
    return removed_urls

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detect website visual/layout changes via HTML diff.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # UPDATE subcommand
    upd = subparsers.add_parser("update", help="Fetch page and store/refresh the cache")
    upd_group = upd.add_mutually_exclusive_group(required=True)
    upd_group.add_argument("--url", action="append", help="One or more URLs to cache (repeatable)")
    upd_group.add_argument("--url-file", type=Path, help="Path to a file containing URLs (one per line)")

    # CHECK subcommand
    chk = subparsers.add_parser("check", help="Compare live page with cached snapshot")
    chk_group = chk.add_mutually_exclusive_group(required=True)
    chk_group.add_argument("--url", action="append", help="One or more URLs to check (repeatable)")
    chk_group.add_argument("--url-file", type=Path, help="Path to a file containing URLs (one per line)")

    # ADD subcommand
    add_parser = subparsers.add_parser("add", help="Bulk or single add domain(s) to monitoring list file")
    add_group = add_parser.add_mutually_exclusive_group(required=False)
    add_group.add_argument("--url", "-u", action="append", help="Single or multiple target domain(s)/URL(s) to add (repeatable)")
    add_group.add_argument("--import-file", "-f", type=Path, help="Path to a text file containing domains to bulk import (one per line)")
    add_parser.add_argument("positional_urls", nargs="*", help="Domains/URLs passed as positional arguments")
    add_parser.add_argument("--target-file", type=Path, default=Path("domain.txt"), help="Monitoring domain list file to update (default: domain.txt)")
    add_parser.add_argument("--update-cache", action="store_true", help="Immediately fetch and store cached HTML snapshots for newly added domains")

    # REMOVE subcommand
    rem_parser = subparsers.add_parser("remove", help="Remove domain(s) from monitoring list file and delete cache")
    rem_group = rem_parser.add_mutually_exclusive_group(required=False)
    rem_group.add_argument("--url", "-u", action="append", help="Single or multiple domain(s)/URL(s) to remove (repeatable)")
    rem_group.add_argument("--import-file", "-f", type=Path, help="Path to a text file containing domains to remove (one per line)")
    rem_parser.add_argument("positional_urls", nargs="*", help="Domains/URLs passed as positional arguments")
    rem_parser.add_argument("--target-file", type=Path, default=Path("domain.txt"), help="Monitoring domain list file to update (default: domain.txt)")

    return parser

def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.command == "remove":
        raw_inputs = []
        if args.url:
            raw_inputs.extend(args.url)
        if args.positional_urls:
            raw_inputs.extend(args.positional_urls)
        if args.import_file:
            if not args.import_file.exists():
                print(f"❌ Error: Import file '{args.import_file}' not found.")
                sys.exit(1)
            file_urls = [line.strip() for line in args.import_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
            raw_inputs.extend(file_urls)

        if not raw_inputs:
            print("❌ Error: No domains provided to remove. Use --url, --import-file, or pass domains as arguments.")
            sys.exit(1)

        removed = remove_domains_from_file(raw_inputs, args.target_file)
        
        print("\n🗑️ Domain Removal Results:")
        print("=" * 65)
        print(f" Target File   : {args.target_file.resolve()}")
        print(f" Removed       : {len(removed)} domain(s)")
        
        if removed:
            print("\nRemoved Domains & Cache Cleaned:")
            for u in removed:
                print(f"  • {u}")

        total_in_file = len(load_urls_from_file(args.target_file))
        print(f"\n📊 Remaining Domains in '{args.target_file.name}': {total_in_file}\n")
        return

    if args.command == "add":
        raw_inputs = []
        if args.url:
            raw_inputs.extend(args.url)
        if args.positional_urls:
            raw_inputs.extend(args.positional_urls)
        if args.import_file:
            if not args.import_file.exists():
                print(f"❌ Error: Import file '{args.import_file}' not found.")
                sys.exit(1)
            file_urls = [line.strip() for line in args.import_file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]
            raw_inputs.extend(file_urls)
            
        if not raw_inputs:
            print("❌ Error: No domains provided. Use --url, --import-file, or pass domains as arguments.")
            sys.exit(1)
            
        added, duplicates = add_domains_to_file(raw_inputs, args.target_file)
        
        print("\n➕ Bulk Domain Import Results:")
        print("=" * 65)
        print(f" Target File   : {args.target_file.resolve()}")
        print(f" Newly Added  : {len(added)} domain(s)")
        print(f" Duplicates   : {len(duplicates)} domain(s) skipped")
        
        if added:
            print("\nNewly Added Domains:")
            for u in added:
                print(f"  • {u}")
                
        if duplicates:
            print("\nSkipped Existing Duplicates:")
            for u in duplicates:
                print(f"  • {u}")
                
        total_in_file = len(load_urls_from_file(args.target_file))
        print(f"\n📊 Total Monitoring Domains in '{args.target_file.name}': {total_in_file}")
        
        if args.update_cache and added:
            print(f"\n📥 Auto-updating Cache for {len(added)} newly added domain(s)...")
            print("-" * 65)
            for url in added:
                status, details = update_cache(url)
                url_fmt = url[:42] + "..." if len(url) > 45 else url.ljust(45)
                print(f"  {url_fmt} | {status.ljust(8)} | {details}")
        print()
        return

    # Resolve URLs from either --url or --url-file
    if args.command == "update":
        if getattr(args, "url_file", None):
            urls = [line.strip() for line in args.url_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            urls = args.url
            
        print(f"\n{'URL'.ljust(45)} | {'Status'.ljust(8)} | {'Details'}")
        print("-" * 45 + "-+-" + "-" * 8 + "-+-" + "-" * 40)
        
        for url in urls:
            status, details = update_cache(url)
            url_fmt = url[:42] + "..." if len(url) > 45 else url.ljust(45)
            status_fmt = status.ljust(8)
            print(f"{url_fmt} | {status_fmt} | {details}")
    elif args.command == "check":
        if getattr(args, "url_file", None):
            urls = [line.strip() for line in args.url_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        else:
            urls = args.url
            
        print(f"\n{'URL'.ljust(45)} | {'Status'.ljust(9)} | {'Details'}")
        print("-" * 45 + "-+-" + "-" * 9 + "-+-" + "-" * 40)
        
        for url in urls:
            status, details = check_changes(url)
            url_fmt = url[:42] + "..." if len(url) > 45 else url.ljust(45)
            status_fmt = status.ljust(9)
            print(f"{url_fmt} | {status_fmt} | {details}")

if __name__ == "__main__":
    main()
