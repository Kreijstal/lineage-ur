cmake_minimum_required(VERSION 3.22.1)
project(LineageSwiftShaderCheck LANGUAGES C CXX)

set(SWIFTSHADER_SOURCE "" CACHE PATH "Separate patched upstream SwiftShader checkout")
if(NOT EXISTS "${SWIFTSHADER_SOURCE}/src/Reactor/LLVMJIT.cpp")
    message(FATAL_ERROR "Set SWIFTSHADER_SOURCE to the patched upstream checkout")
endif()

# Exercise only the JIT backend, without downloading glslang or test submodules.
set(REACTOR_BACKEND LLVM-System CACHE STRING "" FORCE)
set(SWIFTSHADER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_BENCHMARKS OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_PVR OFF CACHE BOOL "" FORCE)
set(BUILD_VULKAN_WRAPPER OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_WSI_XCB OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_WSI_WAYLAND OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_WARNINGS_AS_ERRORS ON CACHE BOOL "" FORCE)
set(REACTOR_VERIFY_LLVM_IR ON CACHE BOOL "" FORCE)
add_subdirectory("${SWIFTSHADER_SOURCE}" swiftshader EXCLUDE_FROM_ALL)

find_package(GTest REQUIRED CONFIG)
find_package(Threads REQUIRED)
add_executable(LineageSwiftShaderReactorTests
    "${SWIFTSHADER_SOURCE}/tests/ReactorUnitTests/main.cpp"
    "${SWIFTSHADER_SOURCE}/tests/ReactorUnitTests/ReactorSIMD.cpp"
    "${SWIFTSHADER_SOURCE}/tests/ReactorUnitTests/ReactorUnitTests.cpp")
target_compile_features(LineageSwiftShaderReactorTests PRIVATE cxx_std_17)
target_link_libraries(LineageSwiftShaderReactorTests PRIVATE
    ReactorLLVM GTest::gtest Threads::Threads ${CMAKE_DL_LIBS})
