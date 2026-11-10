from setuptools import setup, find_packages
from confluence_dump import __version__

setup(
    name="confluence_dump",
    version=__version__,
    url="https://github.com/SomeSunlight/ConfluenceBridge",
    packages=find_packages(),
    install_requires=["beautifulsoup4", "Pillow", "pandoc", "pypandoc", "requests"],
    package_data={"": ["styles/confluence.css", "styles/confluencedefaultpdf.css"]},
    include_package_data=True,
    entry_points={"console_scripts": ["confluencebridge=confluence_dump.__main__:main"]},
)
