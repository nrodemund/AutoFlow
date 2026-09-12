"""Compare matching on identical frames. No screenshots are written to disk.

Run: runtime/python/python.exe scripts/benchmark_screen.py [--live] [--repeats 3]
Live mode only captures pixels; it does not click or change the desktop.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image
from autoflow.screen import WindowsScreen, prepare_texture, match_prepared


def compare(name, scene, texture, repeats, confidence=.97):
    prepared = prepare_texture(texture)
    timings = {False: [], True: []}
    results = {}
    # Warm libraries first; alternate order to reduce drift bias.
    for fast in (False, True): match_prepared(scene, prepared, confidence, accelerated=fast)
    for iteration in range(repeats):
        for fast in ((False, True) if iteration % 2 == 0 else (True, False)):
            start = time.perf_counter()
            result = match_prepared(scene, prepared, confidence, accelerated=fast)
            timings[fast].append((time.perf_counter() - start) * 1000)
            results[fast] = result
    old, new = (statistics.median(timings[fast]) for fast in (False, True))
    return dict(case=name, size=list(scene.size), confidence=confidence,
                original_ms=round(old, 2), optimized_ms=round(new, 2),
                speedup=round(old / new, 2), found=results[False] is not None,
                same_result=results[False] == results[True])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--asset-limit', type=int, default=6)
    args = parser.parse_args()
    if args.repeats < 1: parser.error('repeats must be positive')
    rng = np.random.default_rng(2026)
    if args.live:
        start = time.perf_counter()
        scene, _ = WindowsScreen.capture_desktop()
        print(json.dumps({'capture_ms': round((time.perf_counter() - start) * 1000, 2), 'size': list(scene.size)}), flush=True)
        print(json.dumps(compare('desktop-crop', scene, scene.crop((100, 100, min(400, scene.width), min(200, scene.height))), args.repeats)), flush=True)
        paths = sorted((Path(__file__).resolve().parents[1] / 'projects/assets').glob('*.png'))[:max(0,args.asset_limit)]
        for path in paths:
            with Image.open(path) as texture:
                print(json.dumps(compare(path.name, scene, texture, args.repeats, .9)), flush=True)
    else:
        for width, height in ((1920, 1080), (3840, 2160)):
            scene = Image.fromarray(rng.integers(0, 256, (height, width, 3), dtype=np.uint8))
            texture = scene.crop((200, 100, 450, 140))
            print(json.dumps(compare('exact', scene, texture, args.repeats)), flush=True)
            absent = Image.fromarray(rng.integers(0, 256, (40, 250, 3), dtype=np.uint8))
            print(json.dumps(compare('absent', scene, absent, args.repeats)), flush=True)
            masked = texture.convert('RGBA');masked.putpixel((0, 0), (0, 0, 0, 0))
            print(json.dumps(compare('alpha', scene, masked, args.repeats)), flush=True)


if __name__ == '__main__': main()
