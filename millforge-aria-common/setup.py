from setuptools import setup, find_packages

setup(
    name="millforge-aria-common",
    version="1.0.0",
    description="Shared types and validation for the ARIA-OS ↔ MillForge bridge",
    author="Jonathan Kofman",
    packages=find_packages(),
    python_requires=">=3.11",
    extras_require={
        "submission": ["aiohttp>=3.9"],
    },
)
