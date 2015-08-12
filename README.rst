hererocks
=========

``hererocks`` is a single file Python script for installing `Lua <http://http://www.lua.org/>`_ and `LuaRocks <https://luarocks.org/>`_, its package manager, into a local directory.

::

   $ hererocks here --lua=5.2.3 --luarocks=2.2.2
   $ here/bin/lua -v
   Lua 5.2.3  Copyright (C) 1994-2013 Lua.org, PUC-Rio
   $ here/bin/luarocks --version
   here/bin/luarocks 2.2.2
   LuaRocks main command-line interface
   $ here/bin/luarocks install busted
   $ here/bin/busted --version
   2.0.rc10-0

WIP
