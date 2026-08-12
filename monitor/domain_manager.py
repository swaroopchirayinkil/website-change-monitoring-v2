# -*- coding: utf-8 -*-
"""
monitor/domain_manager.py
--------------------------
Domain CRUD operations, URL normalization, deduplication, and SHA-256 slugging.
"""

import hashlib
from pathlib import Path
from monitor.config import BASELINES_DIR, LATEST_DIR, DIFFS_DIR, DEFAULT_DOMAIN_FILE

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

def url_to_slug(url: str) -> str:
    """Generate a clean, deterministic filename slug for a URL."""
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    sanitized = "".join(c if c.isalnum() else "_" for c in url.split("//")[-1])[:30]
    return f"{sanitized}_{digest}"

def load_urls_from_file(file_path: Path = DEFAULT_DOMAIN_FILE) -> list[str]:
    """Read URLs from a text file, ignoring empty lines and comments."""
    if not file_path.exists():
        return []
    lines = file_path.read_text(encoding="utf-8").splitlines()
    return [normalize_url(line) for line in lines if line.strip() and not line.strip().startswith("#")]

def add_domains_to_file(
    input_urls: list[str],
    target_file: Path = DEFAULT_DOMAIN_FILE
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
    target_file: Path = DEFAULT_DOMAIN_FILE
) -> list[str]:
    """
    Remove specified domains from target domain file and delete associated baseline/latest/diff cache files.
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
            # Remove cached screenshot files
            slug = url_to_slug(url)
            for p in [BASELINES_DIR / f"{slug}.png", LATEST_DIR / f"{slug}.png", DIFFS_DIR / f"{slug}_diff.png"]:
                if p.exists():
                    try:
                        p.unlink()
                    except Exception:
                        pass
        else:
            remaining_urls.append(url)
            
    if removed_urls:
        new_content = "\n".join(remaining_urls) + ("\n" if remaining_urls else "")
        target_file.write_text(new_content, encoding="utf-8")
        
    return removed_urls
