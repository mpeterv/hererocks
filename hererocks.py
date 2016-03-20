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
import hashlib

try:
    from urllib import urlretrieve
except ImportError:
    from urllib.request import urlretrieve

hererocks_version = "Hererocks 0.6.0"
__all__ = ["main"]

opts = None
temp_dir = None

def is_executable(path):
    return (os.path.exists(path) and
            os.access(path, os.F_OK | os.X_OK) and
            not os.path.isdir(path))

def program_exists(prog):
    path = os.environ.get("PATH", os.defpath)

    if not path:
        return False

    if os.name == "nt":
        pathext = os.environ.get("PATHEXT", "").split(os.pathsep)
        candidates = [prog + ext for ext in pathext]
    else:
        candidates = [prog]

    for directory in path.split(os.pathsep):
        for candidate in candidates:
            if is_executable(os.path.join(directory, candidate)):
                return True

    return False

platform_to_lua_target = {
    "linux": "linux",
    "win": "cl" if os.name == "nt" and program_exists("cl") else "mingw",
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

def escape_identifier(s):
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

def objext():
    return ".obj" if opts.target == "cl" else ".o"

def sha256_of_file(filename):
    fileobj = open(filename, "rb")
    contents = fileobj.read()
    fileobj.close()
    return hashlib.sha256(contents).hexdigest()

class Program(object):
    def __init__(self, version):
        version = self.translations.get(version, version)

        if version in self.versions:
            # Simple version.
            self.source_kind = "fixed"
            self.fetched = False
            self.version = version
            self.fixed_version = version
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
        return self.name + "-" + self.fixed_version + ("-win32" if self.win32_zip else "")

    def get_file_name(self):
        return self.get_download_name() + (".zip" if self.win32_zip else ".tar.gz")

    def get_download_url(self):
        return self.downloads + "/" + self.get_file_name()

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

        archive_name = os.path.join(opts.downloads, self.get_file_name())
        url = self.get_download_url()
        message = "Fetching {} from {}".format(self.title, url)

        if not os.path.exists(archive_name):
            print(message)
            urlretrieve(url, archive_name)
        else:
            print(message + " (cached)")

        print("Verifying SHA256 checksum")
        expected_checksum = self.checksums[self.get_file_name()]
        observed_checksum = sha256_of_file(archive_name)
        if expected_checksum != observed_checksum:
            message = "SHA256 checksum mismatch for {}\nExpected: {}\nObserved: {}".format(
                archive_name, expected_checksum, observed_checksum)

            if opts.ignore_checksums:
                print("Warning: " + message)
            else:
                sys.exit("Error: " + message)

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
            self.identifiers = [self.name, escape_identifier(self.version)]
        elif self.source_kind == "git":
            self.identifiers = [self.name, "git", escape_identifier(self.repo), escape_identifier(self.commit)]
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
            self.set_version_suffix()

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
            self.identifiers.extend(map(escape_identifier, [
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

        if opts.no_readline:
            options.append(("readline", "false"))

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
    downloads = "https://www.lua.org/ftp"
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
    checksums = {
        "lua-5.1.tar.gz"  : "7f5bb9061eb3b9ba1e406a5aa68001a66cb82bac95748839dc02dd10048472c1",
        "lua-5.1.1.tar.gz": "c5daeed0a75d8e4dd2328b7c7a69888247868154acbda69110e97d4a6e17d1f0",
        "lua-5.1.2.tar.gz": "5cf098c6fe68d3d2d9221904f1017ff0286e4a9cc166a1452a456df9b88b3d9e",
        "lua-5.1.3.tar.gz": "6b5df2edaa5e02bf1a2d85e1442b2e329493b30b0c0780f77199d24f087d296d",
        "lua-5.1.4.tar.gz": "b038e225eaf2a5b57c9bcc35cd13aa8c6c8288ef493d52970c9545074098af3a",
        "lua-5.1.5.tar.gz": "2640fc56a795f29d28ef15e13c34a47e223960b0240e8cb0a82d9b0738695333",
        "lua-5.2.0.tar.gz": "cabe379465aa8e388988073d59b69e76ba0025429d2c1da80821a252cdf6be0d",
        "lua-5.2.1.tar.gz": "64304da87976133196f9e4c15250b70f444467b6ed80d7cfd7b3b982b5177be5",
        "lua-5.2.2.tar.gz": "3fd67de3f5ed133bf312906082fa524545c6b9e1b952e8215ffbd27113f49f00",
        "lua-5.2.3.tar.gz": "13c2fb97961381f7d06d5b5cea55b743c163800896fd5c5e2356201d3619002d",
        "lua-5.2.4.tar.gz": "b9e2e4aad6789b3b63a056d442f7b39f0ecfca3ae0f1fc0ae4e9614401b69f4b",
        "lua-5.3.0.tar.gz": "ae4a5eb2d660515eb191bfe3e061f2b8ffe94dce73d32cfd0de090ddcc0ddb01",
        "lua-5.3.1.tar.gz": "072767aad6cc2e62044a66e8562f51770d941e972dc1e4068ba719cd8bffac17",
        "lua-5.3.2.tar.gz": "c740c7bb23a936944e1cc63b7c3c5351a8976d7867c5252c8854f7b2af9da68f",
    }

    def __init__(self, version):
        super(RioLua, self).__init__(version)

        self.lua_file = exe("lua")
        self.luac_file = exe("luac")

        if opts.target == "cl":
            self.arch_file = "lua5" + self.major_version[2] + ".lib"
        else:
            self.arch_file = "liblua5" + self.major_version[2] + ".a"

        if opts.target == "mingw" or opts.target == "cl":
            self.dll_file = "lua5" + self.major_version[2] + ".dll"
        else:
            self.dll_file = None

    def set_identifiers(self):
        super(RioLua, self).set_identifiers()

        if self.identifiers is not None:
            self.identifiers.append(str(not opts.no_readline))

    def major_version_from_version(self):
        return self.version[:3]

    def set_version_suffix(self):
        self.version_suffix = " " + self.major_version

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

    def make(self):
        if self.major_version == "5.3":
            cc = "gcc -std=gnu99"
        else:
            cc = "gcc"

        if opts.target in ["linux", "freebsd", "macosx"]:
            cflags = ["-DLUA_USE_POSIX -DLUA_USE_DLOPEN"]

            if self.major_version == "5.2":
                cflags.append("-DLUA_USE_STRTODHEX -DLUA_USE_AFORMAT -DLUA_USE_LONGLONG")

            if not opts.no_readline:
                cflags.append("-DLUA_USE_READLINE")

            if opts.target == "linux":
                lflags = ["-Wl,-E -ldl"]

                if not opts.no_readline:
                    if self.major_version == "5.1":
                        lflags.append("-lreadline -lhistory -lncurses")
                    else:
                        lflags.append("-lreadline")
            elif opts.target == "freebsd":
                lflags = []

                if not opts.no_readline:
                    lflags.append("-Wl,-E -lreadline")
            else:
                lflags = []
                cc = "cc"

                if not opts.no_readline:
                    lflags.append("-lreadline")
        else:
            lflags = []

            if opts.target == "posix":
                cflags = ["-DLUA_USE_POSIX"]
            else:
                cflags = []

        if opts.cflags is not None:
            cflags.append(opts.cflags)

        if opts.target == "cl":
            cc = "cl /nologo /MD /O2 /W3 /c /D_CRT_SECURE_NO_DEPRECATE"
        else:
            cflags.insert(0, "-O2 -Wall -Wextra")

        static_cflags = " ".join(cflags)

        if opts.target == "mingw":
            cflags.insert(1, "-DLUA_BUILD_AS_DLL")
        elif opts.target == "cl":
            cflags.insert(0, "-DLUA_BUILD_AS_DLL")

        cflags = " ".join(cflags)
        lflags.append("-lm")
        lflags = " ".join(lflags)

        os.chdir("src")

        objs = []
        luac_objs = ["luac" + objext(), "print" + objext()]

        for src in sorted(os.listdir(".")):
            base, ext = os.path.splitext(src)

            if ext == ".c":
                obj = base + objext()
                objs.append(obj)

                cmd_suffix = src if opts.target == "cl" else ("-c -o " + obj + " " + src)
                run_command(cc, static_cflags if obj in luac_objs else cflags, cmd_suffix)

        lib_objs = [obj_ for obj_ in objs if obj_ not in luac_objs and (obj_ != "lua" + objext())]
        luac_objs = "luac" + objext()

        if "print" + objext() in objs:
            luac_objs += " print" + objext()

        if opts.target == "cl":
            run_command("link /nologo /out:luac.exe", luac_objs, *lib_objs)

            if os.path.exists("luac.exe.manifest"):
                run_command("mt /nologo -manifest luac.exe.manifest -outputresource:luac.exe")
        else:
            run_command("ar rcu", self.arch_file, *lib_objs)
            run_command("ranlib", self.arch_file)
            run_command(cc, "-o", self.luac_file, luac_objs, self.arch_file, lflags)

        if opts.target == "mingw":
            run_command(cc + " -shared -o", self.dll_file, *lib_objs)
            run_command("strip --strip-unneeded", self.dll_file)
            run_command(cc, "-o", self.lua_file, "-s lua.o", self.dll_file)
        elif opts.target == "cl":
            run_command("link /nologo /DLL /out:" + self.dll_file, *lib_objs)

            if os.path.exists(self.dll_file + ".manifest"):
                run_command("mt /nologo -manifest " + self.dll_file +
                            ".manifest -outputresource:" + self.dll_file)

            run_command("link /nologo /out:lua.exe lua.obj", self.arch_file)

            if os.path.exists("lua.exe.manifest"):
                run_command("mt /nologo -manifest lua.exe.manifest -outputresource:lua.exe")
        else:
            run_command(cc, "-o", self.lua_file, "lua.o", self.arch_file, lflags)

        os.chdir("..")

    def make_install(self):
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
        "2.0.0", "2.0.1", "2.0.2", "2.0.3", "2.0.4",
        "2.1.0-beta1", "2.1.0-beta2"
    ]
    translations = {
        "2": "2.0.4",
        "2.0": "2.0.4",
        "2.1": "2.1.0-beta2",
        "^": "2.0.4"
    }
    checksums = {
        "LuaJIT-2.0.0.tar.gz"      : "778650811bdd9fc55bbb6a0e845e4c0101001ce5ca1ab95001f0d289c61760ab",
        "LuaJIT-2.0.1-fixed.tar.gz": "d33e91f347c0d79aa4fb1bd835df282a25f7ef9c3395928a1183947667c2d6b2",
        "LuaJIT-2.0.2.tar.gz"      : "7cf1bdcd89452f64ed994cff85ae32613a876543a81a88939155266558a669bc",
        "LuaJIT-2.0.3.tar.gz"      : "8da3d984495a11ba1bce9a833ba60e18b532ca0641e7d90d97fafe85ff014baa",
        "LuaJIT-2.0.4.tar.gz"      : "d2abdf16bd3556c41c0aaedad76b6c227ca667be8350111d037a4c54fd43abad",
        "LuaJIT-2.1.0-beta1.tar.gz": "3d10de34d8020d7035193013f07c93fc7f16fcf0bb28fc03f572a21a368a5f2a",
        "LuaJIT-2.1.0-beta2.tar.gz": "82e115b21aa74634b2d9f3cb3164c21f3cde7750ba3258d8820f500f6a36b651",
    }

    def __init__(self, version):
        super(LuaJIT, self).__init__(version)

        if self.source_kind == "fixed" and self.version == "2.0.1":
            # v2.0.1 tag is broken, use v2.0.1-fixed.
            self.fixed_version = "2.0.1-fixed"

    def get_download_url(self):
        return self.downloads + "/v" + self.fixed_version + ".tar.gz"

    @staticmethod
    def major_version_from_version():
        return "5.1"

    @staticmethod
    def set_version_suffix():
        pass

    def set_compat(self):
        self.compat = "5.2" if opts.compat in ["all", "5.2"] else "default"

    def add_compat_to_defines(self):
        if self.compat != "default":
            self.defines.append("#define LUAJIT_ENABLE_LUA52COMPAT")

    @staticmethod
    def make():
        if opts.target == "cl":
            os.chdir("src")
            run_command("msvcbuild.bat")
            os.chdir("..")
        else:
            make = "mingw32-make" if (
                opts.target == "mingw" and
                program_exists("mingw32-make")) else "make"
            run_command(make if opts.cflags is None else make + " XCFLAGS=" + quote(opts.cflags))

    def make_install(self):
        luajit_file = exe("luajit")
        lua_file = exe("lua")
        arch_file = "libluajit.a"
        target_arch_file = "libluajit-5.1.a"
        so_file = "libluajit.so"
        target_so_file = "libluajit-5.1.so.2"
        dll_file = None

        if os.name == "nt":
            arch_file = "lua51.lib"
            target_arch_file = "lua51.lib"
            dll_file = "lua51.dll"

        os.chdir("src")
        copy_files(os.path.join(opts.location, "bin"), dll_file)
        shutil.copy(luajit_file, os.path.join(opts.location, "bin", lua_file))

        copy_files(os.path.join(opts.location, "include"),
                   "lua.h", "luaconf.h", "lualib.h", "lauxlib.h", "lua.hpp", "luajit.h")

        copy_files(os.path.join(opts.location, "lib"))
        shutil.copy(arch_file, os.path.join(opts.location, "lib", target_arch_file))

        if os.name != "nt":
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
        "2.2.0", "2.2.1", "2.2.2",
        "2.3.0"
    ]
    translations = {
        "2": "2.3.0",
        "2.0": "2.0.12",
        "2.1": "2.1.2",
        "2.2": "2.2.2",
        "2.3": "2.3.0",
        "3": "@luarocks-3",
        "^": "2.3.0"
    }
    checksums = {
        "luarocks-2.0.10.tar.gz"   : "11731dfe6e210a962cb2a857b8b2f14a9ab1043e13af09a1b9455b486401b46e",
        "luarocks-2.0.10-win32.zip": "bc00dbc80da6939f372bace50ea68d1746111280862858ecef9fcaaa3d70661f",
        "luarocks-2.0.11.tar.gz"   : "feee5a606938604f4fef1fdadc29692b9b7cdfb76fa537908d772adfb927741e",
        "luarocks-2.0.11-win32.zip": "b0c2c149da49d70972178e3aec0a92a678b3daa2993dd6d6cdd56269730f8e12",
        "luarocks-2.0.12.tar.gz"   : "ad4b465c5dfbdce436ef746a434317110d79f18ff79202a2697e215f4ac407ed",
        "luarocks-2.0.12-win32.zip": "dfb7c7429541628903ec811f151ea19435d2182a9515db57542f6825802a1ae7",
        "luarocks-2.0.8.tar.gz"    : "f8abf1ab03b744a817721a0ff4a0ee454e068735efaa8d1aadcfcd0f07cdaa88",
        "luarocks-2.0.8-win32.zip" : "109e2dd91c66a7fd69471fcd56b3276f57aef334a4a8f53776b94b1ebd58334e",
        "luarocks-2.0.9.tar.gz"    : "4e25a8052c6abe1685da1093e1adb59aa034106c9d335aa932f7b3b51297c63d",
        "luarocks-2.0.9-win32.zip" : "c9389c288bac2c276e363ffbaaa6356119adefed243f0c47bf74611f9296bd94",
        "luarocks-2.1.0.tar.gz"    : "69bf4cb40c8010a5d434f70d26c9885f4260ac265fdaa848c0edb50cc8e53f88",
        "luarocks-2.1.0-win32.zip" : "363ecc0d09b70179735eef0dae158f98733e6d34226d6b5243bcbdc50d5987ca",
        "luarocks-2.1.1.tar.gz"    : "995ba1b9c982b503fd6fc61c905dc07c3a7533c06587616d9f00d9f62bd318ac",
        "luarocks-2.1.1-win32.zip" : "5fa8eccc91c7c1431480257cb1cf99fff902cf762576e1cd208762f01003e780",
        "luarocks-2.1.2.tar.gz"    : "62625c7609c886bae23f8db55dba45dbb083bae0d19bf12fe29ec95f7d389ff3",
        "luarocks-2.1.2-win32.zip" : "66beb4318261bc3e91544ba8672f04f3057137d32b2c33275ab6a355a7b5a546",
        "luarocks-2.2.0.tar.gz"    : "9b1a4ec7b103e2fb90a7ba8589d7e0c8523a3d6d54ac469b0bbc144292b9279c",
        "luarocks-2.2.0-win32.zip" : "0fb56f40f09352567c66318018b52b9fa9e055f318b8589abed24eb1e76a3def",
        "luarocks-2.2.1.tar.gz"    : "713f8a7e33f1e6dc77ba2eec849a80a95f24f82382e0abc4523c2b8d435f7c55",
        "luarocks-2.2.1-win32.zip" : "01b0410eb19f6e31342cbc12524f2e00eddfdf0bd9edcc325def7bcd93e331be",
        "luarocks-2.2.2.tar.gz"    : "4f0427706873f30d898aeb1dfb6001b8a3478e46a5249d015c061fe675a1f022",
        "luarocks-2.2.2-win32.zip" : "576721fb6fe224bbf5f60bd4c94c7c6f686889bb452ae1923a46d56f02df6588",
        "luarocks-2.3.0.tar.gz"    : "68e38feeb66052e29ad1935a71b875194ed8b9c67c2223af5f4d4e3e2464ed97",
        "luarocks-2.3.0-win32.zip" : "7aa02e7249906563a7ab8bb9db497cdeab0506328e4c8d45ffba120526dfec2a",
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
        "Versions 2.0.0 - 2.1.0-beta2 are supported. "
        "When installing from the LuaJIT main git repo its URI can be left out, "
        "so that '@458a40b' installs from a commit and '@' installs from the master branch.")
    parser.add_argument(
        "-r", "--luarocks", help="Version of LuaRocks to install. "
        "As with Lua, a version number (in range 2.0.8 - 2.3.0), '^', git URI with reference or "
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
    parser.add_argument("--no-readline", help="Don't use readline library when building standard Lua.",
                        action="store_true", default=False)
    parser.add_argument("--downloads",
                        # help="Cache downloads in 'DOWNLOADS' directory.",
                        help=argparse.SUPPRESS, default=get_default_cache())
    parser.add_argument("--no-git-cache",
                        help="Do not cache default git repos.",
                        action="store_true", default=False)
    parser.add_argument("--ignore-checksums",
                        help="Ignore checksum mismatches for downloads.",
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
