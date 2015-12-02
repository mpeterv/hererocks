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

hererocks_version = "Hererocks 0.2.0"
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
        if not live_output:
            sys.stdout.write(exception.output)

        sys.exit("Error: got exitcode {} from command {}".format(
            exception.returncode, command))

    if opts.verbose and capture:
        sys.stdout.write(output)

    return capture and output.decode("utf-8")

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

def git_clone_command(repo, ref):
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
            result_dir = os.path.join(temp_dir, self.name)
            print("Cloning {} from {} @{}".format(self.title, self.repo, ref))
            clone_command, need_checkout = git_clone_command(self.repo, ref)
            run_command(clone_command, quote(self.repo), quote(result_dir))
            os.chdir(result_dir)

            if need_checkout and ref != "master":
                run_command("git checkout", quote(ref))

            self.fetched = True
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

    def fetch(self):
        if self.fetched:
            return

        if not os.path.exists(opts.downloads):
            os.makedirs(opts.downloads)

        archive_name = os.path.join(opts.downloads, self.name + self.version)
        download_name = self.name + "-" + self.version + ("-win32" if self.win32_zip else "")
        url = self.downloads + "/" + download_name + (".zip" if self.win32_zip else ".tar.gz")
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
        os.chdir(os.path.join(temp_dir, download_name))
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

        if self.fetched:
            self.major_version = self.major_version_from_source()
        else:
            self.major_version = self.major_version_from_version()

        if not self.version_suffix:
            self.version_suffix = " " + self.major_version

        self.set_compat()

        if self.compat != "default":
            self.version_suffix += " (compat: {})".format(self.compat)

        self.set_package_paths()

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
            self.identifiers.extend(map(url_to_name, [opts.target, self.compat, opts.location]))

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

    def patch_default_paths(self):
        package_path = self.package_path.replace("\\", "\\\\")
        package_cpath = self.package_cpath.replace("\\", "\\\\")

        luaconf_h = open(os.path.join("src", "luaconf.h"), "rb")
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

        luaconf_h = open(os.path.join("src", "luaconf.h"), "wb")
        luaconf_h.write(body)
        luaconf_h.write(defines.encode("UTF-8"))
        luaconf_h.write(rest)
        luaconf_h.close()

    @staticmethod
    def patch_build_option(old, new):
        makefile = open(os.path.join("src", "Makefile"), "rb")
        makefile_src = makefile.read()
        makefile.close()
        makefile_src = makefile_src.replace(old.encode("UTF-8"), new.encode("UTF-8"), 1)
        makefile = open(os.path.join("src", "Makefile"), "wb")
        makefile.write(makefile_src)
        makefile.close()

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
        self.patch_default_paths()
        self.apply_compat()
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
            self.compat = "default"
        elif self.major_version == "5.2":
            self.compat = "none" if opts.compat in ["none", "5.2"] else "default"
        else:
            self.compat = "default" if opts.compat in ["default", "5.2"] else opts.compat

    def apply_compat(self):
        if self.compat != "default":
            if self.major_version == "5.2":
                self.patch_build_option(" -DLUA_COMPAT_ALL", "")
            elif self.compat == "none":
                self.patch_build_option(" -DLUA_COMPAT_5_2", "")
            elif self.compat == "5.1":
                self.patch_build_option(" -DLUA_COMPAT_5_2", " -DLUA_COMPAT_5_1")
            else:
                self.patch_build_option(" -DLUA_COMPAT_5_2", " -DLUA_COMPAT_5_1 -DLUA_COMPAT_5_2")

    @staticmethod
    def make():
        run_command("make", opts.target)

    @staticmethod
    def make_install():
        run_command("make install", "INSTALL_TOP=" + quote(opts.location))

class LuaJIT(Lua):
    name = "LuaJIT"
    title = "LuaJIT"
    downloads = "http://luajit.org/download"
    win32_zip = False
    default_repo = "https://github.com/luajit/luajit"
    versions = [
        "2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.0.4"
    ]
    translations = {
        "2": "2.0.4",
        "2.0": "2.0.4",
        "2.1": "@v2.1",
        "^": "2.0.4"
    }

    @staticmethod
    def major_version_from_version():
        return "5.1"

    def set_compat(self):
        self.compat = "5.2" if opts.compat in ["all", "5.2"] else "default"

    def apply_compat(self):
        if self.compat != "default":
            self.patch_build_option("#XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT",
                                    "XCFLAGS+= -DLUAJIT_ENABLE_LUA52COMPAT")

    @staticmethod
    def make():
        run_command("make", "PREFIX=" + quote(opts.location))

    @staticmethod
    def make_install():
        run_command("make install", "PREFIX=" + quote(opts.location),
                    "INSTALL_TNAME=lua", "INSTALL_TSYM=luajit_symlink",
                    "INSTALL_INC=" + quote(os.path.join(opts.location, "include")))

        if os.path.exists(os.path.join(opts.location, "bin", "luajit_symlink")):
            os.remove(os.path.join(opts.location, "bin", "luajit_symlink"))

class LuaRocks(Program):
    name = "luarocks"
    title = "LuaRocks"
    downloads = "http://keplerproject.github.io/luarocks/releases"
    win32_zip = os.name == "nt"
    default_repo = "https://github.com/keplerproject/luarocks"
    versions = [
        "2.1.0", "2.1.1", "2.1.2",
        "2.2.0", "2.2.1", "2.2.2"
    ]
    translations = {
        "2": "2.2.2",
        "2.1": "2.1.2",
        "2.2": "2.2.2",
        "3": "@luarocks-3",
        "^": "2.2.2"
    }

    def build(self):
        self.fetch()
        print("Building LuaRocks" + self.version_suffix)
        run_command("./configure", "--prefix=" + quote(opts.location),
                    "--with-lua=" + quote(opts.location), "--force-config")
        run_command("make build")

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
        "Versions 5.1.0 - 5.3.1 are supported, "
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
        "As with Lua, a version number (in range 2.1.0 - 2.2.2), '^', git URI with reference or "
        "a local path can be used. '3' can be used as a version number and installs from "
        "the 'luarocks-3' branch of the standard LuaRocks git repo. "
        "Note that LuaRocks 2.1.x does not support Lua 5.3.")
    parser.add_argument("-i", "--ignore-installed", default=False, action="store_true",
                        help="Install even if requested version is already present.")
    parser.add_argument(
        "--compat", default="default", choices=["default", "none", "all", "5.1", "5.2"],
        help="Select compatibility flags for Lua.")
    parser.add_argument("--target", help="Use 'make TARGET' when building standard Lua.",
                        default=get_default_lua_target())
    parser.add_argument("--downloads",
                        # help="Cache downloads in 'DOWNLOADS' directory.",
                        help=argparse.SUPPRESS,
                        default=get_default_cache())
    parser.add_argument("--builds",
                        # help="Cache Lua and LuaJIT builds in 'BUILDS' directory.",
                        help=argparse.SUPPRESS,
                        default=None)
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
