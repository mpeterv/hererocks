@echo off

echo "initial: %PATH%"

call "test\here\bad (dir) 1\bin\activate"
echo "activate 1: %PATH%"

call deactivate-lua
echo "deactivate 1: %PATH%"

call "test\here\bad (dir) 1\bin\activate"
echo "activate 1 again: %PATH%"

call "test\here\bad (dir) 1\bin\activate"
echo "reactivate 1: %PATH%"

call "test\here\bad (dir) 2\bin\activate"
echo "activate 2: %PATH%"

call deactivate-lua
echo "deactivate 2: %PATH%"
