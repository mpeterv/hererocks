#!/usr/bin/env bash
echo "initial: $PATH"

source "test/here/bad (dir) 1/bin/activate"
echo "activate 1: $PATH"

deactivate-lua
echo "deactivate 1: $PATH"

source "test/here/bad (dir) 1/bin/activate"
echo "activate 1 again: $PATH"

source "test/here/bad (dir) 1/bin/activate"
echo "reactivate 1: $PATH"

source "test/here/bad (dir) 2/bin/activate"
echo "activate 2: $PATH"

deactivate-lua
echo "deactivate 2: $PATH"
