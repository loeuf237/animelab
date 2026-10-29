cmake_minimum_required(VERSION 3.22.1)
project(animelab_quickjs LANGUAGES C CXX)
set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 11)
if(NOT EXISTS "${UPSTREAM_ROOT}/quickjs/common/native/quickjs/quickjs.c")
  message(FATAL_ERROR "Run prepareQuickJsSources before compiling")
endif()
file(GLOB_RECURSE sources CONFIGURE_DEPENDS "${UPSTREAM_ROOT}/quickjs/common/native/*.c"
  "${UPSTREAM_ROOT}/quickjs/common/native/*.cpp")
add_library(quickjs SHARED ${sources})
file(STRINGS "${UPSTREAM_ROOT}/quickjs/common/native/quickjs/VERSION" quickjs_version LIMIT_COUNT 1)
target_compile_definitions(quickjs PRIVATE CONFIG_VERSION="${quickjs_version}")
target_compile_options(quickjs PRIVATE -fstrict-aliasing -Os -fomit-frame-pointer -fvisibility=hidden
  "$<$<COMPILE_LANGUAGE:CXX>:-include>" "$<$<COMPILE_LANGUAGE:CXX>:functional>")
# Context.h uses std::function without including <functional>. Pre-including
# the standard header fixes compilation without editing the pinned sources.
target_link_options(quickjs PRIVATE "-Wl,-z,max-page-size=16384" "-Wl,-z,common-page-size=16384")
target_link_libraries(quickjs PRIVATE m log)
