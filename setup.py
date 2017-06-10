import codecs
import os
import setuptools

here = os.path.abspath(os.path.dirname(__file__))
readme = codecs.open(os.path.join(here, "README.rst"), encoding="UTF-8")
long_description = readme.read()
readme.close()

setuptools.setup(
    name="hererocks",
    version="0.16.0",
    description="Tool for installing Lua and LuaRocks locally",
    long_description=long_description,
    keywords="lua",
    url="https://github.com/mpeterv/hererocks",
    author="Peter Melnichenko",
    author_email="mpeterval@gmail.com",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.0",
        "Programming Language :: Python :: 3.1",
        "Programming Language :: Python :: 3.2",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6"
    ],
    py_modules=["hererocks"],
    entry_points={
        "console_scripts": [
            "hererocks=hererocks:main"
        ]
    }
)
