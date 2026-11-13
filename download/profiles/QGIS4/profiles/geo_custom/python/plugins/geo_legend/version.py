# -*- coding: utf-8 -*-
"""
Version information for QGIS Legend View plugin
"""

# Version components
MAJOR = 2
MINOR = 5
PATCH = 0

# Pre-release identifier (alpha, beta, rc) - empty for stable releases
PRERELEASE = ""

# Build metadata
BUILD = ""


def get_version():
    """Get the full version string"""
    version = f"{MAJOR}.{MINOR}.{PATCH}"

    if PRERELEASE:
        version += f"-{PRERELEASE}"

    if BUILD:
        version += f"+{BUILD}"

    return version


def get_version_info():
    """Get version information as a dictionary"""
    return {
        'major': MAJOR,
        'minor': MINOR,
        'patch': PATCH,
        'prerelease': PRERELEASE,
        'build': BUILD,
        'version': get_version()
    }


def is_stable():
    """Check if this is a stable release"""
    return not PRERELEASE


def get_compatibility_info():
    """Get QGIS compatibility information"""
    return {
        'minimum_qgis_version': '4.0',
        'maximum_qgis_version': '4.99',
        'qt6_support': True,
        'supported_qgis_versions': ['4.0+']
    }


# Version string for easy import
__version__ = get_version()

if __name__ == "__main__":
    print(f"QGIS Legend View Plugin Version: {get_version()}")
    print(f"Version Info: {get_version_info()}")
    print(f"Is Stable: {is_stable()}")
    print(f"Compatibility: {get_compatibility_info()}")
