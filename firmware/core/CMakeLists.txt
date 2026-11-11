# The Helm device core: portable C11, no framework headers. It also holds the
# pure logic behind the physical controls (lights, debounce, the knob's seesaw
# protocol, the chime tone), so the host tests cover it.
#
# Inside an ESP-IDF project (ESP_PLATFORM is set) this directory is a
# component: add it to EXTRA_COMPONENT_DIRS or copy it under components/, and
# REQUIRES helm_core (the component takes its directory's name, so name the
# directory helm_core or adjust REQUIRES). Anywhere else it is a static
# library named helm_core; firmware/CMakeLists.txt uses it that way for the
# host tests.
set(HELM_CORE_SRCS
    helm_frame.c
    helm_model.c
    helm_jsonw.c
    helm_event.c
    helm_deck.c
    helm_lights.c
    helm_controls.c
    helm_knob.c
    helm_tone.c
)

if(ESP_PLATFORM)
    idf_component_register(SRCS ${HELM_CORE_SRCS} INCLUDE_DIRS ".")
else()
    add_library(helm_core STATIC ${HELM_CORE_SRCS})
    target_include_directories(helm_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
    set_target_properties(helm_core PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF)
    # The light pulse and the chime tone use sinf (libm is its own library on Linux).
    find_library(HELM_LIBM m)
    if(HELM_LIBM)
        target_link_libraries(helm_core PUBLIC ${HELM_LIBM})
    endif()
endif()
