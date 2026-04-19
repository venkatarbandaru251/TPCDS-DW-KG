"""Invoke dbt with .env loaded and profiles/project dir set.

Usage: python -m ingestion.dbt_run <dbt args...>
Examples:
  python -m ingestion.dbt_run debug
  python -m ingestion.dbt_run parse
  python -m ingestion.dbt_run run
"""
import os
import sys

from .config import REPO_ROOT  # importing triggers load_dotenv()

TRANSFORM_DIR = REPO_ROOT / "transform"


def main(argv: list[str]) -> int:
    from dbt.cli.main import dbtRunner

    os.environ["DBT_PROFILES_DIR"] = str(TRANSFORM_DIR)
    os.chdir(TRANSFORM_DIR)
    result = dbtRunner().invoke(argv[1:])
    return 0 if result.success else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
