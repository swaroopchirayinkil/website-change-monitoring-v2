# -*- coding: utf-8 -*-
"""
monitor/diff_engine.py
-----------------------
Pixel-by-pixel visual diff calculation and heatmap generation using Python Pillow.
"""

from pathlib import Path
from PIL import Image, ImageChops, ImageEnhance

def compute_visual_diff(
    baseline_path: Path,
    latest_path: Path,
    diff_path: Path,
    threshold_percent: float = 0.1,
) -> dict:
    """Compare baseline and latest screenshots pixel-by-pixel."""
    img_base = Image.open(baseline_path).convert("RGB")
    img_live = Image.open(latest_path).convert("RGB")

    width = max(img_base.width, img_live.width)
    height = max(img_base.height, img_live.height)

    # Pad images to match maximum dimensions if viewport height varies
    if img_base.size != (width, height):
        padded = Image.new("RGB", (width, height), (255, 255, 255))
        padded.paste(img_base, (0, 0))
        img_base = padded

    if img_live.size != (width, height):
        padded = Image.new("RGB", (width, height), (255, 255, 255))
        padded.paste(img_live, (0, 0))
        img_live = padded

    # Compute absolute RGB difference
    diff_raw = ImageChops.difference(img_base, img_live)
    gray_diff = diff_raw.convert("L")

    # Filter minor noise/anti-aliasing (threshold < 15 out of 255)
    noise_cutoff = 15
    mask = gray_diff.point(lambda p: 255 if p > noise_cutoff else 0, mode="1")

    histogram = mask.histogram()
    changed_pixels = histogram[255] if len(histogram) > 255 else 0
    total_pixels = width * height
    percentage = (changed_pixels / total_pixels) * 100.0 if total_pixels > 0 else 0.0

    # Generate visual heatmap (bright magenta highlight on dimmed baseline)
    enhancer = ImageEnhance.Brightness(img_base.convert("L").convert("RGB"))
    dimmed_baseline = enhancer.enhance(0.4)
    highlight_color = Image.new("RGB", (width, height), (255, 0, 110))

    visual_heatmap = Image.composite(highlight_color, dimmed_baseline, mask)
    visual_heatmap.save(diff_path)

    is_changed = percentage > threshold_percent

    return {
        "width": width,
        "height": height,
        "total_pixels": total_pixels,
        "changed_pixels": changed_pixels,
        "percentage": round(percentage, 4),
        "is_changed": is_changed,
    }
