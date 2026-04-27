from distutils.core import setup
from glob import glob

setup(
    name='function',
    packages=['function'],
    package_dir={'function': '.'},
    package_data={'function': glob('**', recursive=True)},
)
