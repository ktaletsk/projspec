# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`projspec` is a Python library that provides a unified interface to different types of code projects. It allows programmatic introspection of projects regardless of their underlying tooling (poetry, pixi, uv, conda, node, rust, etc.).

The library defines three core concepts:
- **Project Specs**: Definitions of project types, tied to specific tools (e.g., `PythonLibrary`, `Pixi`, `Poetry`)
- **Contents**: Things that exist within a project (packages, environments, data dependencies, metadata)
- **Artifacts**: Things a project can make or execute (wheels, containers, processes, linters)

## Development Commands

### Installation
```bash
# Install in editable mode with test dependencies
pip install -e .[test]
```

### Testing
```bash
# Run all tests with coverage
pytest -v --cov projspec

# Run specific test file
pytest tests/test_basic.py -v

# Run specific test function
pytest tests/test_basic.py::test_basic -v
```

### Linting
```bash
# Run pre-commit hooks (includes black, ruff, etc.)
pre-commit run --all-files

# Auto-format with black
black src/projspec tests
```

### CLI Usage
```bash
# Analyze current directory
projspec .

# Analyze with summary view
projspec . --summary

# Walk all subdirectories
projspec . --walk

# Filter to specific project types
projspec . --types "Pixi,Poetry"

# Exclude specific types
projspec . --xtypes "GitRepo"

# Make/execute an artifact
projspec . --make wheel

# Get info about a spec/content/artifact type
projspec --info PythonLibrary
```

## Architecture

### Core Classes

**Project** (`src/projspec/proj/base.py:34`): Main entry point. Given a directory path, it attempts to parse it with all registered `ProjectSpec` subclasses. Can recursively walk subdirectories to find child projects.

**ProjectSpec** (`src/projspec/proj/base.py:276`): Base class for all project type definitions. Subclasses automatically register themselves on import. Each spec must implement:
- `match()`: Fast check if a path might conform to this spec (e.g., check for specific files)
- `parse()`: Read metadata and populate `_contents` and `_artifacts` attributes

**ProjectExtra** (`src/projspec/proj/base.py:372`): Special subclass for specs that add contents/artifacts to the root project but aren't standalone projects (e.g., CI/CD configs, linters).

**BaseContent** (`src/projspec/content/base.py:11`): Dataclass representing descriptive project information (packages, environments, licenses, etc.). Read-only introspection.

**BaseArtifact** (`src/projspec/artifact/base.py:14`): Executable actions. Most wrap subprocess calls to external tools. Can check state (clean/done/pending) and provide `make()`, `remake()`, and `clean()` methods.

### Adding a New Project Type

1. Create a new file in `src/projspec/proj/` (e.g., `myproject.py`)
2. Define a class inheriting from `ProjectSpec` or `ProjectExtra`
3. Implement `match()` to check for presence of config files
4. Implement `parse()` to read metadata and populate contents/artifacts
5. Import the class in `src/projspec/proj/__init__.py`
6. The class auto-registers via `__init_subclass__`

Example pattern (see `src/projspec/proj/python_code.py:50-73`):
```python
class MyProject(ProjectSpec):
    spec_doc = "https://url.to/documentation"

    def match(self) -> bool:
        return "my-config.toml" in self.proj.basenames

    def parse(self):
        # Read config
        with self.proj.fs.open(self.proj.basenames["my-config.toml"]) as f:
            config = toml.load(f)

        # Create artifacts
        self._artifacts = AttrDict(
            build=Process(proj=self.proj, cmd=["mytool", "build"])
        )

        # Create contents
        self._contents = AttrDict(
            package=MyPackage(proj=self.proj, name=config["name"])
        )
```

### Registry System

All spec, content, and artifact classes auto-register on import via `__init_subclass__`. Three registries exist:
- `projspec.proj.base.registry`: All `ProjectSpec` subclasses
- `projspec.content.base.registry`: All `BaseContent` subclasses
- `projspec.artifact.base.registry`: All `BaseArtifact` subclasses

Access via snake_case names (e.g., `PythonLibrary` → `python_library`).

### Utilities

**AttrDict** (`src/projspec/utils.py:47`): Dict subclass allowing attribute access (e.g., `proj.specs.python_library` instead of `proj.specs["python_library"]`)

**camel_to_snake()**: Converts class names to snake_case for registry keys

**fsspec integration**: All file operations use `fsspec` for abstracting local/remote filesystems. Check `proj.is_local()` before running local commands.

## Project-Specific Patterns

### Supported Project Types

The library currently supports 15+ project types including:
- Python: `PythonLibrary`, `PythonCode`, `Poetry`, `Uv`, `Pixi`
- Packaging: `CondaRecipe`, `RattlerRecipe`, `CondaProject`
- Documentation: `RTD`, `MDBook`
- Other: `Node`, `Rust`, `RustPython`, `Helm`, `GitRepo`, `VSCode`, `JetbrainsIDE`

See `src/projspec/proj/` for all implementations.

### Accessing Project Data

```python
# Parse a project
proj = projspec.Project("path/to/project")

# Access specs
python_lib = proj.specs.python_library  # or proj["python_library"]

# Get all artifacts (flattened)
artifacts = proj.all_artifacts()
artifacts = proj.all_artifacts(names=["wheel", "container"])

# Check if project supports an artifact type
from projspec.artifact.installable import Wheel
if proj.has_artifact_type([Wheel]):
    # This project can build wheels
    pass

# Access child projects
for subpath, child_proj in proj.children.items():
    print(f"{subpath}: {list(child_proj.specs.keys())}")
```

### Serialization

Projects, specs, contents, and artifacts are all serializable:
```python
# To dict (compact or verbose)
proj.to_dict(compact=True)   # Condensed output
proj.to_dict(compact=False)  # Includes class metadata

# Projects can be pickled
import pickle
pickle.dumps(proj)

# Full round-trip
import json
js = json.dumps(proj.to_dict(compact=False))
proj2 = projspec.Project.from_dict(json.loads(js))
```

## Code Style

- **Formatting**: Black with target Python 3.8+ (line length 80)
- **Linting**: Ruff with extensive ruleset (see `pyproject.toml:55-144`)
- **Type hints**: Not strictly enforced but preferred
- **Python versions**: Support 3.9-3.13

## Testing Patterns

Tests use pytest with a shared fixture (`tests/conftest.py:11`) that parses the projspec repo itself:
```python
@pytest.fixture
def proj():
    return projspec.Project(os.path.dirname(here), walk=True)
```

This "eating our own dogfood" approach tests real-world parsing on this repository.

## Important Notes

- **Fast matching**: Keep `match()` methods lightweight—they run for every directory against every spec type
- **Graceful failure**: `parse()` should raise `ParseFailed` if the directory doesn't match expectations
- **Local-only execution**: Artifact `make()` methods only work on local filesystems (raises `RuntimeError` otherwise)
- **Cached properties**: `Project.filelist`, `Project.basenames`, and `Project.pyproject` are cached—use for efficient repeated access
- **Directory exclusions**: Default excludes (`build`, `dist`, `env`, `.git`, etc.) prevent infinite recursion
