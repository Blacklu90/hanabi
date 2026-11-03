"""Shuinkan (朱印館). This app was called "Hanabi" before; old settings and data keep working."""
import os

# Old HANABI_* environment settings still apply (the new SHUINKAN_* names win when both are set).
for _k, _v in list(os.environ.items()):
    if _k.startswith("HANABI_"):
        os.environ.setdefault("SHUINKAN_" + _k[len("HANABI_"):], _v)
