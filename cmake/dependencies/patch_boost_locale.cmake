# Boost 1.89 lists locale.hpp one level above locale/. CMake 4.5 checks TREE strictly.
set(path "${SOURCE_DIR}/libs/locale/CMakeLists.txt")
file(READ "${path}" content)
string(REPLACE "source_group(TREE \"\${CMAKE_CURRENT_SOURCE_DIR}/include/boost/locale\"" "source_group(TREE \"\${CMAKE_CURRENT_SOURCE_DIR}/include/boost\"" content "${content}")
file(WRITE "${path}" "${content}")
