# Screen matching measurements - 2026-09-12

Measured locally with the bundled OpenCV 4.12.0. Medians of three alternating,
warmed runs on the same frame. Matching excludes capture and initial template
preparation. No screenshots were saved.

| Case | Original | Optimized | Speedup | Same result |
|---|---:|---:|---:|---|
| 1080p exact match | 249 ms | 67 ms | 3.70x | Yes |
| 1080p missing texture | 248 ms | 64 ms | 3.86x | Yes |
| 1080p alpha mask | 566 ms | 199 ms | 2.84x | Yes |
| 4K exact match | 998 ms | 276 ms | 3.62x | Yes |
| 4K missing texture | 1010 ms | 246 ms | 4.11x | Yes |
| 4K alpha mask | 2992 ms | 1153 ms | 2.60x | Yes |
| Actual 2880x1800 desktop, known-present crop | 551 ms | 168 ms | 3.28x | Yes |

Six existing saved textures compared on the actual desktop at 90% confidence:
806-989 ms original versus 230-393 ms optimized, 2.39-4.31x speedups, all results
identical. The first capture measured 173 ms; a later capture measured 118 ms.
For the known-present crop this gives an estimated complete search of 669 ms
versus 286 ms, about 2.34x faster including that capture. End-to-end timings vary
with desktop size, capture latency, template content, confidence and fallback.

Correctness regression tests cover edges, tile boundaries, alpha masks,
confidence thresholds, duplicate matches, constant colors, channel ambiguity,
fresh frames, negative monitor origins and template cache invalidation.
