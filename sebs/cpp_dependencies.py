from __future__ import annotations
from enum import Enum
from typing import Optional

class CppDependencyConfig:
    def __init__(self, docker_img: str, cmake_package: str, cmake_libs: str, cmake_dir: Optional[str] = None):
        self.docker_img = docker_img
        self.cmake_package = cmake_package
        self.cmake_dir = cmake_dir
        self.cmake_libs = cmake_libs

class CppDependencies(str, Enum):
    """
    Enum for C++ dependencies used in the benchmarks.
    """
    TORCH = "torch"
    OPENCV = "opencv"
    IGRAPH = "igraph"
    BOOST = "boost"
    HIREDIS = "hiredis"
    
    @staticmethod
    def _dependency_dictionary() -> dict[str, CppDependencyConfig]:
        return {
            CppDependencies.TORCH: CppDependencyConfig(
                docker_img="dependencies-torch.aws.cpp.all",
                cmake_package="Torch",
                cmake_libs="${TORCH_LIBRARIES} -lm",
                cmake_dir="${TORCH_INCLUDE_DIRS}"
            ),
            CppDependencies.OPENCV: CppDependencyConfig(
                docker_img="dependencies-opencv.aws.cpp.all",
                cmake_package="OpenCV",
                cmake_libs="${OpenCV_LIBS}",
                cmake_dir="${OpenCV_INCLUDE_DIRS}"
            ),
            CppDependencies.IGRAPH: CppDependencyConfig(
                docker_img="dependencies-igraph.aws.cpp.all",
                cmake_package="igraph",
                cmake_libs="igraph::igraph"
            ),
            CppDependencies.BOOST: CppDependencyConfig(
                docker_img="dependencies-boost.aws.cpp.all",
                cmake_package="Boost",
                cmake_libs="${Boost_LIBRARIES}",
                cmake_dir="${Boost_INCLUDE_DIRS}"
            ),
            CppDependencies.HIREDIS: CppDependencyConfig(
                docker_img="dependencies-hiredis.aws.cpp.all",
                cmake_package="hiredis",
                cmake_libs="hiredis::hiredis"
            ),

        }

    @staticmethod
    def deserialize(val: str) -> CppDependencies:
        for member in CppDependencies:
            if member.value == val:
                return member
        raise Exception(f"Unknown C++ dependency type {val}")
    
    @staticmethod
    def to_cmake_list(dependency: CppDependencies) -> str:
        """
        Returns the CMake target for the given C++ dependency.
        """
        if dependency not in CppDependencies:
            raise ValueError(f"Unknown C++ dependency {dependency}")
        dependency_config = CppDependencies._dependency_dictionary()[dependency]
        return \
        '''
            find_package({cmake_package} REQUIRED)
        '''.format(
            cmake_package=dependency_config.cmake_package,
        ) + ("" if not dependency_config.cmake_dir else \
        '''
            target_include_directories(${{PROJECT_NAME}} PRIVATE {cmake_dir})
        '''.format(
            cmake_dir=dependency_config.cmake_dir
        )) + \
        '''
            target_link_libraries(${{PROJECT_NAME}} PRIVATE {cmake_libs})
        '''.format(
            cmake_libs=dependency_config.cmake_libs
        )
