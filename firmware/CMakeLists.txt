# Host build of the Helm device core and its tests (not an ESP-IDF project).
#
#   cmake -S firmware -B firmware/build && cmake --build firmware/build && ctest --test-dir firmware/build
#
# scripts/test-firmware.sh runs exactly that, then the Python cross-tests.
cmake_minimum_required(VERSION 3.16)
project(helm_firmware_host C CXX)

option(HELM_SANITIZE "Build the host tests with AddressSanitizer and UBSan" ON)

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug)
endif()

set(HELM_WARNINGS -Wall -Wextra -Wpedantic -Wshadow -Wconversion -Wsign-conversion -Wstrict-prototypes -Werror)
set(HELM_CXX_WARNINGS -Wall -Wextra -Wpedantic -Werror)

if(HELM_SANITIZE)
    add_compile_options(-fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer)
    add_link_options(-fsanitize=address,undefined)
endif()

add_subdirectory(core)
target_compile_options(helm_core PRIVATE ${HELM_WARNINGS})

add_library(helm_test_support STATIC test/support.c)
target_link_libraries(helm_test_support PUBLIC helm_core)
target_compile_options(helm_test_support PRIVATE ${HELM_WARNINGS})
set_target_properties(helm_test_support PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)

add_executable(test_core test/test_core.c)
target_link_libraries(test_core PRIVATE helm_test_support)
target_compile_options(test_core PRIVATE ${HELM_WARNINGS})
set_target_properties(test_core PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)

# Driven by tests/test_firmware_core.py for byte-for-byte checks against helm/wire.
add_executable(helm_wire_tool test/helm_wire_tool.c)
target_link_libraries(helm_wire_tool PRIVATE helm_test_support)
target_compile_options(helm_wire_tool PRIVATE ${HELM_WARNINGS})
set_target_properties(helm_wire_tool PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)

# The headers must also compile as C++ (Arduino and C++ ESP-IDF code include them).
add_library(helm_cxx_headers STATIC test/cxx_headers.cpp)
target_link_libraries(helm_cxx_headers PRIVATE helm_core)
target_compile_options(helm_cxx_headers PRIVATE ${HELM_CXX_WARNINGS})
set_target_properties(helm_cxx_headers PROPERTIES CXX_STANDARD 17 CXX_STANDARD_REQUIRED ON CXX_EXTENSIONS OFF)

enable_testing()
add_test(NAME helm_core COMMAND test_core ${CMAKE_CURRENT_SOURCE_DIR}/../tests/vectors/cable_frame.txt)
