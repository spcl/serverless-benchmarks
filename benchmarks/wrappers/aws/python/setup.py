# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
from distutils.core import setup
from glob import glob

setup(
    name='function',
    packages=['function'],
    package_dir={'function': '.'},
    package_data={'function': glob('**', recursive=True)},
)

