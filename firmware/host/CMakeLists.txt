# The deck's screens drawn on the host: firmware/idf/main/ui.c and the device
# core, rendered by LVGL into a 1280 x 720 RGB565 buffer in place of the
# panel. `python -m sim.parity` drives it to compare every screen with the
# simulator; scripts/test-screens.sh fetches LVGL, builds this, and runs that.
#
#   cmake -S firmware/host -B build/host -DLVGL_DIR=<LVGL v9.5.0 source tree>
#   cmake --build build/host
#
# Not an ESP-IDF project, and not part of firmware/CMakeLists.txt, since it
# needs the LVGL sources.
cmake_minimum_required(VERSION 3.16)
project(helm_screens C)

set(LVGL_DIR "" CACHE PATH "LVGL source tree, at the version the deck's board package pins (v9.5.0)")
option(HELM_TOUCH_KEYS "Draw the on-screen keys, as the deck's default build does (the simulator has none)" OFF)

if(NOT EXISTS "${LVGL_DIR}/lvgl.h")
    message(FATAL_ERROR "set LVGL_DIR to an LVGL v9.5.0 source tree (scripts/test-screens.sh fetches one)")
endif()

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# LVGL itself, with lv_conf.h from this directory. Sources for features the
# configuration leaves off compile to nothing.
file(GLOB_RECURSE LVGL_SOURCES CONFIGURE_DEPENDS "${LVGL_DIR}/src/*.c")
add_library(lvgl STATIC ${LVGL_SOURCES})
target_include_directories(lvgl PUBLIC "${LVGL_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}")
target_compile_definitions(lvgl PUBLIC LV_CONF_INCLUDE_SIMPLE)

add_subdirectory(../core core)

add_executable(helm_screens screens.c ../idf/main/ui.c)
target_include_directories(helm_screens PRIVATE ../idf/main "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(helm_screens PRIVATE helm_core lvgl)
set_target_properties(helm_screens PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)
# As firmware/idf/main builds ui.c.
target_compile_options(helm_screens PRIVATE -Wall -Wextra -Werror)
if(HELM_TOUCH_KEYS)
    target_compile_definitions(helm_screens PRIVATE CONFIG_HELM_TOUCH_KEYS=1)
endif()
