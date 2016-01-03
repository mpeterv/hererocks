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

hererocks_version = "Hererocks 0.4.0"
__all__ = ["main"]

opts = None
temp_dir = None

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
        if capture and not exception.output.strip():
            # Ignore errors if output is empty.
            return ""

        if not live_output:
            sys.stdout.write(exception.output)

        sys.exit("Error: got exitcode {} from command {}".format(
            exception.returncode, command))

    if opts.verbose and capture:
        sys.stdout.write(output.decode("UTF-8"))

    return capture and output.decode("UTF-8")

def run_command(*args):
    exec_command(False, *args)

def copy_dir(src, dst):
    shutil.copytree(src, dst, ignore=lambda _, __: {".git"})

clever_http_git_whitelist = [
    "http://github.com/", "https://github.com/",
    "http://bitbucket.com/", "https://bitbucket.com/"
]

git_branch_accepts_tags = None

def set_git_branch_accepts_tags():
    global git_branch_accepts_tags

    if git_branch_accepts_tags is None:
        version_output = exec_command(True, "git --version")
        match = re.search("(\d+)\.(\d+)\.?(\d*)", version_output)

        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            tiny = int(match.group(3) or "0")
            git_branch_accepts_tags = major > 1 or (
                major == 1 and (minor > 7 or (minor == 7 and tiny >= 10)))

def git_clone_command(repo, ref, is_cache):
    if is_cache:
        # Cache full repos.
        return "git clone", True

    # Http(s) transport may be dumb and not understand --depth.
    if repo.startswith("http://") or repo.startswith("https://"):
        if not any(map(repo.startswith, clever_http_git_whitelist)):
            return "git clone", True

    # Have to clone whole repo to get a specific commit.
    if all(c in string.hexdigits for c in ref):
        return "git clone", True

    set_git_branch_accepts_tags()

    if git_branch_accepts_tags:
        return "git clone --depth=1 --branch=" + quote(ref), False
    else:
        return "git clone --depth=1", True

def url_to_name(s):
    return re.sub("[^\w]", "_", s)

def identifiers_to_string(identifiers):
    return "-".join(identifiers)

def copy_files(path, *files):
    if not os.path.exists(path):
        os.makedirs(path)

    for src in files:
        if src is not None:
            shutil.copy(src, path)

def exe(name):
    if os.name == "nt":
        return name + ".exe"
    else:
        return name

class Program(object):
    def __init__(self, version):
        version = self.translations.get(version, version)

        if version in self.versions:
            # Simple version.
            self.source_kind = "fixed"
            self.fetched = False
            self.version = version
            self.version_suffix = " " + version
        elif "@" in version:
            # Version from a git repo.
            self.source_kind = "git"

            if version.startswith("@"):
                # Use the default git repo for this program.
                self.repo = self.default_repo
                ref = version[1:] or "master"
            else:
                self.repo, _, ref = version.partition("@")

            # Have to clone the repo to get the commit ref points to.
            self.fetch_repo(ref)
            self.commit = exec_command(True, "git rev-parse HEAD").strip()
            self.version_suffix = " @" + self.commit[:7]
        else:
            # Local directory.
            self.source_kind = "local"

            if not os.path.exists(version):
                sys.exit("Error: bad {} version {}".format(self.title, version))

            print("Using {} from {}".format(self.title, version))
            result_dir = os.path.join(temp_dir, self.name)
            copy_dir(version, result_dir)
            os.chdir(result_dir)
            self.fetched = True
            self.version_suffix = ""

    def fetch_repo(self, ref):
        message = "Cloning {} from {} @{}".format(self.title, self.repo, ref)

        if self.repo == self.default_repo and not opts.no_git_cache:
            # Default repos are cached.
            if not os.path.exists(opts.downloads):
                os.makedirs(opts.downloads)

            repo_path = os.path.join(opts.downloads, self.name)
            self.fetched = False

            if os.path.exists(repo_path):
                print(message + " (cached)")
                # Sync with origin first.
                os.chdir(repo_path)

                if not exec_command(True, "git rev-parse --quiet --verify", quote(ref)):
                    run_command("git fetch")

                run_command("git checkout", quote(ref))

                # If HEAD is not detached, we are on a branch that must be synced.
                if exec_command(True, "git symbolic-ref -q HEAD"):
                    run_command("git pull --rebase")

                return
        else:
            self.fetched = True
            repo_path = os.path.join(temp_dir, self.name)

        print(message)
        clone_command, need_checkout = git_clone_command(self.repo, ref, not self.fetched)
        run_command(clone_command, quote(self.repo), quote(repo_path))
        os.chdir(repo_path)

        if need_checkout and ref != "master":
            run_command("git checkout", quote(ref))

    def get_download_name(self):
        return self.name + "-" + self.version + ("-win32" if self.win32_zip else "")

    def get_download_url(self):
        return self.downloads + "/" + self.get_download_name() + (
            ".zip" if self.win32_zip else ".tar.gz")

    def fetch(self):
        if self.fetched:
            return

        if self.source_kind == "git":
            # Currently inside the cached git repo, just copy it somewhere.
            result_dir = os.path.join(temp_dir, self.name)
            copy_dir(".", result_dir)
            os.chdir(result_dir)
            return

        if not os.path.exists(opts.downloads):
            os.makedirs(opts.downloads)

        archive_name = os.path.join(opts.downloads, self.name + self.version)
        url = self.get_download_url()
        message = "Fetching {} from {}".format(self.title, url)

        if not os.path.exists(archive_name):
            print(message)
            urlretrieve(url, archive_name)
        else:
            print(message + " (cached)")

        if self.win32_zip:
            archive = zipfile.ZipFile(archive_name)
        else:
            archive = tarfile.open(archive_name, "r:gz")

        archive.extractall(temp_dir)
        archive.close()
        os.chdir(os.path.join(temp_dir, self.get_download_name()))
        self.fetched = True

    def set_identifiers(self):
        if self.source_kind == "fixed":
            self.identifiers = [self.name, self.version]
        elif self.source_kind == "git":
            self.identifiers = [self.name, "git", url_to_name(self.repo), url_to_name(self.commit)]
        else:
            self.identifiers = None

    def update_identifiers(self, all_identifiers):
        installed_identifiers = all_identifiers.get(self.name)
        self.set_identifiers()

        if not opts.ignore_installed:
            if self.identifiers is not None and self.identifiers == installed_identifiers:
                print(self.title + self.version_suffix + " already installed")
                return False

        self.build()
        self.install()
        all_identifiers[self.name] = self.identifiers
        return True

class Lua(Program):
    def __init__(self, version):
        super(Lua, self).__init__(version)

        if self.source_kind == "fixed":
            self.major_version = self.major_version_from_version()
        else:
            self.major_version = self.major_version_from_source()

        if not self.version_suffix:
            self.version_suffix = " " + self.major_version

        self.set_compat()
        self.add_options_to_version_suffix()

        self.defines = []
        self.redefines = []
        self.add_compat_to_defines()
        self.set_package_paths()
        self.add_package_paths_to_defines()

    @staticmethod
    def major_version_from_source():
        lua_h = open(os.path.join("src", "lua.h"))

        for line in lua_h:
            match = re.match("^\\s*#define\\s+LUA_VERSION_NUM\\s+50(\d)\\s*$", line)

            if match:
                return "5." + match.group(1)

    def set_identifiers(self):
        super(Lua, self).set_identifiers()

        if self.identifiers is not None:
            self.identifiers.extend(map(url_to_name, [
                opts.target, self.compat, opts.cflags or "", opts.location
            ]))

    def add_options_to_version_suffix(self):
        options = []

        if opts.target != get_default_lua_target():
            options.append(("target", opts.target))

        if self.compat != "default":
            options.append(("compat", self.compat))

        if opts.cflags is not None:
            options.append(("cflags", opts.cflags))

        if options:
            self.version_suffix += " (" + (", ".join(
                opt + ": " + value for opt, value in options)) + ")"

    def set_package_paths(self):
        local_paths_first = self.major_version == "5.1"

        module_path = os.path.join(opts.location, "share", "lua", self.major_version)
        module_path_parts = [
            os.path.join(module_path, "?.lua"),
            os.path.join(module_path, "?", "init.lua")
        ]
        module_path_parts.insert(0 if local_paths_first else 2, os.path.join(".", "?.lua"))
        self.package_path = ";".join(module_path_parts)

        cmodule_path = os.path.join(opts.location, "lib", "lua", self.major_version)
        so_extension = ".dll" if os.name == "nt" else ".so"
        cmodule_path_parts = [
            os.path.join(cmodule_path, "?" + so_extension),
            os.path.join(cmodule_path, "loadall" + so_extension)
        ]
        cmodule_path_parts.insert(0 if local_paths_first else 2,
                                  os.path.join(".", "?" + so_extension))
        self.package_cpath = ";".join(cmodule_path_parts)

    def add_package_paths_to_defines(self):
        package_path = self.package_path.replace("\\", "\\\\")
        package_cpath = self.package_cpath.replace("\\", "\\\\")
        self.redefines.extend([
            "#undef LUA_PATH_DEFAULT",
            "#undef LUA_CPATH_DEFAULT",
            "#define LUA_PATH_DEFAULT \"{}\"".format(package_path),
            "#define LUA_CPATH_DEFAULT \"{}\"".format(package_cpath)
        ])

    def patch_defines(self):
        defines = "\n".join(self.defines)
        redefines = "\n".join(self.redefines)

        luaconf_h = open(os.path.join("src", "luaconf.h"), "rb")
        luaconf_src = luaconf_h.read()
        luaconf_h.close()

        body, _, tail = luaconf_src.rpartition(b"#endif")
        header, _, main = body.partition(b"#define")
        first_define, main = main.split(b"\n", 1)

        luaconf_h = open(os.path.join("src", "luaconf.h"), "wb")
        luaconf_h.write(header + b"#define" + first_define + b"\n")
        luaconf_h.write(defines.encode("UTF-8") + b"\n")
        luaconf_h.write(main)
        luaconf_h.write(redefines.encode("UTF-8") + b"\n")
        luaconf_h.write(b"#endif")
        luaconf_h.write(tail)
        luaconf_h.close()

    def build(self):
        if opts.builds and self.identifiers is not None:
            self.cached_build_path = os.path.join(opts.builds,
                                                  identifiers_to_string(self.identifiers))

            if os.path.exists(self.cached_build_path):
                print("Building " + self.title + self.version_suffix + " (cached)")
                os.chdir(self.cached_build_path)
                return
        else:
            self.cached_build_path = None

        self.fetch()
        print("Building " + self.title + self.version_suffix)
        self.patch_defines()
        self.make()

        if self.cached_build_path is not None:
            copy_dir(".", self.cached_build_path)

    def install(self):
        print("Installing " + self.title + self.version_suffix)
        self.make_install()

class RioLua(Lua):
    name = "lua"
    title = "Lua"
    downloads = "http://www.lua.org/ftp"
    win32_zip = False
    default_repo = "https://github.com/lua/lua"
    versions = [
        "5.1", "5.1.1", "5.1.2", "5.1.3", "5.1.4", "5.1.5",
        "5.2.0", "5.2.1", "5.2.2", "5.2.3", "5.2.4",
        "5.3.0", "5.3.1", "5.3.2"
    ]
    translations = {
        "5": "5.3.2",
        "5.1": "5.1.5",
        "5.1.0": "5.1",
        "5.2": "5.2.4",
        "5.3": "5.3.2",
        "^": "5.3.2"
    }

    def major_version_from_version(self):
        return self.version[:3]

    def set_compat(self):
        if self.major_version == "5.1":
            self.compat = "none" if opts.compat == "none" else "default"
        elif self.major_version == "5.2":
            self.compat = "none" if opts.compat in ["none", "5.2"] else "default"
        else:
            self.compat = "default" if opts.compat in ["default", "5.2"] else opts.compat

    def add_compat_to_defines(self):
        if self.compat != "default":
            if self.major_version == "5.1":
                if self.compat == "none":
                    self.redefines.extend([
                        "#undef LUA_COMPAT_VARARG", "#undef LUA_COMPAT_MOD",
                        "#undef LUA_COMPAT_LSTR", "#undef LUA_COMPAT_GFIND",
                        "#undef LUA_COMPAT_OPENLIB"
                    ])
            elif self.major_version == "5.2":
                self.defines.append("#undef LUA_COMPAT_ALL")
            elif self.compat == "none":
                self.defines.append("#undef LUA_COMPAT_5_2")
            elif self.compat == "5.1":
                self.defines.append("#undef LUA_COMPAT_5_2")
                self.defines.append("#define LUA_COMPAT_5_1")
            else:
                self.defines.append("#define LUA_COMPAT_5_1")

    def set_files(self):
        self.lua_file = exe("lua")
        self.luac_file = exe("luac")
        self.arch_file = "liblua.a"
        self.dll_file = None

        if os.name == "nt":
            self.dll_file = "lua5" + self.major_version[2] + ".dll"

            if opts.target == "cl":
                self.arch_file = None

    def make(self):
        cmd = "make"

        if opts.cflags is not None:
            if self.major_version == "5.1":
                # Lua 5.1 doesn't support passing MYCFLAGS to Makefile.
                makefile_h = open(os.path.join("src", "Makefile"), "rb")
                makefile_src = makefile_h.read()
                makefile_h.close()

                before, it, after = makefile_src.partition(b"CFLAGS= -O2 -Wall $(MYCFLAGS)")
                makefile_src = before + it + " " + opts.cflags + after

                makefile_h = open(os.path.join("src", "Makefile"), "wb")
                makefile_h.write(makefile_src)
                makefile_h.close()
            else:
                cmd = "make MYCFLAGS=" + quote(opts.cflags)

        run_command(cmd, opts.target)

    def make_install(self):
        self.set_files()
        os.chdir("src")
        copy_files(os.path.join(opts.location, "bin"),
                   self.lua_file, self.luac_file, self.dll_file)

        lua_hpp = "lua.hpp"

        if not os.path.exists(lua_hpp):
            lua_hpp = "../etc/lua.hpp"

        copy_files(os.path.join(opts.location, "include"),
                   "lua.h", "luaconf.h", "lualib.h", "lauxlib.h", lua_hpp)

        copy_files(os.path.join(opts.location, "lib"), self.arch_file)

class LuaJIT(Lua):
    name = "LuaJIT"
    title = "LuaJIT"
    downloads = "https://github.com/LuaJIT/LuaJIT/archive"
    win32_zip = False
    default_repo = "https://github.com/LuaJIT/LuaJIT"
    versions = [
        "2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.0.4"
    ]
    translations = {
        "2": "2.0.4",
        "2.0": "2.0.4",
        "2.1": "@v2.1",
        "^": "2.0.4"
    }

    def get_download_url(self):
        return self.downloads + "/v" + self.version + ".tar.gz"

    @staticmethod
    def major_version_from_version():
        return "5.1"

    def set_compat(self):
        self.compat = "5.2" if opts.compat in ["all", "5.2"] else "default"

    def add_compat_to_defines(self):
        if self.compat != "default":
            self.defines.append("#define LUAJIT_ENABLE_LUA52COMPAT")

    @staticmethod
    def make():
        if os.name == "nt" and opts.target == "cl":
            os.chdir("src")
            run_command("msvcbuild.bat")
            os.chdir("..")
        else:
            run_command("make" if opts.cflags is None else "make XCFLAGS=" + quote(opts.cflags))

    def make_install(self):
        luajit_file = exe("luajit")
        lua_file = exe("lua")
        arch_file = "libluajit.a"
        target_arch_file = "libluajit-5.1.a"
        so_file = "libluajit.so"
        target_so_file = "libluajit-5.1.so.2"
        dll_file = None

        if os.name == "nt":
            self.arch_file = "lua51.lib"
            target_arch_file = "lua51.lib"
            dll_file = "lua51.dll"

        os.chdir("src")
        copy_files(os.path.join(opts.location, "bin"), dll_file)
        shutil.copy(luajit_file, os.path.join(opts.location, "bin", lua_file))

        copy_files(os.path.join(opts.location, "include"),
                   "lua.h", "luaconf.h", "lualib.h", "lauxlib.h", "lua.hpp")

        copy_files(os.path.join(opts.location, "lib"))
        shutil.copy(arch_file, os.path.join(opts.location, "lib", target_arch_file))
        shutil.copy(so_file, os.path.join(opts.location, "lib", target_so_file))

        jitlib_path = os.path.join(
            opts.location, "share", "lua", self.major_version, "jit")

        if os.path.exists(jitlib_path):
            shutil.rmtree(jitlib_path)

        copy_dir("jit", jitlib_path)

class LuaRocks(Program):
    name = "luarocks"
    title = "LuaRocks"
    downloads = "http://keplerproject.github.io/luarocks/releases"
    win32_zip = os.name == "nt"
    default_repo = "https://github.com/keplerproject/luarocks"
    versions = [
        "2.0.8", "2.0.9", "2.0.10", "2.0.11", "2.0.12",
        "2.1.0", "2.1.1", "2.1.2",
        "2.2.0", "2.2.1", "2.2.2"
    ]
    translations = {
        "2": "2.2.2",
        "2.0": "2.0.12",
        "2.1": "2.1.2",
        "2.2": "2.2.2",
        "3": "@luarocks-3",
        "^": "2.2.2"
    }

    def is_luarocks_2_0(self):
        if self.source_kind == "fixed":
            return self.versions.index(self.version) < self.versions.index("2.1.0")

        makefile = open("Makefile")

        for line in makefile:
            if re.match("^\\s*all:\\s+built\\s*$", line):
                return True

        return False

    def build(self):
        self.fetch()
        print("Building LuaRocks" + self.version_suffix)
        run_command("./configure", "--prefix=" + quote(opts.location),
                    "--with-lua=" + quote(opts.location), "--force-config")
        run_command("make" if self.is_luarocks_2_0() else "make build")

    def install(self):
        print("Installing LuaRocks" + self.version_suffix)
        run_command("make install")

def get_manifest_name():
    return os.path.join(opts.location, "hererocks.manifest")

def get_installed_identifiers():
    if not os.path.exists(get_manifest_name()):
        return {}

    manifest_h = open(get_manifest_name())
    identifiers = {}

    for line in manifest_h:
        cur_identifiers = line.strip().split("-")

        if cur_identifiers:
            identifiers[cur_identifiers[0]] = cur_identifiers

    return identifiers

def save_installed_identifiers(identifiers):
    manifest_h = open(get_manifest_name(), "w")

    for program in [RioLua, LuaJIT, LuaRocks]:
        if identifiers.get(program.name) is not None:
            manifest_h.write(identifiers_to_string(identifiers[program.name]))
            manifest_h.write("\n")

    manifest_h.close()

def main():
    parser = argparse.ArgumentParser(
        description=hererocks_version + " a tool for installing Lua and/or LuaRocks locally.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter, add_help=False)
    parser.add_argument(
        "location", help="Path to directory in which Lua and/or LuaRocks will be installed. "
        "Their binaries will be found in its 'bin' subdirectory. "
        "Scripts from modules installed using LuaRocks will also turn up there. "
        "If an incompatible version of Lua is already installed there it should be "
        "removed before installing the new one. ")
    parser.add_argument(
        "-l", "--lua", help="Version of standard PUC-Rio Lua to install. "
        "Version can be specified as a version number, e.g. 5.2 or 5.3.1. "
        "Versions 5.1.0 - 5.3.2 are supported, "
        "'^' can be used to install the latest stable version. "
        "If the argument contains '@', sources will be downloaded "
        "from a git repo using URI before '@' and using part after '@' as git reference "
        "to checkout, 'master' by default. "
        "Default git repo is https://github.com/lua/lua which contains tags for most "
        "unstable versions, i.e. Lua 5.3.2-rc1 can be installed using '@5.3.2-rc1' as version. "
        "The argument can also be a path to local directory.")
    parser.add_argument(
        "-j", "--luajit", help="Version of LuaJIT to install. "
        "Version can be specified in the same way as for standard Lua. "
        "Versions 2.0.0 - 2.1 are supported. "
        "When installing from the LuaJIT main git repo its URI can be left out, "
        "so that '@458a40b' installs from a commit and '@' installs from the master branch.")
    parser.add_argument(
        "-r", "--luarocks", help="Version of LuaRocks to install. "
        "As with Lua, a version number (in range 2.0.8 - 2.2.2), '^', git URI with reference or "
        "a local path can be used. '3' can be used as a version number and installs from "
        "the 'luarocks-3' branch of the standard LuaRocks git repo. "
        "Note that Lua 5.2 is not supported in LuaRocks 2.0.8 "
        "and Lua 5.3 is supported only since LuaRocks 2.2.0.")
    parser.add_argument("-i", "--ignore-installed", default=False, action="store_true",
                        help="Install even if requested version is already present.")
    parser.add_argument(
        "--compat", default="default", choices=["default", "none", "all", "5.1", "5.2"],
        help="Select compatibility flags for Lua.")
    parser.add_argument(
        "--cflags", default=None,
        help="Pass additional options to C compiler when building Lua or LuaJIT.")
    parser.add_argument("--target", help="Use 'make TARGET' when building standard Lua.",
                        default=get_default_lua_target())
    parser.add_argument("--downloads",
                        # help="Cache downloads in 'DOWNLOADS' directory.",
                        help=argparse.SUPPRESS, default=get_default_cache())
    parser.add_argument("--no-git-cache",
                        help="Do not cache default git repos.",
                        action="store_true", default=False)
    parser.add_argument("--builds",
                        # help="Cache Lua and LuaJIT builds in 'BUILDS' directory.",
                        help=argparse.SUPPRESS, default=None)
    parser.add_argument("--verbose", default=False, action="store_true",
                        help="Show executed commands and their output.")
    parser.add_argument("-v", "--version", help="Show program's version number and exit.",
                        action="version", version=hererocks_version)
    parser.add_argument("-h", "--help", help="Show this help message and exit.", action="help")

    global opts, temp_dir
    opts = parser.parse_args()
    if not opts.lua and not opts.luajit and not opts.luarocks:
        parser.error("nothing to install")

    if opts.lua and opts.luajit:
        parser.error("can't install both PUC-Rio Lua and LuaJIT")

    opts.location = os.path.abspath(opts.location)
    opts.downloads = os.path.abspath(opts.downloads)

    if opts.builds is not None:
        opts.builds = os.path.abspath(opts.builds)

    start_dir = os.getcwd()
    temp_dir = tempfile.mkdtemp()
    identifiers = get_installed_identifiers()
    identifiers_changed = False

    if not os.path.exists(opts.location):
        os.makedirs(opts.location)

    if opts.lua:
        identifiers["LuaJIT"] = None
        identifiers_changed = RioLua(opts.lua).update_identifiers(identifiers)
        os.chdir(start_dir)

    if opts.luajit:
        identifiers["lua"] = None
        identifiers_changed = LuaJIT(opts.luajit).update_identifiers(identifiers)
        os.chdir(start_dir)

    if opts.luarocks:
        if LuaRocks(opts.luarocks).update_identifiers(identifiers):
            identifiers_changed = True

        os.chdir(start_dir)

    if identifiers_changed:
        save_installed_identifiers(identifiers)

    shutil.rmtree(temp_dir)
    print("Done.")

if __name__ == "__main__":
    main()
