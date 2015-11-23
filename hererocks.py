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
import zipfile

try:
    from urllib import urlretrieve
except ImportError:
    from urllib.request import urlretrieve

hererocks_version = "Hererocks 0.0.3"
__all__ = ["main"]

opts = None

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

def get_default_cache():
    if os.name == "nt":
        cache_root = os.getenv("LOCALAPPDATA") or os.path.join(
            os.getenv("USERPROFILE"), "Local Settings", "Application Data")
        return os.path.join(cache_root, "HereRocks", "Cache")
    else:
        return os.path.join(os.getenv("HOME"), ".cache", "hererocks")


def quote(command_arg):
    return "'" + command_arg.replace("'", "'\"'\"'") + "'"

def exec_command(capture, *args):
    command = " ".join(args)

    if opts.verbose:
        print("Running " + command)

    live_output = opts.verbose and not capture
    runner = subprocess.check_call if live_output else subprocess.check_output

    try:
        output = runner(command, stderr=subprocess.STDOUT, shell=True)
    except subprocess.CalledProcessError as exception:
        if not live_output:
            sys.stdout.write(exception.output)

        sys.exit("Error: got exitcode {} from command {}".format(
            exception.returncode, command))

    if opts.verbose and capture:
        sys.stdout.write(output)

    return output

def run_command(*args):
    exec_command(False, *args)

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

    # --branch works even for tags
    return "git clone --depth=1 --branch=" + quote(ref)

def cached_archive_name(name, version):
    return os.path.join(opts.downloads, name + version)

def capitalize(s):
    return s[0].upper() + s[1:]

def url_to_name(s):
    return re.sub("[^\w-]", "_", s)

def copy_dir(src, dst):
    shutil.copytree(src, dst, ignore=lambda _, __: {".git"})

def translate(versions, version):
    return versions[1].get(version, version)

def fetch(versions, version, temp_dir, targz=True):
    raw_versions, _, downloads, name, repo = versions
    version = translate(versions, version)

    if version in raw_versions:
        if not os.path.exists(opts.downloads):
            os.makedirs(opts.downloads)

        archive_name = cached_archive_name(name, version)
        url = downloads + "/" + name + "-" + version + (".tar.gz" if targz else "-win32.zip")
        message = "Fetching {} from {}".format(capitalize(name), url)

        if not os.path.exists(archive_name):
            print(message)
            urlretrieve(url, archive_name)
        else:
            print(message + " (cached)")

        if targz:
            archive = tarfile.open(archive_name, "r:gz")
        else:
            archive = zipfile.ZipFile(archive_name)

        archive.extractall(temp_dir)
        archive.close()
        result_dir = os.path.join(temp_dir, name + "-" + version + ("" if targz else "-win32"))
        os.chdir(result_dir)
        return result_dir, [name, version]

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
        copy_dir(version, result_dir)
        os.chdir(result_dir)
        return result_dir, None

    result_dir = os.path.join(temp_dir, name)
    print("Cloning {} from {} @{}".format(capitalize(name), repo, ref))
    clone_command = git_clone_command(repo, ref)
    run_command(clone_command, quote(repo), quote(result_dir))
    os.chdir(result_dir)

    if clone_command == "git clone" and ref != "master":
        run_command("git checkout", quote(ref))

    commit = exec_command(True, "git rev-parse HEAD").strip().decode("utf-8")
    return result_dir, [name, "git", url_to_name(repo), url_to_name(commit)]

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


def apply_compat(lua_path, nominal_version):
    if opts.compat != "default":
        if opts.luajit:
            if opts.compat in ["all", "5.2"]:
                patch_build_option(lua_path,
                                   "#XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT",
                                   "XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT")
        elif nominal_version == "5.2":
            if opts.compat in ["none", "5.2"]:
                patch_build_option(lua_path, " -DLUA_COMPAT_ALL", "")
        elif nominal_version == "5.3":
            if opts.compat == "none":
                patch_build_option(lua_path, " -DLUA_COMPAT_5_2", "")
            elif opts.compat == "all":
                patch_build_option(lua_path, " -DLUA_COMPAT_5_2",
                                   " -DLUA_COMPAT_5_1 -DLUA_COMPAT_5_2")
            elif opts.compat == "5.1":
                patch_build_option(lua_path, " -DLUA_COMPAT_5_2", " -DLUA_COMPAT_5_1")

def check_subdir(path, subdir):
    path = os.path.join(path, subdir)

    if not os.path.exists(path):
        os.mkdir(path)

    return path

def try_build_cache(target_dir, parts):
    if opts.builds and parts is not None:
        parts.extend(map(url_to_name, [opts.target, opts.compat, target_dir]))
        cached_build_path = os.path.join(opts.builds, "-".join(parts))

        if os.path.exists(cached_build_path):
            print("Building " + capitalize(parts[0]) + " (cached)")
            os.chdir(cached_build_path)
            return cached_build_path, True
        else:
            return cached_build_path, False
    else:
        return None, False

def build_lua(target_dir, lua_version, temp_dir):
    versions = luajit_versions if opts.luajit else lua_versions
    lua_version = translate(versions, lua_version)
    name = versions[3]

    if lua_version in versions[0]:
        # Simple Lua version. Check build cache before fetching sources.
        cached_build_path, cached = try_build_cache(target_dir, [name, lua_version])

        if cached:
            return

    lua_path, parts = fetch(versions, lua_version, temp_dir)
    cached_build_path, cached = try_build_cache(target_dir, parts)

    if cached:
        return

    print("Building " + capitalize(name))
    nominal_version = detect_lua_version(".")
    package_path, package_cpath = get_luarocks_paths(target_dir, nominal_version)
    patch_default_paths(".", package_path, package_cpath)
    apply_compat(".", nominal_version)

    if opts.luajit:
        run_command("make", "PREFIX=" + quote(target_dir))
    else:
        run_command("make", opts.target)

    if cached_build_path is not None:
        copy_dir(".", cached_build_path)

def install_lua(target_dir, lua_version, temp_dir):
    build_lua(target_dir, lua_version, temp_dir)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)

    if opts.luajit:
        print("Installing LuaJIT")
        run_command("make install", "PREFIX=" + quote(target_dir),
                    "INSTALL_TNAME=lua", "INSTALL_TSYM=luajit_symlink",
                    "INSTALL_INC=" + quote(os.path.join(target_dir, "include")))

        if os.path.exists(os.path.join(target_dir, "bin", "luajit_symlink")):
            os.remove(os.path.join(target_dir, "bin", "luajit_symlink"))
    else:
        print("Installing Lua")
        run_command("make install", "INSTALL_TOP=" + quote(target_dir))

def install_luarocks(target_dir, temp_dir):
    fetch(luarocks_versions, opts.luarocks, temp_dir, os.name != "nt")

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
        "--compat", default="default", choices=["default", "none", "all", "5.1", "5.2"],
        help="Select compatibility flags for Lua.")
    parser.add_argument("--target", help="Use 'make TARGET' when building standard Lua.",
                        default=get_default_lua_target())
    parser.add_argument("--downloads", help="Cache downloads in 'DOWNLOADS' directory.",
                        default=get_default_cache())
    parser.add_argument("--builds", help="Cache Lua and LuaJIT builds in 'BUILDS' directory.",
                        default=None)
    parser.add_argument("--verbose", default=False, action="store_true",
                        help="Show executed commands and their output.")
    parser.add_argument("-v", "--version", help="Show program's version number and exit.",
                        action="version", version=hererocks_version)
    parser.add_argument("-h", "--help", help="Show this help message and exit.", action="help")

    global opts
    opts = parser.parse_args()
    if not opts.lua and not opts.luajit and not opts.luarocks:
        parser.error("nothing to install")

    if opts.lua and opts.luajit:
        parser.error("can't install both PUC-Rio Lua and LuaJIT")

    abs_location = os.path.abspath(opts.location)
    opts.downloads = os.path.abspath(opts.downloads)

    if opts.builds is not None:
        opts.builds = os.path.abspath(opts.builds)

    start_dir = os.getcwd()
    temp_dir = tempfile.mkdtemp()

    if opts.lua or opts.luajit:
        install_lua(abs_location, opts.lua or opts.luajit, temp_dir)
        os.chdir(start_dir)

    if opts.luarocks:
        install_luarocks(abs_location, temp_dir)
        os.chdir(start_dir)

    shutil.rmtree(temp_dir)
    print("Done.")

if __name__ == "__main__":
    main()
