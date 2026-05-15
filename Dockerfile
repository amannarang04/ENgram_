FROM python:3.11-slim

WORKDIR /app

# Copy the entire repository into the container
COPY . /app/

# The benchmark uses pure Python stdlib, so no pip install is required.
# Run the canonical L2 benchmark validation script.
CMD ["python", "run.py", "--adapter", "adapters.myteam:EngineAdapter", "--mode", "fast", "--seeds", "9999", "31415", "27182", "16180", "11235", "--n-services", "20", "--days", "14", "--out", "report.json"]
