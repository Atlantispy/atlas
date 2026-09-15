"""Retain the unchanged R30 prepared geology regional interface and its keys.

These independent fixed-column jobs use no changed topography operation. Their
R30 source-pinned recipes, persistent forecast workers and cached receipts are
therefore deliberately forwarded without a new regional execution namespace.
"""
from work.generator_upgrade_r30.region import recipes, iter_region
