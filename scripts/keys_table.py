"""Print the default keybindings as a Markdown table (for README.md).

    uv run python scripts/keys_table.py

Keys come from ``tcal/default_config.toml``, groups and descriptions from the
help screen (``tcal.ui.screens.help.GROUPS``), so the README matches ``?``.
"""

from tcal.config import default_data
from tcal.ui.screens.help import sections


def keys_table() -> str:
    keys: dict[str, list[str]] = default_data()["keys"]
    lines = ["| Keys | Action |", "|---|---|"]
    for title, rows in sections(keys):
        lines.append(f"| **{title}** | |")
        for label, description in rows:
            shown = " ".join(f"`{k}`" for k in label.split(" "))
            lines.append(f"| {shown} | {description} |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(keys_table())
