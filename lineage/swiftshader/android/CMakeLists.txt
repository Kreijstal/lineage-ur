cmake_minimum_required(VERSION 3.22.1)
project(LineageSwiftShaderAndroid LANGUAGES C CXX ASM)

foreach(required SWIFTSHADER_SOURCE ANDROID_SOURCE TERMUX_PREFIX)
    if(NOT IS_DIRECTORY "${${required}}")
        message(FATAL_ERROR "Set ${required} to its source/staging directory")
    endif()
endforeach()
set(REACTOR_BACKEND LLVM-System CACHE STRING "" FORCE)
set(SWIFTSHADER_ANDROID_PLATFORM ON CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_BENCHMARKS OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_PVR OFF CACHE BOOL "" FORCE)
set(BUILD_VULKAN_WRAPPER OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_WSI_XCB OFF CACHE BOOL "" FORCE)
set(SWIFTSHADER_BUILD_WSI_WAYLAND OFF CACHE BOOL "" FORCE)
set(REACTOR_VERIFY_LLVM_IR ON CACHE BOOL "" FORCE)
set(SWIFTSHADER_WARNINGS_AS_ERRORS ON CACHE BOOL "" FORCE)
set(SWIFTSHADER_LLVM_LIBRARY "${TERMUX_PREFIX}/lib/libLLVM.so" CACHE FILEPATH "" FORCE)
set(SWIFTSHADER_LLVM_INCLUDE_DIR "${TERMUX_PREFIX}/include" CACHE PATH "" FORCE)
set(SWIFTSHADER_LLVM_PACKAGE_VERSION "21.1.8" CACHE STRING "" FORCE)

include_directories(
    "${ANDROID_SOURCE}/hardware/libhardware/include_all"
    "${ANDROID_SOURCE}/system/core/libcutils/include"
    "${ANDROID_SOURCE}/system/core/libsystem/include"
    "${ANDROID_SOURCE}/system/core/libsync/include"
    "${ANDROID_SOURCE}/system/logging/liblog/include"
    "${ANDROID_SOURCE}/frameworks/native/libs/nativebase/include"
    "${ANDROID_SOURCE}/frameworks/native/libs/nativewindow/include"
    "${ANDROID_SOURCE}/frameworks/native/vulkan/include"
    "${CMAKE_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/generated")
execute_process(COMMAND python3 "${SWIFTSHADER_SOURCE}/src/commit_id.py"
    gen "${CMAKE_BINARY_DIR}/generated/commit.h" COMMAND_ERROR_IS_FATAL ANY)
add_subdirectory("${SWIFTSHADER_SOURCE}" swiftshader EXCLUDE_FROM_ALL)
