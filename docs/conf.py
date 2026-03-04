# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import re
import sys

sys.path.insert(0, os.path.abspath(".."))


def _generate_intro_from_readme():
    """Generate introduction.md from README.md with Sphinx-compatible links.

    README.md uses paths like docs/X.md which are correct relative to the
    repo root, but need to be rewritten for the Sphinx source tree rooted at
    docs/.  This runs at conf.py load time so the file is ready before Sphinx
    starts reading sources.
    """
    conf_dir = os.path.dirname(os.path.abspath(__file__))
    readme_path = os.path.join(conf_dir, "..", "README.md")
    intro_path = os.path.join(conf_dir, "introduction.md")

    with open(readme_path, "r") as f:
        content = f.read()

    # [text](docs/X.md#anchor) -> <a href="X.html#anchor">text</a>
    # Sphinx cannot resolve heading anchors across documents via myst
    # cross-references, so emit a plain HTML href for these cases.
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

    # (docs/X.png) -> (X.png)  – image lives in docs/, the Sphinx source root
    content = re.sub(r"\(docs/([^)]+\.(?:png|jpg|gif|svg|webp))\)", r"(\1)", content)

    with open(intro_path, "w") as f:
        f.write(content)


_generate_intro_from_readme()


def _generate_benchmarks_page():
    """Merge per-benchmark READMEs into docs/benchmarks.md at build time.

    docs/benchmarks.md acts as the template: each "[Details →](../benchmarks/…)"
    link is replaced with the content of that benchmark's README (headings
    shifted by +2 so they nest under the existing ### benchmark headings).
    benchmarks-data READMEs are appended as an "#### Input Data" subsection
    where they exist.  The function is idempotent: if the links have already
    been expanded (e.g. from a previous build) the regex finds nothing and the
    file is left unchanged.
    """
    conf_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.join(conf_dir, "..")
    benchmarks_doc = os.path.join(conf_dir, "benchmarks.md")

    with open(benchmarks_doc, "r") as f:
        content = f.read()

    def read_readme_body(path, heading_offset=2):
        """Return README content with the h1 title stripped and headings shifted."""
        if not os.path.exists(path):
            return ""
        with open(path, "r") as f:
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
        data_readme = os.path.join(repo_root, "benchmarks-data", bench_rel, "README.md")
        if os.path.exists(data_readme):
            with open(data_readme, "r") as f:
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

    with open(benchmarks_doc, "w") as f:
        f.write(content)


_generate_benchmarks_page()

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
]

templates_path = ["_templates"]
exclude_patterns = ["source"]

# -- Autodoc configuration --------------------------------------------------
# Let RST files control documentation generation explicitly to avoid duplicates

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


# -- GFM alert conversion ---------------------------------------------------
# GitHub-flavored Markdown uses `> [!NOTE]` / `> [!WARNING]` alert blocks.
# myst_parser does not recognise this syntax, so we convert them to myst
# `:::{note}` / `:::{warning}` admonitions via the source-read event, which
# fires for every document before parsing.  The source .md files remain valid
# for GitHub rendering; only the Sphinx build sees the converted form.

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


def setup(app):
    app.connect(
        "source-read",
        lambda app, docname, source: source.__setitem__(
            0, _convert_gfm_alerts(source[0])
        ),
    )
