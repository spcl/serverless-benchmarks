#!/bin/bash

##
## Converts the README from Markdown syntax to reStructuredText using Pandoc
##

if [ ! -x /usr/share/pandoc ] ; then
    echo "Pandoc is required to convert the README to reStructuredText"
    exit 1
fi

pandoc -f markdown -t rst -o README.rst README.md
