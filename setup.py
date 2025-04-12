from setuptools import setup, find_packages
from setuptools.command.install import install

class PostInstallCommand(install):
    def run(self):
        install.run(self)
        subprocess.call(["python", "scripts/init_shell.py"])

setup(
    name="pload",
    version="0.1.0",
    description="A simple command line tool for python virtual env management.",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="Yunming Hu",
    author_email="hugonelsonm3@gmail.com",
    license="MIT",
    python_requires=">=3.8",
    install_requires=[
        "colorama",
        "argcomplete",
    ],
    entry_points={
        "console_scripts": [
            "pload = src.cli:main",
        ],
    },
    packages=find_packages(),
    # cmdclass={
    #     "install": PostInstallCommand
    # },
)
