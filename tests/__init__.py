"""Test suite for adb-auto-game.

Run with::

    python -m unittest discover -s tests   # zero extra deps
    python -m pytest tests                  # if pytest is installed

These tests are a regression safety net for the src/ refactor: they pin the
pure logic (settings round-trips, parsing, caching) and verify every module
imports and every game still instantiates.
"""
