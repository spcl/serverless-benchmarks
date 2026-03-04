# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import re
import sys

# conf_dir = docs/source/
# docs_dir  = docs/
# repo_root = repository root (parent of docs/)
conf_dir = os.path.dirname(os.path.abspath(__file__))
docs_dir = os.path.abspath(os.path.join(conf_dir, ".."))
repo_root = os.path.abspath(os.path.join(conf_dir, "../.."))

sys.path.insert(0, repo_root)

project = "sebs"
copyright = "2024, Marcin Copik"
author = "Marcin Copik"
release = "1.2"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.napoleon",
    "sphinx.ext.autodoc",
    "sphinx.ext.viewcode",
    "myst_parser",
    "sphinxcontrib.mermaid",
]

templates_path = ["_templates"]
exclude_patterns = []

# Suppress duplicate object warnings
suppress_warnings = ["autosectionlabel.*"]

# -- MyST configuration -----------------------------------------------------
myst_enable_extensions = ["colon_fence"]
myst_heading_anchors = 3  # generate anchors for h1–h3, needed for #section links

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]
html_theme_options = {
    # Limit sidebar to caption → page title only; prevents the RTD theme from
    # expanding each page's internal headings (h2/h3) into the sidebar nav.
    "navigation_depth": 2,
}


# ---------------------------------------------------------------------------
# GFM alert conversion
# ---------------------------------------------------------------------------
# GitHub-flavored Markdown uses `> [!NOTE]` / `> [!WARNING]` alert blocks.
# myst_parser does not recognise this syntax, so we convert them to myst
# `:::{note}` / `:::{warning}` admonitions.  The conversion happens inside
# the source-read event so the source .md files are never modified.

_GFM_ALERT = re.compile(
    r"> \[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\n((?:> [^\n]*\n?)*)",
    re.MULTILINE | re.IGNORECASE,
)


def _convert_gfm_alerts(text):
    def _replace(m):
        kind = m.group(1).lower()
        body = re.sub(r"^> ?", "", m.group(2), flags=re.MULTILINE).strip()
        return f":::{{{kind}}}\n{body}\n:::\n"

    return _GFM_ALERT.sub(_replace, text)


# ---------------------------------------------------------------------------
# Content loaders – run inside source-read, never write to user files
# ---------------------------------------------------------------------------


def _load_intro():
    """Load README.md and rewrite docs/ links for Sphinx in memory."""
    readme_path = os.path.join(repo_root, "README.md")
    with open(readme_path) as f:
        content = f.read()

    # [text](docs/X.md#anchor) -> <a href="X.html#anchor">text</a>
    # Sphinx cannot resolve heading anchors across documents via myst
    # cross-references, so emit plain HTML hrefs for anchored links.
    def fix_anchored_link(m):
        text, name, anchor = m.group(1), m.group(2), m.group(3)
        return f'<a href="{name}.html#{anchor}">{text}</a>'

    content = re.sub(
        r"\[([^\]]+)\]\(docs/([^/)#]+)\.md#([^)]+)\)",
        fix_anchored_link,
        content,
    )

    # (docs/X.md) -> (X)  – plain Sphinx cross-reference
    content = re.sub(r"\(docs/([^/)#]+)\.md\)", r"(\1)", content)

    # (docs/X.png) -> (../X.png)
    # Images live in docs/ which is one level above docs/source/ (our Sphinx
    # source root), so we need to go up one directory from source root.
    content = re.sub(
        r"\(docs/([^)]+\.(?:png|jpg|gif|svg|webp))\)", r"(../\1)", content
    )

    return _convert_gfm_alerts(content)


def _load_benchmarks():
    """Load docs/benchmarks.md and inline per-benchmark READMEs in memory."""
    benchmarks_doc = os.path.join(docs_dir, "benchmarks.md")
    with open(benchmarks_doc) as f:
        content = f.read()

    # Promote ## to # if the file has no top-level heading yet
    if not re.match(r"^# ", content):
        content = re.sub(r"^## ", "# ", content, count=1)

    def read_readme_body(path, heading_offset=2):
        """Return README content with the h1 title stripped and headings shifted."""
        if not os.path.exists(path):
            return ""
        with open(path) as f:
            text = f.read()
        # Drop the leading h1 title line (and any blank lines that follow it)
        text = re.sub(r"^# [^\n]*\n+", "", text)
        # Shift remaining headings: ## → ####, ### → #####, etc.
        text = re.sub(
            r"^(#{1,6})([ \t])",
            lambda m: "#" * (len(m.group(1)) + heading_offset) + m.group(2),
            text,
            flags=re.MULTILINE,
        )
        return text.strip()

    def replace_details_link(m):
        bench_rel = m.group(1)  # e.g. "100.webapps/110.dynamic-html"
        readme_path = os.path.join(repo_root, "benchmarks", bench_rel, "README.md")

        parts = []

        body = read_readme_body(readme_path)
        if body:
            parts.append(body)

        # Include benchmarks-data attribution if present
        data_readme = os.path.join(
            repo_root, "benchmarks-data", bench_rel, "README.md"
        )
        if os.path.exists(data_readme):
            with open(data_readme) as f:
                data_body = f.read().strip()
            if data_body:
                parts.append("#### Input Data\n\n" + data_body)

        return "\n\n" + "\n\n".join(parts) if parts else ""

    # Replace every [Details →](../benchmarks/PATH/README.md) with inlined content
    content = re.sub(
        r"\[Details →\]\(\.\./benchmarks/([^)]+)/README\.md\)",
        replace_details_link,
        content,
    )

    # Fix cross-page anchored links: [text](../README.md#anchor) → HTML href
    content = re.sub(
        r"\[([^\]]+)\]\(\.\./README\.md#([^)]+)\)",
        lambda m: f'<a href="introduction.html#{m.group(2)}">{m.group(1)}</a>',
        content,
    )

    return _convert_gfm_alerts(content)


# Pages whose content is loaded from docs/*.md one level above docs/source/
_DOC_PAGES = frozenset(
    {"usage", "build", "design", "experiments", "modularity", "platforms", "storage"}
)


def _load_doc_page(docname):
    """Load docs/<docname>.md and apply GFM alert conversion."""
    path = os.path.join(docs_dir, docname + ".md")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        content = f.read()
    return _convert_gfm_alerts(content)


# ---------------------------------------------------------------------------
# source-read event handler
# ---------------------------------------------------------------------------


def _on_source_read(app, docname, source):
    """Replace stub content with real content loaded and transformed in memory."""
    if docname == "introduction":
        source[0] = _load_intro()
    elif docname == "benchmarks":
        source[0] = _load_benchmarks()
    elif docname in _DOC_PAGES:
        content = _load_doc_page(docname)
        if content is not None:
            source[0] = content
    else:
        # Apply GFM alert conversion to all other docs (e.g. api/*.rst are not
        # Markdown so they won't match, but this is a safe no-op for them)
        source[0] = _convert_gfm_alerts(source[0])


def setup(app):
    app.connect("source-read", _on_source_read)
