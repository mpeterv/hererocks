# Changelog

## 0.20.0 (unreleased)

### New features and improvements

* Added support for LuaRocks 3.0.0 and 3.0.1. `latest` and `^` aliases now point
  to 3.0.1.
* `--show` can now be used when installing programs; all programs present
  in the given location are listed after installation is complete.

### Fixes

* `package.path` for Lua 5.3+ built with hererocks now includes `./?/init.lua`,
  just as with standard Lua.

## 0.19.0 (2018-07-11)

### New features and improvements

* Added support for Lua 5.4.0-work1 and 5.4.0-work2.
* Added support for Lua 5.3.5.
* Added patches for Lua 5.3.4:

    - `Lua crashes when building sequences with more than 2^30 elements`
    - `Table length computation overflows for sequences larger than 2^31
      elements`
    - `Memory-allocation error when resizing a table can leave it in an
      inconsistent state`

## 0.18.0 (2018-03-13)

### New features and improvements

* Added support for LuaRocks 2.4.4.
* Using `3` as version when installing LuaRocks now uses master branch of the
  LuaRocks git repo instead of `luarocks-3`.
* Added `lua_pushcclosure should not call the garbage collector when n is zero`
  patch for Lua 5.3.4.

## 0.17.0 (2017-09-13)

### New features and improvements

* Added support for LuaRocks 2.4.3.
* When installing PUC-Rio Lua from a git repo or local sources, source files
  are expected to be in root directory instead of `src`. This allows one to
  install Lua from the default Lua repo at github.com/lua/lua.

## 0.16.0 (2017-06-10)

### New features and improvements

* Added support for LuaJIT 2.0.5 and 2.1.0-beta3.
* Added fallback to a mirror for PUC-Rio Lua download.
* Added `--timeout` option for downloads.

## 0.15.0 (2017-04-02)

### New features and improvements

* When building Lua with custom cflags, hererocks now instructs LuaRocks to use
  same flags when building C modules.

## 0.14.0 (2017-01-31)

### New features and improvements

* Added support for Lua 5.3.4.

## 0.13.1 (2017-01-09)

### Fixes

* Fixed an error when setting up cl.exe and hererocks has been installed using
  a version of pip that passes `prefix/hererocks` instead of
  `prefix/hererocks-script.py` as `sys.argv[0]`.

## 0.13.0 (2016-12-22)

### New features and improvements

* Added support for LuaRocks 2.4.2.
* LuaRocks is now configured to allow using config in user home directory.
  In particular, API keys for `luarocks upload` command are now properly cached.

## 0.12.0 (2016-11-04)

### New features and improvements

* Added support for LuaRocks 2.4.1.
* Updated URL for LuaRocks downloads and default git repo.

## 0.11.0 (2016-09-10)

### New features and improvements

* Added support for LuaRocks 2.4.0.
* Added two new patches for bugs in Lua 5.3.3, try `--patch`.
* Caching of downloads now works on Unix-like systems even when `$HOME` is
  unset (#28).

## 0.10.0 (2016-07-14)

### New features and improvements

* hererocks now creates activation scripts a-la virtualenv in `<location>/bin`.
  Bash, Zsh, Dash, Fish, Csh, Batch, and PowerShell are supported.
* Lua 5.3.3 can now be patched to fix a bug (`Expression list with four or more
  expressions in a 'for' loop can crash the interpreter`), try `--patch`.

## 0.9.0 (2016-06-21)

### New features and improvements

* Added support for LuaRocks 2.0.13.

### Fixes

* Fixed occasional SHA256 mismatches when downloading LuaJIT (#27).

## 0.8.1 (2016-06-12)

### Fixes

* Fixed error when installing from non-default git repo on Windows.

## 0.8.0 (2016-06-07)

### New features and improvements

* Added support for Lua 5.3.3.

## 0.7.0 (2016-05-03)

### New features and improvements

* Windows support with automatic Visual Studio setup.
* New values for `--target` option for selecting Visual Studio version and
  target architecture.
* New `--show` option for listing programs installed in a location.
* New `--patch` option for applying official patches for bugs in Lua (#21).
* Documented `--downloads` and `--builds` options, may be useful for caching.

### Fixes

* Fixed an error when a command failed when using Python 3 (#15).
* Fixed error when running with `HOME` environment variable undefined (#24).

## 0.6.2 (2016-03-22)

### Fixes

Fixed a bug that resulted in Lua being built without compatibility flags (#14).

## 0.6.1 (2016-03-22) [yanked]

## 0.6.0 (2016-03-20)

### Breaking changes

* `hererocks --luajit 2.1` now installs LuaJIT 2.1.0-beta2 instead of
  using v2.1 git branch. Use `hererocks --luajit @v2.1` to get old behaviour.

### New features and improvements

* LuaJIT versions 2.1.0-beta1 - 2.1.0-beta2 are now supported.
* Lua is now built manually (`make` is not run).
* OS X 10.4+ support for Lua 5.1.0 - 5.1.2.
* SHA256 checksums for downloaded archives are now verified (#13).
* `--no-readline` flag for building Lua without readline library.
* Lua archives are now downloaded using HTTPS.

### Fixes

* `luajit.h` is installed for LuaJIT (#11, #12).
* `jit.*` modules work correctly for LuaJIT 2.0.1.

## 0.5.0 (2016-01-11)

### New features and improvements

LuaRocks 2.3.0 is now supported.

## 0.4.0 (2016-01-03)

### New features and improvements

* Documented --no-git-cache option.

### Fixes

* Fixed error when installing Lua 5.1 on OS X, thanks to @xpol.

## 0.3.1 (2015-12-22)

### Fixes

* Fetch LuaJIT from GitHub mirror archive to avoid 'Connection refused' errors
  when installing it on Travis.

## 0.3.0 (2015-12-19)

### New features and improvements

* LuaRocks versions 2.0.8 - 2.0.12 are now supported.
* `--compat=none` now turns off Lua 5.0 compatibility options when installing
  Lua 5.1
* Default git repos are cached.
* New `--cflags` option for adding custom compiler flags when compiling Lua and
  LuaJIT.

### Fixes

* LuaJIT `jit.*` modules are now properly installed.

## 0.2.0 (2015-12-02)

### New features and improvements

* Lua 5.3.2 is now supported.
* Versions of installed programs are showed in status messages.

## 0.1.0 (2015-11-29)

### Breaking changes

* Removed `-c` and `-t` shortcuts.

### New features and improvements

* `--verbose` flag that prints commands hererocks runs.
* hererocks now checks if requested versions are already installed, and skips
  installation in that case. Override using `--ignore-installed/-i` flag.
* PUC Rio Lua now has default git URI.

### Fixes

* Installing from a git branch now works with newer git versions.

## 0.0.3 (2015-08-14)

The first release.
