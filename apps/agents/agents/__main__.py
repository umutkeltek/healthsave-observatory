"""Module entrypoint: ``python -m agents``.

Mirrors :mod:`worker.__main__` so the Compose service can run the
same image with a different command. See :func:`agents.main.main`.
"""

from .main import main

if __name__ == "__main__":
    main()
