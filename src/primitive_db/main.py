#!/usr/bin/env python3

from primitive_db.engine import run


def main():
    """Run the database CLI and return its exit status."""
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
