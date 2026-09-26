### How to Run

1. **Run the Watcher & Queue Runner**:
   ```bash
   uv run --with pyyaml python -m myaristotle.cli watch_and_pull
   ```
   Or directly with the script runner:
   ```bash
   uv run src/myaristotle/cli.py watch_and_pull
   ```

2. **Run Tests**:
   ```bash
   uv run --with pytest --with pyyaml pytest
   ```
