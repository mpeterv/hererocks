package = "hererocks-test"
version = "scm-1"
source = {
   url = "git://github.com/luarocks/hererocks"
}
description = {
   summary = "A test rock for hererocks",
   detailed = "A test rock for hererocks",
   homepage = "https://github.com/luarocks/hererocks",
   license = "MIT <http://opensource.org/licenses/MIT>"
}
dependencies = {
   "lua >= 5.1, < 5.4"
}
build = {
   type = "builtin",
   modules = {
      ["hererocks.test"] = "test/test.lua"
   },
   install = {
      bin = {
         ["hererocks-test"] = "test/hererocks-test.lua"
      }
   },
   copy_directories = {}
}
