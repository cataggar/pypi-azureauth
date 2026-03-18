# Show the current version
version:
    uvx --with hatch-vcs hatchling version

# Build wheels for a specific azureauth version (e.g., just build 0.9.5)
build version:
    uv run scripts/build_wheels.py {{version}}

# Clean build artifacts
clean:
    rm -rf dist/
