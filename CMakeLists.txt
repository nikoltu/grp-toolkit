cmake_minimum_required(VERSION 3.16)
project(scgrp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

# ---- header-only decoder library (drop-in for any engine) ----
add_library(scgrp INTERFACE)
target_include_directories(scgrp INTERFACE ${CMAKE_CURRENT_SOURCE_DIR}/include)

# ---- headless CLI: grp/dds/anim -> PNG (no SDL needed) ----
add_executable(grp2png src/grp2png.cpp)
target_link_libraries(grp2png PRIVATE scgrp)

# ---- SDL2 viewer (optional) ----
find_package(SDL2 QUIET)
if(SDL2_FOUND)
  add_executable(viewer src/viewer.cpp)
  target_link_libraries(viewer PRIVATE scgrp SDL2::SDL2)
  message(STATUS "SDL2 found — building 'viewer'")
else()
  # fall back to pkg-config (some distros ship no SDL2 CMake config)
  find_package(PkgConfig QUIET)
  if(PkgConfig_FOUND)
    pkg_check_modules(SDL2PC QUIET sdl2)
  endif()
  if(SDL2PC_FOUND)
    add_executable(viewer src/viewer.cpp)
    target_include_directories(viewer PRIVATE ${SDL2PC_INCLUDE_DIRS})
    target_link_libraries(viewer PRIVATE scgrp ${SDL2PC_LIBRARIES})
    message(STATUS "SDL2 (pkg-config) found — building 'viewer'")
  else()
    message(STATUS "SDL2 not found — skipping 'viewer' (grp2png still builds)")
  endif()
endif()
