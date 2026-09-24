cmake_minimum_required(VERSION 3.18)
project(gk_preload_shim LANGUAGES C)

add_library(gk_preload_shim SHARED gk_preload_shim.c)
set_target_properties(gk_preload_shim PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED ON
    POSITION_INDEPENDENT_CODE ON
    OUTPUT_NAME "gk_preload_shim"
)
target_compile_options(gk_preload_shim PRIVATE -O2 -Wall -Wextra)
target_link_libraries(gk_preload_shim PRIVATE ${CMAKE_DL_LIBS})
install(TARGETS gk_preload_shim LIBRARY DESTINATION .)

