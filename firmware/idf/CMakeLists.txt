# The Helm deck firmware: an ESP-IDF app for the Waveshare
# ESP32-P4-WIFI6-Touch-LCD-5. Build with `idf.py build` from this directory
# (see README.md for the pinned ESP-IDF version).
cmake_minimum_required(VERSION 3.16)

# The portable device core (frame, model, events, deck logic) is a component
# named after its directory: `core`.
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../core")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(helm)
