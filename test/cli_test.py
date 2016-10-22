import os
import shutil
import subprocess
import time
import unittest

class TestCLI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.check_call(["coverage", "erase"])

    def setUp(self):
        if os.name == "nt":
            # On Windows tests randomly fail here with errors such as 'can not remove here\bin: directory not empty'.
            # Supposedly this happens because a file in the directory is still open, and on NFS
            # deleting an open file leaves a file in the same directory. Waiting before attempting
            # to remove directories seems to help.
            time.sleep(1)

        for subdir in ["here", "builds"]:
            if os.path.exists(os.path.join("test", subdir)):
                shutil.rmtree(os.path.join("test", subdir))

    def assertSuccess(self, args, expected_output_lines=None, from_prefix=True):
        if from_prefix:
            args[0] = os.path.join("test", "here", "bin", args[0])

            if os.name == "nt" and not os.path.exists(args[0]) and not os.path.exists(args[0] + ".exe"):
                args[0] += ".bat"

        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = process.communicate()[0]

        if process.returncode != 0:
            raise AssertionError("Error running command '{}': code {}, output:\n{}".format(
                " ".join(args), process.returncode, output))

        if expected_output_lines is not None:
            actual_output_lines = output.splitlines()

            for expected_output_line in expected_output_lines:
                expected_output_line = expected_output_line.encode("UTF-8")

                if not any(expected_output_line in actual_output_line for actual_output_line in actual_output_lines):
                    raise AssertionError("Expected to see '{}' in output of command '{}', got output:\n{}".format(
                        expected_output_line, " ".join(args), output))

    def assertHererocksSuccess(self, args, expected_output_lines=None, location="here"):
        self.assertSuccess([
            "coverage", "run", "-a",
            "hererocks.py", os.path.join("test", location)] + args, expected_output_lines, from_prefix=False)

    def test_install_latest_lua_with_latest_luarocks(self):
        self.assertHererocksSuccess(["--lua", "latest", "--luarocks", "latest"])
        self.assertHererocksSuccess(["--show"], ["Programs installed in", "Compat: default"])
        self.assertSuccess(["lua", "-v"], ["Lua 5.3.3"])
        self.assertSuccess(["lua", "-e", "assert(bit32)"])

        self.assertSuccess(["luarocks", "--version"])
        self.assertSuccess(["luarocks", "make", os.path.join("test", "hererocks-test-scm-1.rockspec")])
        self.assertSuccess(["hererocks-test"], ["Lua 5.3"])

        self.assertHererocksSuccess(["--lua", "latest", "--luarocks", "latest"], ["already installed"])
        self.assertHererocksSuccess(["--luarocks", "latest", "--ignore-installed"], ["Fetching", "cached"])

    def test_install_latest_lua_with_luarocks_from_git(self):
        self.assertHererocksSuccess(["--lua", "latest", "--luarocks", "https://github.com/mpeterv/luarocks@master"])

    def test_verbose_install_bleeding_edge_luajit_with_latest_luarocks(self):
        self.assertHererocksSuccess(["--luajit", "@v2.1", "--luarocks", "latest", "--verbose"])
        self.assertSuccess(["lua", "-v"], ["LuaJIT 2.1.0"])
        self.assertSuccess(["lua", "-e", "require 'jit.bcsave'"])

        self.assertSuccess(["luarocks", "--version"])
        self.assertSuccess(["luarocks", "make", os.path.join("test", "hererocks-test-scm-1.rockspec")])
        self.assertSuccess(["hererocks-test"], ["LuaJIT 2.1.0"])

        self.assertHererocksSuccess(["--luajit", "@v2.1", "--luarocks", "latest"], ["already installed"])

    def test_install_lua_5_1_without_compat_without_readline_with_old_luarocks(self):
        self.assertHererocksSuccess(["--lua", "5.1", "--compat", "none", "--no-readline", "--luarocks", "2.0.8"])
        self.assertSuccess(["lua", "-e", "assert(not pcall(string.gfind, '', '.'))"])
        self.assertSuccess(["lua", "-e", "(function(...) assert(arg == nil) end)()"])
        self.assertSuccess(["lua", "-e", "assert(math.mod == nil)"])

        self.assertSuccess(["luarocks", "--version"])
        self.assertSuccess(["luarocks", "make", os.path.join("test", "hererocks-test-scm-1.rockspec")])

    def test_install_lua_5_3_2_with_patches(self):
        self.assertHererocksSuccess(["--lua", "5.3.2", "--patch"])
        self.assertSuccess(["lua", "-e", "assert(coroutine.wrap(string.gmatch('x', '.'))() == 'x')"])

        if os.name == "nt":
            self.assertHererocksSuccess(["--lua", "5.3.2", "--patch", "--target", "vs"])
            self.assertSuccess(["lua", "-e", "assert(coroutine.wrap(string.gmatch('x', '.'))() == 'x')"])

    def test_install_luajit_with_compat_with_apicheck(self):
        self.assertHererocksSuccess(["--luajit", "latest", "--compat", "5.2", "--cflags=-DLUA_USE_APICHECK"])

        if os.name == "nt":
            self.assertHererocksSuccess([
                "--luajit", "latest", "--compat", "5.2", "--cflags=-DLUA_USE_APICHECK", "--target", "vs"])

    def test_install_latest_ravi_with_luarocks_2_3_0(self):
        # luarocks 2.4.0 fails Lua version check on Windows for "Ravi 5.3"
        self.assertHererocksSuccess(["--ravi", "latest", "--luarocks", "2.3.0", "--verbose"])
        self.assertSuccess(["lua", "-v"], ["Ravi 5.3.2"])
        self.assertSuccess(["lua", "-e", "local t: table = {}"])

        self.assertSuccess(["luarocks", "--version"])
        self.assertSuccess(["luarocks", "make", os.path.join("test", "hererocks-test-scm-1.rockspec")])
        self.assertSuccess(["hererocks-test"], ["Ravi 5.3"])

        self.assertHererocksSuccess(["--ravi", "latest", "--luarocks", "2.3.0"], ["already installed"])

    def test_cached_lua_5_2_build(self):
        self.assertHererocksSuccess(
            ["--lua", "5.2", "--builds", os.path.join("test", "builds")],
            ["No patches available for Lua 5.2"])
        self.assertHererocksSuccess(
            ["--lua", "5.2", "--compat", "none", "--builds", os.path.join("test", "builds")],
            ["No patches available for Lua 5.2"])
        self.assertHererocksSuccess(
            ["--lua", "5.2", "--ignore-installed", "--compat", "none", "--builds", os.path.join("test", "builds")],
            ["compat: none) (cached)"])

    def test_install_lua_from_given_git_repo_with_luarocks_from_local_sources(self):
        local_luarocks = os.path.join("test", "luarocks")

        if not os.path.exists(local_luarocks):
            self.assertSuccess([
                "git", "clone", "https://github.com/keplerproject/luarocks",
                "--depth=1", local_luarocks], from_prefix=False)

        self.assertHererocksSuccess(["--lua", "https://github.com/lua/lua@5.1.3-rc3", "--luarocks", local_luarocks])
        self.assertSuccess(["lua", "-v"], ["Lua 5.1.3"])
        self.assertHererocksSuccess(["--show"], [
            "Lua 5.1", "cloned from https://github.com/lua/lua", "from local sources"])

    def test_activate_scripts(self):
        self.assertHererocksSuccess(["--lua", "5.1"], location=os.path.join("here", "bad (dir) 1"))
        self.assertHererocksSuccess(["--lua", "5.2"], location=os.path.join("here", "bad (dir) 2"))
        checker = os.path.join("test", "check_activate." + ("bat" if os.name == "nt" else "sh"))

        path = os.getenv("PATH")
        path1 = os.path.abspath(os.path.join("test", "here", "bad (dir) 1", "bin"))
        path2 = os.path.abspath(os.path.join("test", "here", "bad (dir) 2", "bin"))
        self.assertSuccess([checker], [
            "initial: {}".format(path),
            "activate 1: {}{}{}".format(path1, os.pathsep, path),
            "deactivate 1: {}".format(path),
            "activate 1 again: {}{}{}".format(path1, os.pathsep, path),
            "reactivate 1: {}{}{}".format(path1, os.pathsep, path),
            "activate 2: {}{}{}".format(path2, os.pathsep, path),
            "deactivate 2: {}".format(path)
        ], from_prefix=False)
