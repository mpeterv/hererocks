hererocks
=========

.. image:: https://travis-ci.org/mpeterv/hererocks.svg?branch=master
  :target: https://travis-ci.org/mpeterv/hererocks

``hererocks`` is a single file Python script for installing `Lua <http://http://www.lua.org/>`_ (or `LuaJIT <http://luajit.org/>`_) and `LuaRocks <https://luarocks.org/>`_, its package manager, into a local directory. It configures Lua to only see packages installed by that bundled version of LuaRocks, so that the installation is isolated.

Installation
------------

Using `pip <https://pypi.python.org/pypi/pip>`_: run ``pip install hererocks``, using ``sudo`` if necessary.

Manually: download hererocks with ``wget https://raw.githubusercontent.com/mpeterv/hererocks/latest/hererocks.py``, then use ``python hererocks.py ...`` to run it.

Usage
-----

Installation location
^^^^^^^^^^^^^^^^^^^^^

The first argument of ``hererocks`` command should be path to the directory where Lua and/or LuaRocks should be installed. If it does not exist, it will be created.

If installation directory already has Lua installed, a new version of Lua or LuaRocks can be installed over it as a seamless upgrade (packages installed with LuaRocks will keep working) provided new and old Lua minor versions are same. E.g. Lua 5.1.5 and LuaJIT 2.1 can be installed over Lua 5.1.1, but not over Lua 5.2.1. Otherwise, when installing an incompatible Lua version, the installation directory should be removed prior to running ``hererocks``. If ``hererocks`` detects that it has already installed requested version of Lua or LuaRocks into the directory, it will skip installation for that program, unless ``--ignore-installed/-i`` is used.

After installation Lua and LuaRocks binaries will be in the ``bin`` subdirectory of the installation directory. Scripts installed using LuaRocks will also turn up there. Lua binary is always named ``lua``, even if it's LuaJIT under the hood, and LuaRocks binary is named ``luarocks`` as usual.

Version selection
^^^^^^^^^^^^^^^^^

``--lua/-l``, ``--luajit/-j`` and ``--luarocks/-r`` options should be used to select versions of programs to install. There are three ways to specify how to fetch the sources:

* Using version number, such as ``5.1.5``. If patch or minor versions are left out the latest possible version will be used, e.g. for Lua ``5.2`` is currently equivalent to ``5.2.4`` and for LuaJIT ``2.1`` is same as ``2.1.0-beta2``. ``^`` can be used to select the latest stable version. ``hererocks`` will fetch and unpack sources of the selected version from corresponding downloads location, verifying their SHA256 checksum.
* Using git URI plus reference to checkout, separated by ``@``. Default reference is ``master``, and there are default git URIs for Lua (https://github.com/lua/lua), LuaJIT (https://github.com/luajit/luajit) and LuaRocks (https://github.com/keplerproject/luarocks). For instance, ``--luajit @458a40b`` installs from a commit at the LuaJIT git repository and ``--luajit @`` installs from its master branch. ``hererocks`` will use ``git`` command for cloning.
* Using path to a local directory.

Compatibility flags
^^^^^^^^^^^^^^^^^^^

Lua and LuaJIT have some flags that add compatibility with other Lua versions. Lua 5.1 has several options for compatibility with Lua 5.0 (on by default), Lua 5.2 has 5.1 compatibility flag (on by default), Lua 5.3 - both 5.1 and 5.2 compatibility flags (only 5.2 compatibility is on by default), and LuaJIT has 5.2 flag (off by default). ``hererocks`` can change these flags before building when using ``--compat`` option. Possible arguments are ``default``, ``none``, ``all``, ``5.1`` and ``5.2``.

Installing standard PUC-Rio Lua
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Available versions: 5.1 - 5.1.5, 5.2.0 - 5.2.4, 5.3.0 - 5.3.2.

Use ``5.1.0`` to install Lua ``5.1`` which was released without patch version for some reason.

When building Lua, ``hererocks`` tries to emulate a sensible ``make`` target. The default can be seen in the help message printed by ``hererocks --help``. To select another target use ``--target`` option. To build without readline library use ``--no-readline`` option.

Installing LuaJIT
^^^^^^^^^^^^^^^^^

Available versions: 2.0.0 - 2.0.4, 2.1.0-beta1 - 2.1.0-beta2.

Installing LuaRocks
^^^^^^^^^^^^^^^^^^^

Available versions: 2.0.8 - 2.0.12, 2.1.0 - 2.1.2, 2.2.0 - 2.2.2, 2.3.0, 3 (installs from ``luarocks-3`` branch of the LuaRocks git repository).

Version 2.0.8 does not support Lua 5.2. Versions 2.1.0 - 2.1.2 do not support Lua 5.3.

Using hererocks to set up automated testing
-------------------------------------------

Popular continuous integration services such as `Travis-CI <https://travis-ci.org/>`_ and `Drone.io <https://drone.io/>`_ do not support Lua out of the box. That can be solved using hererocks in just a couple of lines. Here is an example of Travis-CI configuration file (``.travis.yml``) using hererocks to install a rock and run `Busted <http://olivinelabs.com/busted/>`_ test suite under Lua 5.1, 5.2, 5.3, LuaJIT 2.0 and 2.1:

.. code-block:: yaml

  language: python # Need python environment for pip
  sudo: false # Use container-based infrastructure

  env:
    - LUA="lua 5.1"
    - LUA="lua 5.2"
    - LUA="lua 5.3"
    - LUA="luajit 2.0"
    - LUA="luajit 2.1"

  before_install:
    - pip install hererocks
    - hererocks here -r^ --$LUA # Install latest LuaRocks version
                                # plus the Lua version for this build job
                                # into 'here' subdirectory
    - export PATH=$PATH:$PWD/here/bin # Add directory with all installed binaries to PATH
    - luarocks install busted

  install:
    - luarocks make # Install the rock, assuming there is a rockspec
                    # in the root of the repository

  script:
    - busted spec # Run the test suite, assuming tests are in the 'spec' subdirectory
