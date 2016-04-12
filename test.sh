#!/usr/bin/env bash
set -ev
export PATH="$PWD/test/here/bin:$PATH"
HEREROCKS="python hererocks.py test/here --downloads=test/cache --no-git-cache --verbose"

rm -rf test/here
$HEREROCKS -l^ -r^
lua -v
lua -e "assert(bit32)"
lua -e "assert(coroutine.wrap(string.gmatch('x', '.'))() ~= 'x')"

luarocks --version
luarocks make
hererocks-test | tee test/tmp && grep "5\.3" test/tmp
$HEREROCKS -l^ -r^ | tee test/tmp && grep "already installed" test/tmp

rm -rf test/here
$HEREROCKS -j @v2.1 -r^ | tee test/tmp && grep "Fetching" test/tmp | grep "cached"
lua -v
lua -e "require 'jit.bcsave'"
luarocks --version
luarocks make
hererocks-test | tee test/tmp && grep "2\.1" test/tmp

rm -rf test/here
$HEREROCKS -l 5.1 --compat=none --no-readline
lua -e "assert(not pcall(string.gfind, '', '.'))"
lua -e "(function(...) assert(arg == nil) end)()"
lua -e "assert(math.mod == nil)"

rm -rf test/here
rm -rf test/builds
$HEREROCKS -l 5.3 --compat=none --patch --builds=test/builds
lua -e "assert(not bit32)"
lua -e "assert(coroutine.wrap(string.gmatch('x', '.'))() == 'x')"

rm -rf test/here
$HEREROCKS -l 5.3 --compat=none --patch --builds=test/builds | tee test/tmp && grep "Building" test/tmp | grep "cached"
$HEREROCKS --show
