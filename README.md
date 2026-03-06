Repository containing code that might be useful for the wider DS team.

## Installation

### Install everything (recommended)

To install all libraries in this repo at once:

```bash
pip install git+https://github.com/BLSQ/openhexa-ds-developments.git
```

This gives you access to all sub-libraries:

```python
from d2d_development import ...
from pyramid_matcher import ...
```

### Install a single library

If you only need one of the sub-libraries, you can install it individually:

```bash
# DHIS2-to-DHIS2 development utilities
pip install git+https://github.com/BLSQ/openhexa-ds-developments.git#subdirectory=d2d_development

# Pyramid matching utilities
pip install git+https://github.com/BLSQ/openhexa-ds-developments.git#subdirectory=pyramid_matching
```

See each sub-library's README for details:
- [d2d_development](d2d_development/README.md)
- [pyramid_matching](pyramid_matching/README.md)
