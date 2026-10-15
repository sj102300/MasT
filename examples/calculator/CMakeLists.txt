cmake_minimum_required(VERSION 3.20)
project(calculator CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(calculator_lib STATIC
    src/calculator.cpp
    src/string_utils.cpp
)
target_include_directories(calculator_lib PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

add_executable(calculator_app src/main.cpp)
target_link_libraries(calculator_app PRIVATE calculator_lib)
