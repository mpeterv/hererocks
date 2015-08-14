#!/usr/bin/env python

"""A tool for installing Lua and LuaRocks locally."""

from __future__ import print_function

import argparse
import os
import re
import shutil
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

def get_default_lua_target():
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

def run_command(*args):
    command = " ".join(args)

    try:
        subprocess.check_output(command, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as exception:
        sys.exit("Error: got exitcode {} from command {}\nOutput:\n{}".format(
            exception.returncode, command, exception.output))

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
}, "http://luajit.org/download", "LuaJIT", "http://luajit.org/git/luajit-2.0.git")

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
    "https://github.com/keplerproject/luarocks.git"
)

clever_http_git_whitelist = [
    "http://github.com/", "https://github.com/",
    "http://bitbucket.com/", "https://bitbucket.com/"
]

def git_clone_command(repo):
    # Http(s) transport may be dumb and not understand --depth.
    if repo.startswith("http://") or repo.startswith("https://"):
        if not any(map(repo.startswith, clever_http_git_whitelist)):
            return "git clone"

    return "git clone --depth=1"

def cached_archive_name(name, version):
    return os.path.join(cache_path, name + version)

def capitalize(s):
    return s[0].upper() + s[1:]

def fetch(versions, version, temp_dir):
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
        shutil.copytree(version, result_dir)
        os.chdir(result_dir)
        return result_dir

    result_dir = os.path.join(temp_dir, name)
    print("Cloning {} from {} @{}".format(capitalize(name), repo, ref))
    run_command(git_clone_command(repo), quote(repo), quote(result_dir))
    os.chdir(result_dir)

    if ref != "master":
        run_command("git checkout", quote(ref))

    return result_dir

lua_version_regexp = re.compile("^\\s*#define\\s+LUA_VERSION_NUM\\s+50(\d)\\s*$")

def detect_lua_version(lua_path):
    lua_h = open(os.path.join(lua_path, "src", "lua.h"))

    for line in lua_h:
        match = lua_version_regexp.match(line)

        if match:
            return "5." + match.group(1)

def patch_default_paths(lua_path, package_path, package_cpath):
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
    module_path = os.path.join(target_dir, "share", "lua", nominal_version)
    package_path = ";".join([
        os.path.join(module_path, "?.lua"),
        os.path.join(module_path, "?", "init.lua"),
        os.path.join(".", "?.lua")
    ])
    cmodule_path = os.path.join(target_dir, "lib", "lua", nominal_version)
    so_extension = ".dll" if os.name == "nt" else ".so"
    package_cpath = ";".join([
        os.path.join(cmodule_path, "?" + so_extension),
        os.path.join(cmodule_path, "loadall" + so_extension),
        os.path.join(".", "?" + so_extension)
    ])
    return package_path, package_cpath

def apply_compat(lua_path, nominal_version, is_luajit, compat):
    if compat != "default":
        if is_luajit:
            if compat in ["all", "5.2"]:
                patch_build_option(lua_path,
                                   "#XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT",
                                   "XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT")
        elif nominal_version == "5.2":
            if compat in ["none", "5.2"]:
                patch_build_option(lua_path, " -DLUA_COMPAT_ALL", "")
        elif nominal_version == "5.3":
            if compat == "none":
                patch_build_option(lua_path, " -DLUA_COMPAT_5_2", "")
            elif compat == "all":
                patch_build_option(lua_path, " -DLUA_COMPAT_5_2",
                                   " -DLUA_COMPAT_5_1 -DLUA_COMPAT_5_2")
            elif compat == "5.1":
                patch_build_option(lua_path, " -DLUA_COMPAT_5_2", " -DLUA_COMPAT_5_1")

def install_lua(target_dir, lua_version, is_luajit, lua_target, compat, temp_dir):
    lua_path = fetch(luajit_versions if is_luajit else lua_versions, lua_version, temp_dir)
    print("Building " + ("LuaJIT" if is_luajit else "Lua"))
    nominal_version = detect_lua_version(lua_path)
    package_path, package_cpath = get_luarocks_paths(target_dir, nominal_version)
    patch_default_paths(lua_path, package_path, package_cpath)
    apply_compat(lua_path, nominal_version, is_luajit, compat)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    if is_luajit:
        run_command("make", "PREFIX=" + quote(target_dir))
        print("Installing LuaJIT")
        run_command("make install", "PREFIX=" + quote(target_dir),
                    "INSTALL_TNAME=lua", "INSTALL_TSYM=luajit_symlink",
                    "INSTALL_INC=" + quote(os.path.join(target_dir, "include")))

        if os.path.exists(os.path.join(target_dir, "bin", "luajit_symlink")):
            os.remove(os.path.join(target_dir, "bin", "luajit_symlink"))
    else:
        run_command("make", lua_target)
        print("Installing Lua")
        run_command("make install", "INSTALL_TOP=" + quote(target_dir))

def install_luarocks(target_dir, luarocks_version, temp_dir):
    luarocks_path = fetch(luarocks_versions, luarocks_version, temp_dir)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    print("Building LuaRocks")
    run_command("./configure", "--prefix=" + quote(target_dir),
                "--with-lua=" + quote(target_dir), "--force-config")
    run_command("make build")
    print("Installing LuaRocks")
    run_command("make install")

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
    parser.add_argument("-t", "--target", help="Use 'make TARGET' when building standard Lua.",
                        default=get_default_lua_target())
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
                    args.target, args.compat, temp_dir)
        os.chdir(start_dir)

    if args.luarocks:
        install_luarocks(abs_location, args.luarocks, temp_dir)
        os.chdir(start_dir)

    shutil.rmtree(temp_dir)
    print("Done.")

if __name__ == "__main__":
    main()
