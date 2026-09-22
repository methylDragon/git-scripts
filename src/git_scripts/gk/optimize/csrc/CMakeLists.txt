cmake_minimum_required(VERSION 3.18)
project(gk_nsfw_nofollow LANGUAGES C)

add_library(gk_nsfw_nofollow SHARED gk_nsfw_nofollow.c)
set_target_properties(gk_nsfw_nofollow PROPERTIES
    C_STANDARD 11
    C_STANDARD_REQUIRED ON
    POSITION_INDEPENDENT_CODE ON
    OUTPUT_NAME "gk_nsfw_nofollow"
)
target_compile_options(gk_nsfw_nofollow PRIVATE -O2 -Wall -Wextra)
target_link_libraries(gk_nsfw_nofollow PRIVATE ${CMAKE_DL_LIBS})
