#!/usr/bin/env python

"""A tool for installing Lua and LuaRocks locally."""

from __future__ import print_function

import argparse
import hashlib
import json
import os
import platform
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

if os.name == "nt":
    try:
        import _winreg as winreg
    except ImportError:
        import winreg

hererocks_version = "Hererocks 0.6.2"
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
    "win": "mingw" if os.name == "nt" and program_exists("gcc") and not program_exists("cl") else "vs",
    "darwin": "macosx",
    "freebsd": "freebsd"
}

def using_cl():
    return opts.target.startswith("vs")

def get_default_lua_target():
    for plat, lua_target in platform_to_lua_target.items():
        if sys.platform.startswith(plat):
            return lua_target

    return "posix" if os.name == "posix" else "generic"

def get_default_cache():
    if os.name == "nt":
        cache_root = os.getenv("LOCALAPPDATA") or os.path.join(
            os.getenv("USERPROFILE"), "Local Settings", "Application Data")
        return os.path.join(cache_root, "HereRocks", "Cache")
    else:
        return os.path.join(os.getenv("HOME"), ".cache", "hererocks")

def run(*args, **kwargs):
    """Execute a command.

    Command can be passed as several arguments, each being a string
    or a list of strings; lists are flattened.
    If opts.verbose is True, output of the command is shown.
    If the command exits with non-zero, print an error message and exit.
    If keyward argument get_output is True, output is returned.
    Additionally, non-zero exit code with empty output is ignored.
    """

    capture = kwargs.get("get_output", False)
    args = [arg for arglist in args for arg in (arglist if isinstance(arglist, list) else [arglist])]

    if opts.verbose:
        print("Running {}".format(" ".join(args)))

    live_output = opts.verbose and not capture
    runner = subprocess.check_call if live_output else subprocess.check_output

    try:
        output = runner(args, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exception:
        if capture and not exception.output.strip():
            # Ignore errors if output is empty.
            return ""

        if not live_output:
            sys.stdout.write(exception.output.decode("UTF-8"))

        sys.exit("Error: got exitcode {} from command {}".format(
            exception.returncode, " ".join(args)))
    except OSError:
        sys.exit("Error: couldn't run {}: is {} in PATH?".format(" ".join(args), args[0]))

    if opts.verbose and capture:
        sys.stdout.write(output.decode("UTF-8"))

    return capture and output.decode("UTF-8").strip()

def get_output(*args):
    return run(get_output=True, *args)

def query_registry(key, value):
    keys = [key, key.replace("\\", "\\Wow6432Node\\", 1)]

    for candidate in keys:
        if opts.verbose:
            print("Querying registry key HKEY_LOCAL_MACHINE\\{}:{}".format(candidate, value))

        try:
            handle = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, candidate)
        except WindowsError:
            pass
        else:
            res = winreg.QueryValueEx(handle, value)[0]
            winreg.CloseKey(handle)
            return res

def check_existence(path):
    if opts.verbose:
        print("Checking existence of {}".format(path))

    return os.path.exists(path)

def copy_dir(src, dst):
    shutil.copytree(src, dst, ignore=lambda _, __: {".git"})

clever_http_git_whitelist = [
    "http://github.com/", "https://github.com/",
    "http://bitbucket.com/", "https://bitbucket.com/"
]

git_branch_does_accept_tags = None

def git_branch_accepts_tags():
    global git_branch_does_accept_tags

    if git_branch_does_accept_tags is None:
        version_output = get_output("git", "--version")
        match = re.search(r"(\d+)\.(\d+)\.?(\d*)", version_output)

        if match:
            major = int(match.group(1))
            minor = int(match.group(2))
            tiny = int(match.group(3) or "0")
            git_branch_does_accept_tags = (major, minor, tiny) >= (1, 7, 10)
        else:
            git_branch_does_accept_tags = False

    return git_branch_does_accept_tags

def git_clone_command(repo, ref, is_cache):
    if is_cache:
        # Cache full repos.
        return ["git", "clone"], True

    # Http(s) transport may be dumb and not understand --depth.
    if repo.startswith("http://") or repo.startswith("https://"):
        if not any(map(repo.startswith, clever_http_git_whitelist)):
            return ["git", "clone"], True

    # Have to clone whole repo to get a specific commit.
    if all(c in string.hexdigits for c in ref):
        return ["git", "clone"], True

    if git_branch_accepts_tags():
        return ["git", "clone", "--depth=1", "--branch=" + ref], False
    else:
        return ["git", "clone", "--depth=1"], True

important_identifiers = ["name", "source", "version", "repo", "commit", "location"]
other_identifiers = ["target", "compat", "c flags", "readline"]

def escape_path(s):
    return re.sub(r"[^\w]", "_", s)

def hash_identifiers(identifiers):
    return "-".join(escape_path(
        identifiers.get(name, "")) for name in important_identifiers + other_identifiers)

def show_identifiers(identifiers):
    title = identifiers["name"]

    if "version" in identifiers:
        title += " " + identifiers["version"]
    elif "major version" in identifiers and title != "LuaJIT":
        title += " " + identifiers["major version"]

    if identifiers["source"] == "release":
        print(title)
    elif identifiers["source"] == "git":
        print("{} @{} (cloned from {})".format(title, identifiers["commit"][:7], identifiers["repo"]))
    else:
        print("{} (from local sources)".format(title))

    for name in other_identifiers:
        if identifiers.get(name):
            print("    {}: {}".format(name.capitalize(), identifiers[name]))

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
    return ".obj" if using_cl() else ".o"

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
            self.source = "release"
            self.fetched = False
            self.version = version
            self.fixed_version = version
            self.version_suffix = " " + version
        elif "@" in version:
            # Version from a git repo.
            self.source = "git"

            if version.startswith("@"):
                # Use the default git repo for this program.
                self.repo = self.default_repo
                ref = version[1:] or "master"
            else:
                self.repo, _, ref = version.partition("@")

            # Have to clone the repo to get the commit ref points to.
            self.fetch_repo(ref)
            self.commit = get_output("git", "rev-parse", "HEAD")
            self.version_suffix = " @" + self.commit[:7]
        else:
            # Local directory.
            self.source = "local"

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

                if not get_output("git", "rev-parse", "--quiet", "--verify", ref):
                    run("git", "fetch")

                run("git", "checkout", ref)

                # If HEAD is not detached, we are on a branch that must be synced.
                if get_output("git", "symbolic-ref", "-q", "HEAD"):
                    run("git", "pull", "--rebase")

                return
        else:
            self.fetched = True
            repo_path = os.path.join(temp_dir, self.name)

        print(message)
        clone_command, need_checkout = git_clone_command(self.repo, ref, not self.fetched)
        run(clone_command, self.repo, repo_path)
        os.chdir(repo_path)

        if need_checkout and ref != "master":
            run("git", "checkout", ref)

    def get_download_name(self):
        return self.name + "-" + self.fixed_version + ("-win32" if self.win32_zip else "")

    def get_file_name(self):
        return self.get_download_name() + (".zip" if self.win32_zip else ".tar.gz")

    def get_download_url(self):
        return self.downloads + "/" + self.get_file_name()

    def fetch(self):
        if self.fetched:
            return

        if self.source == "git":
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
        self.identifiers = {
            "name": self.title,
            "source": self.source
        }

        if self.source == "release":
            self.identifiers["version"] = self.version
        elif self.source == "git":
            self.identifiers["repo"] = self.repo
            self.identifiers["commit"] = self.commit

    def update_identifiers(self, all_identifiers):
        self.all_identifiers = all_identifiers
        installed_identifiers = all_identifiers.get(self.name)
        self.set_identifiers()

        if not opts.ignore_installed and self.source != "local" and installed_identifiers is not None:
            if hash_identifiers(self.identifiers) == hash_identifiers(installed_identifiers):
                print(self.title + self.version_suffix + " already installed")
                return False

        self.build()
        self.install()
        all_identifiers[self.name] = self.identifiers
        return True

class Lua(Program):
    def __init__(self, version):
        super(Lua, self).__init__(version)

        if self.source == "release":
            self.major_version = self.major_version_from_version()
        else:
            self.major_version = self.major_version_from_source()

        if not self.version_suffix:
            self.set_version_suffix()

        self.set_compat()
        self.add_options_to_version_suffix()

        self.redefines = []
        self.compat_cflags = []
        self.set_package_paths()
        self.add_package_paths_redefines()
        self.add_compat_cflags_and_redefines()

    @staticmethod
    def major_version_from_source():
        lua_h = open(os.path.join("src", "lua.h"))

        for line in lua_h:
            match = re.match(r"^\s*#define\s+LUA_VERSION_NUM\s+50(\d)\s*$", line)

            if match:
                return "5." + match.group(1)

        sys.exit("Error: couldn't infer Lua major version from lua.h")

    def set_identifiers(self):
        super(Lua, self).set_identifiers()

        self.identifiers["target"] = opts.target
        self.identifiers["compat"] = self.compat
        self.identifiers["c flags"] = opts.cflags or ""
        self.identifiers["location"] = opts.location
        self.identifiers["major version"] = self.major_version

        if using_cl():
            cl_help = get_output("cl")
            cl_version = re.search(r"(1[56789])\.\d+", cl_help)
            cl_arch = re.search(r"(x(?:86)|(?:64))", cl_help)

            if not cl_version or not cl_arch:
                sys.exit("Error: couldn't determine cl.exe version and architecture")

            cl_version = cl_version.group(1)
            cl_arch = cl_arch.group(1)

            self.identifiers["vs year"] = cl_version_to_vs_year[cl_version]
            self.identifiers["vs arch"] = cl_arch

    def add_options_to_version_suffix(self):
        options = []

        if os.name == "nt" or opts.target != get_default_lua_target():
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

    def add_package_paths_redefines(self):
        package_path = self.package_path.replace("\\", "\\\\")
        package_cpath = self.package_cpath.replace("\\", "\\\\")
        self.redefines.extend([
            "#undef LUA_PATH_DEFAULT",
            "#undef LUA_CPATH_DEFAULT",
            "#define LUA_PATH_DEFAULT \"{}\"".format(package_path),
            "#define LUA_CPATH_DEFAULT \"{}\"".format(package_cpath)
        ])

    def patch_redefines(self):
        redefines = "\n".join(self.redefines)

        luaconf_h = open(os.path.join("src", "luaconf.h"), "rb")
        luaconf_src = luaconf_h.read()
        luaconf_h.close()

        body, _, tail = luaconf_src.rpartition(b"#endif")

        luaconf_h = open(os.path.join("src", "luaconf.h"), "wb")
        luaconf_h.write(body)
        luaconf_h.write(redefines.encode("UTF-8"))
        luaconf_h.write(b"\n#endif")
        luaconf_h.write(tail)
        luaconf_h.close()

    def build(self):
        if opts.builds and self.source != "local":
            self.cached_build_path = os.path.join(opts.builds,
                                                  hash_identifiers(self.identifiers))

            if os.path.exists(self.cached_build_path):
                print("Building " + self.title + self.version_suffix + " (cached)")
                os.chdir(self.cached_build_path)
                return
        else:
            self.cached_build_path = None

        self.fetch()
        print("Building " + self.title + self.version_suffix)
        self.patch_redefines()
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
        "^": "5.3.2",
        "latest": "5.3.2"
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

        if using_cl():
            self.arch_file = "lua5" + self.major_version[2] + ".lib"
        else:
            self.arch_file = "liblua5" + self.major_version[2] + ".a"

        if opts.target == "mingw" or using_cl():
            self.dll_file = "lua5" + self.major_version[2] + ".dll"
        else:
            self.dll_file = None

    def set_identifiers(self):
        super(RioLua, self).set_identifiers()

        self.identifiers["readline"] = str(not opts.no_readline).lower()

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

    def add_compat_cflags_and_redefines(self):
        if self.major_version == "5.1":
            if self.compat == "none":
                self.redefines.extend([
                    "#undef LUA_COMPAT_VARARG", "#undef LUA_COMPAT_MOD",
                    "#undef LUA_COMPAT_LSTR", "#undef LUA_COMPAT_GFIND",
                    "#undef LUA_COMPAT_OPENLIB"
                ])
        elif self.major_version == "5.2":
            if self.compat == "default":
                self.compat_cflags.append("-DLUA_COMPAT_ALL")
        else:
            if self.compat in ["5.1", "all"]:
                self.compat_cflags.append("-DLUA_COMPAT_5_1")

            if self.compat in ["default", "5.2", "all"]:
                self.compat_cflags.append("-DLUA_COMPAT_5_2")

    def make(self):
        if self.major_version == "5.3":
            cc = ["gcc", "-std=gnu99"]
        else:
            cc = "gcc"

        if opts.target in ["linux", "freebsd", "macosx"]:
            cflags = ["-DLUA_USE_POSIX", "-DLUA_USE_DLOPEN"]

            if self.major_version == "5.2":
                cflags.extend(["-DLUA_USE_STRTODHEX", "-DLUA_USE_AFORMAT", "-DLUA_USE_LONGLONG"])

            if not opts.no_readline:
                cflags.append("-DLUA_USE_READLINE")

            if opts.target == "linux":
                lflags = ["-Wl,-E", "-ldl"]

                if not opts.no_readline:
                    if self.major_version == "5.1":
                        lflags.extend(["-lreadline", "-lhistory", "-lncurses"])
                    else:
                        lflags.append("-lreadline")
            elif opts.target == "freebsd":
                lflags = []

                if not opts.no_readline:
                    lflags.extend(["-Wl,-E", "-lreadline"])
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

        cflags.extend(self.compat_cflags)

        if opts.cflags is not None:
            cflags.extend(opts.cflags.split())

        if using_cl():
            cc = ["cl", "/nologo", "/MD", "/O2", "/W3", "/c", "/D_CRT_SECURE_NO_DEPRECATE"]
        else:
            cflags = ["-O2", "-Wall", "-Wextra"] + cflags

        lflags.append("-lm")
        static_cflags = list(cflags)

        if opts.target == "mingw":
            cflags.insert(3, "-DLUA_BUILD_AS_DLL")
        elif using_cl():
            cflags.insert(0, "-DLUA_BUILD_AS_DLL")

        os.chdir("src")
        objs = []
        luac_objs = ["luac" + objext(), "print" + objext()]

        for src in sorted(os.listdir(".")):
            base, ext = os.path.splitext(src)

            if ext == ".c":
                obj = base + objext()
                objs.append(obj)

                cmd_suffix = src if using_cl() else ["-c", "-o", obj, src]
                run(cc, static_cflags if obj in luac_objs else cflags, cmd_suffix)

        lib_objs = [obj_ for obj_ in objs if obj_ not in luac_objs and (obj_ != "lua" + objext())]
        luac_objs = ["luac" + objext()]

        if "print" + objext() in objs:
            luac_objs.append("print" + objext())

        if using_cl():
            run("link", "/nologo", "/out:luac.exe", luac_objs, lib_objs)

            if os.path.exists("luac.exe.manifest"):
                run("mt", "/nologo", "-manifest", "luac.exe.manifest", "-outputresource:luac.exe")
        else:
            run("ar", "rcu", self.arch_file, lib_objs)
            run("ranlib", self.arch_file)
            run(cc, "-o", self.luac_file, luac_objs, self.arch_file, lflags)

        if opts.target == "mingw":
            run(cc, "-shared", "-o", self.dll_file, lib_objs)
            run("strip", "--strip-unneeded", self.dll_file)
            run(cc, "-o", self.lua_file, "-s", "lua.o", self.dll_file)
        elif using_cl():
            run("link", "/nologo", "/DLL", "/out:" + self.dll_file, lib_objs)

            if os.path.exists(self.dll_file + ".manifest"):
                run("mt", "/nologo", "-manifest", self.dll_file + ".manifest",
                    "-outputresource:" + self.dll_file)

            run("link", "/nologo", "/out:lua.exe", "lua.obj", self.arch_file)

            if os.path.exists("lua.exe.manifest"):
                run("mt", "/nologo", "-manifest", "lua.exe.manifest", "-outputresource:lua.exe")
        else:
            run(cc, "-o", self.lua_file, "lua.o", self.arch_file, lflags)

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
        "^": "2.0.4",
        "latest": "2.0.4"
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

        if self.source == "release" and self.version == "2.0.1":
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

    def add_compat_cflags_and_redefines(self):
        if self.compat == "5.2":
            self.compat_cflags.append("-DLUAJIT_ENABLE_LUA52COMPAT")

    @staticmethod
    def add_cflags_to_msvcbuild(cflags):
        msvcbuild_file = open("msvcbuild.bat", "rb")
        msvcbuild_src = msvcbuild_file.read()
        msvcbuild_file.close()

        start, assignment, value_and_rest = msvcbuild_src.partition(b"@set LJCOMPILE")

        msvcbuild_file = open("msvcbuild.bat", "wb")
        msvcbuild_file.write(start)
        msvcbuild_file.write(assignment)
        msvcbuild_file.write(value_and_rest.replace(b"\r\n", b" " + cflags.encode("UTF-8") + b"\r\n", 1))
        msvcbuild_file.close()

    def make(self):
        cflags = list(self.compat_cflags)

        if opts.cflags is not None:
            cflags.extend(opts.cflags.split())

        if using_cl():
            os.chdir("src")

            if cflags:
                self.add_cflags_to_msvcbuild(" ".join(cflags))

            run("msvcbuild.bat")
            os.chdir("..")
        else:
            if opts.target == "mingw" and program_exists("mingw32-make"):
                make = "mingw32-make"
            else:
                make = "make"

            if not cflags:
                run(make)
            else:
                run(make, "XCFLAGS=" + " ".join(cflags))

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

        if opts.target != "mingw":
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
        "^": "2.3.0",
        "latest": "2.3.0"
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
        if self.source == "release":
            return self.versions.index(self.version) < self.versions.index("2.1.0")

        makefile = open("Makefile")

        for line in makefile:
            if re.match(r"^\s*all:\s+built\s*$", line):
                return True

        return False

    @staticmethod
    def get_cmake_generator(lua_identifiers):
        lua_target = lua_identifiers["target"]

        if lua_target == "mingw":
            return "MinGW Makefiles"
        elif using_cl():
            vs_year = lua_identifiers["vs year"]
            vs_arch = lua_identifiers["vs arch"]
            vs_short_version = vs_year_to_version[vs_year][:-2]
            return "Visual Studio {} 20{}{}".format(
                vs_short_version, vs_year, " Win64" if vs_arch == "x64" else "")

    def build(self):
        lua_identifiers = self.all_identifiers.get("lua", self.all_identifiers.get("LuaJIT"))

        if lua_identifiers is None:
            sys.exit("Error: can't install LuaRocks: Lua is not present in {}".format(opts.location))

        self.fetch()

        if os.name == "nt":
            print("Building and installing LuaRocks" + self.version_suffix)

            help_text = get_output("install.bat", "/?")
            args = [
                "install.bat",
                "/P", os.path.join(opts.location, "luarocks"),
                "/LUA", opts.location,
                "/FORCECONFIG",
            ]
            if opts.target == "mingw":
                args += ["/MW"]
            # Since LuaRocks 2.0.13
            if "/LV" in help_text:
                args += ["/LV", lua_identifiers["major version"]]
            # Since LuaRocks 2.1.2
            if "/NOREG" in help_text:
                args += ["/NOREG", "/Q"]

            run(args)

            for script in ["luarocks.bat", "luarocks-admin.bat"]:
                for subdir in [".", "2.2", "2.1", "2.0"]:
                    script_path = os.path.join(opts.location, "luarocks", subdir, script)

                    if os.path.exists(script_path):
                        shutil.copy(script_path, os.path.join(opts.location, "bin"))
                        break

            cmake_generator = self.get_cmake_generator(lua_identifiers)

            if cmake_generator is not None:
                config_path = os.path.join(
                    opts.location, "luarocks", "config-{}.lua".format(lua_identifiers["major version"]))
                config_h = open(config_path, "ab")
                config_h.write(b'\r\ncmake_generator = "{}"\r\n'.format(cmake_generator.encode("UTF-8")))
                config_h.close()

        else:
            print("Building LuaRocks" + self.version_suffix)
            run("./configure", "--prefix=" + opts.location,
                "--with-lua=" + opts.location, "--force-config")

            if self.is_luarocks_2_0():
                run("make")
            else:
                run("make", "build")

    def install(self):
        if os.name != "nt":
            print("Installing LuaRocks" + self.version_suffix)
            run("make", "install")

def get_manifest_name():
    return os.path.join(opts.location, "hererocks.manifest")

manifest_version = 3

def get_installed_identifiers():
    if not os.path.exists(get_manifest_name()):
        return {}

    with open(get_manifest_name()) as manifest_h:
        try:
            identifiers = json.load(manifest_h)
        except ValueError:
            return {}

        if identifiers.get("version") == manifest_version:
            return identifiers
        else:
            return {}

def save_installed_identifiers(all_identifiers):
    all_identifiers["version"] = manifest_version

    with open(get_manifest_name(), "w") as manifest_h:
        json.dump(all_identifiers, manifest_h)

cl_version_to_vs_year = {
    "15": "08",
    "16": "10",
    "17": "12",
    "18": "13",
    "19": "15"
}

vs_year_to_version = {
    "08": "9.0",
    "10": "10.0",
    "12": "11.0",
    "13": "12.0",
    "15": "14.0"
}

def get_vs_directory(vs_version):
    keys = [
        "Software\\Microsoft\\VisualStudio\\{}\\Setup\\VC".format(vs_version),
        "Software\\Microsoft\\VCExpress\\{}\\Setup\\VS".format(vs_version)
    ]

    for key in keys:
        vs_directory = query_registry(key, "ProductDir")

        if vs_directory is not None:
            return vs_directory

def get_wsdk_directory(vs_version):
    if vs_version == "9.0":
        wsdk_version = "v6.1"
    elif vs_version == "10.0":
        wsdk_version = "v7.1"
    else:
        return

    return query_registry(
        "Software\\Microsoft\\Microsoft SDKs\\Windows\\{}".format(wsdk_version), "InstallationFolder")

def get_vs_setup_cmd(vs_version, arch):
    vs_directory = get_vs_directory(vs_version)

    if vs_directory is not None:
        vcvars_all_path = os.path.join(vs_directory, "vcvarsall.bat")

        if check_existence(vcvars_all_path):
            return 'call "{}"{}'.format(vcvars_all_path, " x86_amd64" if arch == "x64" else "")

        vcvars_arch_path = os.path.join(
            vs_directory, "bin", "amd64\\vcvars64.bat" if arch == "x64" else "vcvars32.bat")

        if check_existence(vcvars_arch_path):
            return 'call "{}"'.format(vcvars_arch_path)

    wsdk_directory = get_wsdk_directory(vs_version)

    if wsdk_directory is not None:
        setenv_path = os.path.join(wsdk_directory, "bin", "setenv.cmd")

        if check_existence(setenv_path):
            return 'call "{}" /{}'.format(setenv_path, arch)

def setup_vs_and_rerun(vs_version, arch):
    vs_setup_cmd = get_vs_setup_cmd(vs_version, arch).encode("UTF-8")

    if vs_setup_cmd is None:
        return

    print("Setting up VS {} ({})".format(vs_version, arch))
    bat_name = os.path.join(temp_dir, "hererocks.bat")
    argv_name = os.path.join(temp_dir, "argv")
    setup_output_name = os.path.join(temp_dir, "setup_out")

    script_arg = '"{}"'.format(sys.argv[0])

    if sys.executable:
        script_arg = '"{}" {}'.format(sys.executable, script_arg)

    recursive_call = '{} --actual-argv-file "{}"'.format(script_arg, argv_name).encode("UTF-8")

    bat_h = open(bat_name, "wb")
    bat_h.write(b"@echo off\r\n")
    bat_h.write(b"setlocal enabledelayedexpansion enableextensions\r\n")

    if opts.verbose:
        bat_h.write(b"echo Running {}\r\n".format(vs_setup_cmd))
        bat_h.write(b"{}\r\n".format(vs_setup_cmd))
    else:
        bat_h.write(b'{} > "{}" 2>&1\r\n'.format(vs_setup_cmd, setup_output_name))

    bat_h.write(b"set exitcode=%errorlevel%\r\n")
    bat_h.write(b"if %exitcode% equ 0 (\r\n")
    bat_h.write(b"    {}\r\n".format(recursive_call))
    bat_h.write(b") else (\r\n")

    if not opts.verbose:
        bat_h.write(b'    type "{}"\r\n'.format(setup_output_name))

    bat_h.write(b"    echo Error: got exitcode %exitcode% from command {}\r\n".format(vs_setup_cmd))
    bat_h.write(b"    exit /b 1\r\n")
    bat_h.write(b")\r\n")
    bat_h.close()

    argv_h = open(argv_name, "wb")
    argv_h.write("\r\n".join(sys.argv).encode("UTF-8"))
    argv_h.close()

    exit_code = subprocess.call([bat_name])
    shutil.rmtree(temp_dir)
    sys.exit(exit_code)

class UseActualArgsFileAction(argparse.Action):
    def __call__(self, parser, namespace, fname, option_string=None):
        args_h = open(fname, "rb")
        args_content = args_h.read().decode("UTF-8")
        args_h.close()
        main(args_content.split("\r\n")[1:])

def main(argv=None):
    parser = argparse.ArgumentParser(
        description=hererocks_version + ", a tool for installing Lua and/or LuaRocks locally.",
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
        "'^' or 'latest' can be used to install the latest stable version. "
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
    parser.add_argument("--show", default=False, action="store_true",
                        help="Instead of installing show programs already present in <location>")
    parser.add_argument("-i", "--ignore-installed", default=False, action="store_true",
                        help="Install even if requested version is already present.")
    parser.add_argument(
        "--compat", default="default", choices=["default", "none", "all", "5.1", "5.2"],
        help="Select compatibility flags for Lua.")
    parser.add_argument(
        "--cflags", default=None,
        help="Pass additional options to C compiler when building Lua or LuaJIT.")
    parser.add_argument(
        "--target", help="Select how to build Lua. "
        "Windows-specific targets (mingw, vs and vsXX_YY) also affect LuaJIT. "
        "vs, vs_XX and vsXX_YY targets compile using cl.exe. "
        "vsXX_YY targets (such as vs15_32) always set up Visual Studio 20XX (YYbit). "
        "vs target sets up latest available Visual Studio with host architecture "
        "unless cl.exe is already in PATH. vs_32 and vs_64 targets do the same but use "
        " fixed architecture, while vs target falls back to x86 for VS 2008 and 2010."
        "macosx target uses cc and the remaining targets use gcc, passing compiler "
        "and linker flags the same way Lua's Makefile does when running make <target>.",
        choices=[
            "linux", "macosx", "freebsd", "mingw", "posix", "generic", "mingw", "vs", "vs_32", "vs_64",
            "vs08_32", "vs08_64", "vs10_32", "vs10_64", "vs12_32", "vs12_64",
            "vs13_32", "vs13_64", "vs15_32", "vs15_64"
        ], metavar="{linux,macosx,freebsd,mingw,posix,generic,mingw,vs,vs_XX,vsXX_YY}",
        default=get_default_lua_target())
    parser.add_argument("--no-readline", help="Don't use readline library when building standard Lua.",
                        action="store_true", default=False)
    parser.add_argument("--downloads",
                        help="Cache downloads and default git repos in 'DOWNLOADS' directory.",
                        default=get_default_cache())
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

    if os.name == "nt" and argv is None:
        parser.add_argument("--actual-argv-file", action=UseActualArgsFileAction,
                            # help="Load argv from a file, used when setting up cl toolchain."
                            help=argparse.SUPPRESS)

    global opts
    opts = parser.parse_args(argv)
    if not opts.lua and not opts.luajit and not opts.luarocks and not opts.show:
        parser.error("nothing to do")

    if opts.lua and opts.luajit:
        parser.error("can't install both PUC-Rio Lua and LuaJIT")

    if (opts.lua or opts.luajit or opts.luarocks) and opts.show:
        parser.error("can't both install and show")

    if opts.show:
        if os.path.exists(opts.location):
            all_identifiers = get_installed_identifiers()

            if all_identifiers:
                print("Programs installed in {}:".format(opts.location))

                for program in [RioLua, LuaJIT, LuaRocks]:
                    if program.name in all_identifiers:
                        show_identifiers(all_identifiers[program.name])
            else:
                print("No programs installed in {}.".format(opts.location))
        else:
            print("Location does not exist.")

        sys.exit(0)

    global temp_dir
    temp_dir = tempfile.mkdtemp()

    # If using vsXX_YY target, set VS up by writing a .bat file calling corresponding vcvarsall.bat
    # before recursively calling hererocks, passing arguments through a temporary file using
    # --actual-argv-file because passing special characters like '^' as an argument to a batch file is not fun.
    # If using vs target, do nothing if cl.exe is in PATH and setup latest possible VS with host arch otherwise.
    # vs_32 and vs_64 targets are same as vs but force an arch.
    if (opts.lua or opts.luajit) and os.name == "nt" and argv is None and using_cl():
        if opts.target in ["vs", "vs_32", "vs_64"]:
            if program_exists("cl"):
                print("Using cl.exe found in PATH.")
            else:
                arch_bits = platform.machine() if opts.target == "vs" else opts.target
                arch = "x64" if arch_bits.endswith("64") else "x86"
                vs_versions = ["14.0", "12.0", "11.0", "10.0", "9.0"]

                for vs_version in vs_versions:
                    setup_vs_and_rerun(
                        vs_version,
                        "x86" if opts.target == "vs" and vs_version in ["9.0", "10.0"] else arch)

                sys.exit("Error: couldn't set up MSVC toolchain")
        else:
            vs_version = vs_year_to_version[opts.target[2:4]]
            arch = "x64" if opts.target.endswith("64") else "x86"
            setup_vs_and_rerun(vs_version, arch)
            sys.exit("Error: couldn't set up MSVC toolchain")

    start_dir = os.getcwd()
    opts.location = os.path.abspath(opts.location)
    opts.downloads = os.path.abspath(opts.downloads)

    if opts.builds is not None:
        opts.builds = os.path.abspath(opts.builds)

    identifiers = get_installed_identifiers()
    identifiers_changed = False

    if not os.path.exists(opts.location):
        os.makedirs(opts.location)

    if opts.lua:
        if "LuaJIT" in identifiers:
            del identifiers["LuaJIT"]

        identifiers_changed = RioLua(opts.lua).update_identifiers(identifiers)
        os.chdir(start_dir)

    if opts.luajit:
        if "lua" in identifiers:
            del identifiers["lua"]

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
    sys.exit(0)

if __name__ == "__main__":
    main()
