#!/usr/bin/env sh
echo "initial: $PATH"

. "test/here/bad (dir) 1/bin/activate_posix"
echo "activate 1: $PATH"

deactivate_lua
echo "deactivate 1: $PATH"

. "test/here/bad (dir) 1/bin/activate_posix"
echo "activate 1 again: $PATH"

. "test/here/bad (dir) 1/bin/activate_posix"
echo "reactivate 1: $PATH"

. "test/here/bad (dir) 2/bin/activate_posix"
echo "activate 2: $PATH"

deactivate_lua
echo "deactivate 2: $PATH"
