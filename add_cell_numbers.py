"""
One-off script: add a "Cell #NN" label to every cell of the given notebooks,
numbered sequentially per-file starting at 1. Safe with respect to Jupyter
cell-magic rules (a %% cell magic must be the literal first line of the
cell, so those get their label appended at the end instead of prepended).

Run with: python3 add_cell_numbers.py <notebook.ipynb> [<notebook.ipynb> ...]
"""
import json
import sys
from pathlib import Path


def _as_lines(text: str) -> list[str]:
    """Split into nbformat-style source lines (each ending in \\n except a
    possible trailing line), matching how these notebooks already look."""
    if text == "":
        return []
    lines = text.split("\n")
    out = [line + "\n" for line in lines[:-1]]
    if lines[-1] != "":
        out.append(lines[-1])
    return out


def label_notebook(path: Path) -> None:
    nb = json.loads(path.read_text(encoding="utf-8"))
    cells = nb["cells"]
    width = max(2, len(str(len(cells))))

    for i, cell in enumerate(cells, start=1):
        tag = f"Cell #{i:0{width}d}"
        src = "".join(cell["source"])

        if cell["cell_type"] == "markdown":
            new_src = f"**{tag}**\n\n{src}"
        else:
            stripped = src.lstrip()
            if stripped.startswith("%%"):
                # Cell magic must stay the literal first line. Append the
                # label at the end instead. %%sql bodies are SQL, so use a
                # SQL comment; anything else falls back to a '#' comment.
                first_line = stripped.split("\n", 1)[0]
                comment = "--" if "sql" in first_line.lower() else "#"
                sep = "" if src.endswith("\n") else "\n"
                new_src = f"{src}{sep}{comment} {tag}"
            else:
                new_src = f"# {tag}\n{src}"

        cell["source"] = _as_lines(new_src)

    path.write_text(json.dumps(nb, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{path.name}: labeled {len(cells)} cells (Cell #{'1'.zfill(width)}..#{len(cells)})")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        label_notebook(Path(p))
