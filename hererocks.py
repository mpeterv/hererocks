#!/usr/bin/env python

"""A tool for installing Lua and LuaRocks locally."""

from __future__ import print_function

import argparse
import os
import re
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile

try:
    from urllib import urlretrieve
except ImportError:
    from urllib.request import urlretrieve

hererocks_version = "Hererocks 0.0.3"
__all__ = ["main"]

platform_to_lua_target = {
    "linux": "linux",
    "win": "mingw",
    "darwin": "macosx",
    "freebsd": "freebsd"
}

def get_lua_target():
    for platform, lua_target in platform_to_lua_target.items():
        if sys.platform.startswith(platform):
            return lua_target

    return "posix" if os.name == "posix" else "generic"

if os.name == "nt":
    cache_root = os.getenv("LOCALAPPDATA") or os.path.join(
        os.getenv("USERPROFILE"), "Local Settings", "Application Data")
    cache_path = os.path.join(cache_root, "HereRocks", "Cache")
else:
    cache_path = os.path.join(os.getenv("HOME"), ".cache", "hererocks")

def quote(command_arg):
    return "'" + command_arg.replace("'", "'\"'\"'") + "'"

def space_cat(*args):
    return " ".join(filter(None, args))

def run_command(verbose, *args):
    command = space_cat(*args)
    runner = subprocess.check_output

    if verbose:
        print("Running " + command)
        runner = subprocess.check_call

    try:
        runner(command, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as exception:
        if not verbose:
            sys.stdout.write(exception.output)

        sys.exit("Error: got exitcode {} from command {}\n".format(
            exception.returncode, command))

lua_versions = ([
    "5.1", "5.1.1", "5.1.2", "5.1.3", "5.1.4", "5.1.5",
    "5.2.0", "5.2.1", "5.2.2", "5.2.3", "5.2.4",
    "5.3.0", "5.3.1"
], {
    "5": "5.3.1",
    "5.1": "5.1.5",
    "5.1.0": "5.1",
    "5.2": "5.2.4",
    "5.3": "5.3.1",
    "^": "5.3.1"
}, "http://www.lua.org/ftp", "lua", None)

luajit_versions = ([
    "2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.0.4"
], {
    "2": "2.0.4",
    "2.0": "2.0.4",
    "2.1": "@v2.1",
    "^": "2.0.4"
}, "http://luajit.org/download", "LuaJIT", "https://github.com/luajit/luajit")

luarocks_versions = ([
    "2.1.0", "2.1.1", "2.1.2",
    "2.2.0", "2.2.1", "2.2.2"
], {
    "2": "2.2.2",
    "2.1": "2.1.2",
    "2.2": "2.2.2",
    "3": "@luarocks-3",
    "^": "2.2.2"
}, "http://keplerproject.github.io/luarocks/releases", "luarocks",
    "https://github.com/keplerproject/luarocks"
)

clever_http_git_whitelist = [
    "http://github.com/", "https://github.com/",
    "http://bitbucket.com/", "https://bitbucket.com/"
]

def git_clone_command(repo, ref):
    # Http(s) transport may be dumb and not understand --depth.
    if repo.startswith("http://") or repo.startswith("https://"):
        if not any(map(repo.startswith, clever_http_git_whitelist)):
            return "git clone"

    # Have to clone whole repo to get a specific commit.
    if all(c in string.hexdigits for c in ref):
        return "git clone"

    return "git clone --depth=1"

def cached_archive_name(name, version):
    return os.path.join(cache_path, name + version)

def capitalize(s):
    return s[0].upper() + s[1:]

def fetch(versions, version, verbose, temp_dir):
    raw_versions, translations, downloads, name, repo = versions

    if version in translations:
        version = translations[version]

    if version in raw_versions:
        if not os.path.exists(cache_path):
            os.makedirs(cache_path)

        archive_name = cached_archive_name(name, version)
        url = downloads + "/" + name + "-" + version + ".tar.gz"
        message = "Fetching {} from {}".format(capitalize(name), url)

        if not os.path.exists(archive_name):
            print(message)
            urlretrieve(url, archive_name)
        else:
            print(message + " (cached)")

        archive = tarfile.open(archive_name, "r:gz")
        archive.extractall(temp_dir)
        archive.close()
        result_dir = os.path.join(temp_dir, name + "-" + version)
        os.chdir(result_dir)
        return result_dir

    if version.startswith("@"):
        if not repo:
            sys.exit("Error: no default git repo for standard Lua ")

        ref = version[1:] or "master"
    elif "@" in version:
        repo, _, ref = version.partition("@")
    else:
        if not os.path.exists(version):
            sys.exit("Error: bad {} version {}".format(capitalize(name), version))

        print("Using {} from {}".format(capitalize(name), version))
        result_dir = os.path.join(temp_dir, name)
        shutil.copytree(version, result_dir, ignore=lambda _, __: {".git"})
        os.chdir(result_dir)
        return result_dir

    result_dir = os.path.join(temp_dir, name)
    print("Cloning {} from {} @{}".format(capitalize(name), repo, ref))
    run_command(verbose, git_clone_command(repo, ref), quote(repo), quote(result_dir))
    os.chdir(result_dir)

    if ref != "master":
        run_command(verbose, "git checkout", quote(ref))

    return result_dir

lua_version_regexp = re.compile("^\\s*#define\\s+LUA_VERSION_NUM\\s+50(\d)\\s*$")

def detect_lua_version(lua_path):
    lua_h = open(os.path.join(lua_path, "src", "lua.h"))

    for line in lua_h:
        match = lua_version_regexp.match(line)

        if match:
            return "5." + match.group(1)

def patch_default_paths(lua_path, package_path, package_cpath):
    package_path = package_path.replace("\\", "\\\\")
    package_cpath = package_cpath.replace("\\", "\\\\")

    luaconf_h = open(os.path.join(lua_path, "src", "luaconf.h"), "rb")
    luaconf_src = luaconf_h.read()
    luaconf_h.close()

    body, _, rest = luaconf_src.rpartition(b"#endif")
    defines = os.linesep.join([
        "#undef LUA_PATH_DEFAULT",
        "#undef LUA_CPATH_DEFAULT",
        "#define LUA_PATH_DEFAULT \"{}\"".format(package_path),
        "#define LUA_CPATH_DEFAULT \"{}\"".format(package_cpath),
        "#endif"
    ])

    luaconf_h = open(os.path.join(lua_path, "src", "luaconf.h"), "wb")
    luaconf_h.write(body)
    luaconf_h.write(defines.encode("UTF-8"))
    luaconf_h.write(rest)
    luaconf_h.close()

def patch_build_option(lua_path, old, new):
    makefile = open(os.path.join(lua_path, "src", "Makefile"), "rb")
    makefile_src = makefile.read()
    makefile.close()
    makefile_src = makefile_src.replace(old.encode("UTF-8"), new.encode("UTF-8"), 1)
    makefile = open(os.path.join(lua_path, "src", "Makefile"), "wb")
    makefile.write(makefile_src)
    makefile.close()

def get_luarocks_paths(target_dir, nominal_version):
    local_paths_first = nominal_version == "5.1"

    module_path = os.path.join(target_dir, "share", "lua", nominal_version)
    module_path_parts = [
        os.path.join(module_path, "?.lua"),
        os.path.join(module_path, "?", "init.lua")
    ]
    module_path_parts.insert(0 if local_paths_first else 2, os.path.join(".", "?.lua"))
    package_path = ";".join(module_path_parts)

    cmodule_path = os.path.join(target_dir, "lib", "lua", nominal_version)
    so_extension = ".dll" if os.name == "nt" else ".so"
    cmodule_path_parts = [
        os.path.join(cmodule_path, "?" + so_extension),
        os.path.join(cmodule_path, "loadall" + so_extension)
    ]
    cmodule_path_parts.insert(0 if local_paths_first else 2, os.path.join(".", "?" + so_extension))
    package_cpath = ";".join(cmodule_path_parts)

    return package_path, package_cpath

def apply_luajit_compat(lua_path, compat):
    if compat != "default":
        if compat in ["all", "5.2"]:
            patch_build_option(lua_path,
                               "#XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT",
                               "XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT")

def check_subdir(path, subdir):
    path = os.path.join(path, subdir)

    if not os.path.exists(path):
        os.mkdir(path)

    return path

def move_files(path, *files):
    for src in files:
        if src is not None:
            dst = os.path.join(path, os.path.basename(src))

            # On Windows os.rename will fail if destination exists.
            if os.path.exists(dst):
                os.remove(dst)

            os.rename(src, dst)

class LuaBuilder(object):
    def __init__(self, target, lua, compat):
        self.target = target
        self.lua = lua
        self.compat = compat
        self.set_params()

    def get_compat_cflags(self):
        if self.lua == "5.1":
            return ""
        elif self.lua == "5.2":
            if self.compat in ["none", "5.2"]:
                return ""
            else:
                return "-DLUA_COMPAT_ALL"
        elif self.lua == "5.3":
            if self.compat == "none":
                return ""
            elif self.compat == "all":
                return "-DLUA_COMPAT_5_1 -DLUA_COMPAT_5_2"
            elif self.compat == "5.1":
                return "-DLUA_COMPAT_5_1"
            else:
                return "-DLUA_COMPAT_5_2"

    def set_params(self):
        if self.lua == "5.3":
            self.cc = "gcc -std=gnu99"
        else:
            self.cc = "gcc"

        self.ar = "ar rcu"
        self.ranlib = "ranlib"
        self.arch_file = "liblua.a"
        self.lua_file = "lua"
        self.luac_file = "luac"
        self.scflags = None
        self.dll_file = None

        if self.target == "linux" or self.target == "freebsd":
            self.cflags = "-DLUA_USE_LINUX"

            if self.target == "linux":
                if self.lua == "5.1":
                    self.lflags = "-Wl,-E -ldl -lreadline -lhistory -lncurses"
                else:
                    self.lflags = "-Wl,-E -ldl -lreadline"
            else:
                self.lflags = "-Wl,-E -lreadline"
        elif self.target == "macosx":
            self.cflags = "-DLUA_USE_MACOSX -DLUA_USE_READLINE"
            self.lflags = "-lreadline"
            self.cc = "cc"
        else:
            self.lflags = ""

            if self.target == "mingw":
                self.arch_file = "liblua5" + self.lua[2] + ".a"
                self.lua_file += ".exe"
                self.luac_file += ".exe"
                self.cflags = "-DLUA_BUILD_AS_DLL"
                self.scflags = ""
            elif self.target == "posix":
                self.cflags = "-DLUA_USE_POSIX"
            else:
                self.cflags = ""

        if self.scflags is None:
            self.scflags = self.cflags

        compat_cflags = self.get_compat_cflags()
        self.cflags = space_cat("-O2 -Wall -Wextra", self.cflags, compat_cflags)
        self.scflags = space_cat("-O2 -Wall -Wextra", self.scflags, compat_cflags)
        self.lflags = space_cat(self.lflags, "-lm")

    def get_compile_cmd(self, src_file, obj_file, static):
        return space_cat(self.cc, self.scflags if static else self.cflags, "-c -o", obj_file, src_file)

    def get_arch_cmd(self, obj_files, arch_file):
        return space_cat(self.ar, arch_file, *obj_files)

    def get_index_cmd(self, arch_file):
        return space_cat(self.ranlib, arch_file)

    def get_link_cmd(self, obj_files, arch_file, exec_file):
        return space_cat(self.cc, space_cat(*obj_files), arch_file, self.lflags, "-o", exec_file)

    def compile_bases(self, bases, verbose, static=False):
        obj_files = []

        for base in sorted(bases):
            obj_file = base + ".o"
            run_command(verbose, self.get_compile_cmd(base + ".c", obj_file, static))
            obj_files.append(obj_file)

        return obj_files

    def build(self, verbose):
        os.chdir("src")

        lib_bases = []
        lua_bases = []
        luac_bases = []

        for path in os.listdir("."):
            base, ext = os.path.splitext(path)

            if ext == ".c":
                bases = lua_bases if base == "lua" else luac_bases if base in ["luac", "print"] else lib_bases
                bases.append(base)

        lib_obj_files = self.compile_bases(lib_bases, verbose)
        run_command(verbose, self.get_arch_cmd(lib_obj_files, self.arch_file))
        run_command(verbose, self.get_index_cmd(self.arch_file))

        luac_obj_files = self.compile_bases(luac_bases, verbose, True)
        run_command(verbose, self.get_link_cmd(luac_obj_files, self.arch_file, self.luac_file))

        if self.target == "mingw":
            orig_arch_file = self.arch_file
            self.ar = self.cc + " -shared -o"
            self.ranlib = "strip --strip-unneeded"
            self.arch_file = "lua5" + self.lua[2] + ".dll"
            self.lflags = "-s"
            run_command(verbose, self.get_arch_cmd(lib_obj_files, self.arch_file))
            run_command(verbose, self.get_index_cmd(self.arch_file))
            self.arch_file, self.dll_file = orig_arch_file, self.arch_file

        lua_obj_files = self.compile_bases(lua_bases, verbose)
        run_command(verbose, self.get_link_cmd(lua_obj_files, self.arch_file, self.lua_file))

    def install(self, target_dir):
        move_files(check_subdir(target_dir, "bin"), self.lua_file, self.luac_file, self.dll_file)

        lua_hpp = "lua.hpp"

        if not os.path.exists(lua_hpp):
            lua_hpp = "../etc/lua.hpp"

        move_files(check_subdir(target_dir, "include"), "lua.h", "luaconf.h", "lualib.h", "lauxlib.h", lua_hpp)
        move_files(check_subdir(target_dir, "lib"), self.arch_file)

def install_lua(target_dir, lua_version, is_luajit, compat, verbose, temp_dir):
    lua_path = fetch(luajit_versions if is_luajit else lua_versions, lua_version, verbose, temp_dir)

    print("Building " + ("LuaJIT" if is_luajit else "Lua"))
    nominal_version = detect_lua_version(lua_path)
    package_path, package_cpath = get_luarocks_paths(target_dir, nominal_version)
    patch_default_paths(lua_path, package_path, package_cpath)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    if is_luajit:
        apply_luajit_compat(lua_path, compat)
        run_command(verbose, "make", "PREFIX=" + quote(target_dir))
        print("Installing LuaJIT")
        run_command(verbose, "make install", "PREFIX=" + quote(target_dir),
                    "INSTALL_TNAME=lua", "INSTALL_TSYM=luajit_symlink",
                    "INSTALL_INC=" + quote(os.path.join(target_dir, "include")))

        if os.path.exists(os.path.join(target_dir, "bin", "luajit_symlink")):
            os.remove(os.path.join(target_dir, "bin", "luajit_symlink"))
    else:
        builder = LuaBuilder(get_lua_target(), nominal_version, compat)
        builder.build(verbose)
        print("Installing Lua")
        builder.install(target_dir)

def install_luarocks(target_dir, luarocks_version, verbose, temp_dir):
    fetch(luarocks_versions, luarocks_version, verbose, temp_dir)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    print("Building LuaRocks")
    run_command(verbose, "./configure", "--prefix=" + quote(target_dir),
                "--with-lua=" + quote(target_dir), "--force-config")
    run_command(verbose, "make build")
    print("Installing LuaRocks")
    run_command(verbose, "make install")

def main():
    parser = argparse.ArgumentParser(
        description=hererocks_version + " a tool for installing Lua and/or LuaRocks locally.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, add_help=False)
    parser.add_argument(
        "location", help="Path to directory in which Lua and/or LuaRocks will be installed. "
        "Their binaries will be found in its 'bin' subdirectory. "
        "Scripts from modules installed using LuaRocks will also turn up there. "
        "If an incompatible version of Lua is already installed there it should be"
        "removed before installing the new one.")
    parser.add_argument(
        "-l", "--lua", help="Version of standard PUC-Rio Lua to install. "
        "Version can be specified as a version number, e.g. 5.2 or 5.3.1. "
        "Versions 5.1.0 - 5.3.1 are supported, "
        "'^' can be used to install the latest stable version. "
        "If the argument contains '@', sources will be downloaded "
        "from a git repo using URI before '@' and using part after '@' as git reference "
        "to checkout, 'master' by default. "
        "The argument can also be a path to local directory.")
    parser.add_argument(
        "-j", "--luajit", help="Version of LuaJIT to install. "
        "Version can be specified in the same way as for standard Lua."
        "Versions 2.0.0 - 2.1 are supported. "
        "When installing from the LuaJIT main git repo its URI can be left out, "
        "so that '@458a40b' installs from a commit and '@' installs from the master branch.")
    parser.add_argument(
        "-r", "--luarocks", help="Version of LuaRocks to install. "
        "As with Lua, a version number (in range 2.1.0 - 2.2.2), git URI with reference or "
        "a local path can be used. '3' can be used as a version number and installs from "
        "the 'luarocks-3' branch of the standard LuaRocks git repo. "
        "Note that LuaRocks 2.1.x does not support Lua 5.3.")
    parser.add_argument(
        "-c", "--compat", default="default", choices=["default", "none", "all", "5.1", "5.2"],
        help="Select compatibility flags for Lua.")
    parser.add_argument(
        "--verbose", default=False, action="store_true",
        help="Show executed commands and their output.")
    parser.add_argument("-v", "--version", help="Show program's version number and exit.",
                        action="version", version=hererocks_version)
    parser.add_argument("-h", "--help", help="Show this help message and exit.", action="help")

    args = parser.parse_args()
    if not args.lua and not args.luajit and not args.luarocks:
        parser.error("nothing to install")

    if args.lua and args.luajit:
        parser.error("can't install both PUC-Rio Lua and LuaJIT")

    abs_location = os.path.abspath(args.location)
    start_dir = os.getcwd()
    temp_dir = tempfile.mkdtemp()

    if args.lua or args.luajit:
        install_lua(abs_location, args.lua or args.luajit, args.luajit,
                    args.compat, args.verbose, temp_dir)
        os.chdir(start_dir)

    if args.luarocks:
        install_luarocks(abs_location, args.luarocks, args.verbose, temp_dir)
        os.chdir(start_dir)

    shutil.rmtree(temp_dir)
    print("Done.")

if __name__ == "__main__":
    main()
