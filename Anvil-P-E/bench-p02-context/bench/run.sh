#!/bin/bash
set -e

# Change directory to the parent folder containing run.py
cd "$(dirname "$0")/.."

echo "Running ENgram Context Engine benchmark..."
python run.py --adapter adapters.myteam:EngineAdapter --mode fast --seeds 9999 31415 27182 16180 11235 --n-services 20 --days 14 --out report.json
echo "Benchmark complete. Results saved to report.json."
