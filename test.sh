#!/usr/bin/env bash
set -ev
export PATH="$PWD/test/here/bin:$PATH"
HEREROCKS="python hererocks.py test/here --downloads=test/cache --no-git-cache"

rm -rf test/here
$HEREROCKS -l^ -r^
lua -v
luarocks --version
luarocks make
hererocks-test | grep "5\.3"
$HEREROCKS -l^ -r^ | grep "already installed"

rm -rf test/here
$HEREROCKS -j @v2.1 -r^ | grep "Fetching" | grep "cached"
lua -v
lua -e "require 'jit.bcsave'"
luarocks --version
luarocks make
hererocks-test | grep "2\.1"

rm -rf test/here
$HEREROCKS -l 5.1 --compat=none --no-readline
lua -e "assert(not pcall(string.gfind, '', '.'))"
lua -e "(function(...) assert(arg == nil) end)()"
lua -e "assert(math.mod == nil)"

rm -rf test/here
$HEREROCKS -l 5.3 --compat=none --builds=test/builds
lua -e "assert(module == nil)"

rm -rf test/here
$HEREROCKS -l 5.3 --compat=none --builds=test/builds | grep "Building" | grep "cached"
