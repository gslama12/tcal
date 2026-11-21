"""README.md's key table is the output of scripts/keys_table.py."""

import runpy
from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_readme_key_table_is_up_to_date() -> None:
    table = runpy.run_path(str(ROOT / "scripts" / "keys_table.py"))["keys_table"]()
    readme = (ROOT / "README.md").read_text()
    start = readme.index("<!-- keys:start -->\n") + len("<!-- keys:start -->\n")
    end = readme.index("<!-- keys:end -->")
    assert readme[start:end].strip() == table, "run: uv run python scripts/keys_table.py"


def test_key_table_lists_every_default_action() -> None:
    from tcal.config import default_data
    from tcal.ui.screens.help import GROUPS

    described = {action for rows in GROUPS.values() for action, _ in rows}
    assert set(default_data()["keys"]) <= described
