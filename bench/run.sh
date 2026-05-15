#!/bin/bash
set -e

echo "Starting Engram Persistent Context Engine L2 Benchmark..."
python run.py --adapter adapters.myteam:EngineAdapter --mode fast --seeds 9999 31415 27182 16180 11235 --n-services 20 --days 14 --out report.json
echo "Benchmark complete! Results saved to report.json."
