from __future__ import annotations
from enum import Enum
from typing import Optional


class CppDependencyConfig:
    def __init__(
        self,
        docker_img: str,
        cmake_package: str | None,
        cmake_libs: str,
        cmake_dir: Optional[str] = None,
        runtime_paths: Optional[list[str]] = None,
    ):
        self.docker_img = docker_img
        self.cmake_package = cmake_package
        self.cmake_dir = cmake_dir
        self.cmake_libs = cmake_libs
        self.runtime_paths = runtime_paths or []


class CppDependencies(str, Enum):
    """
    Enum for C++ dependencies used in the benchmarks.
    """

    SDK = "sdk"
    RUNTIME = "runtime"
    TORCH = "torch"
    OPENCV = "opencv"
    LIBJPEG_TURBO = "libjpeg-turbo"
    IGRAPH = "igraph"
    BOOST = "boost"
    HIREDIS = "hiredis"

    @staticmethod
    def _dependency_dictionary() -> dict[str, CppDependencyConfig]:
        return {
            CppDependencies.SDK: CppDependencyConfig(
                docker_img="dependencies-sdk.aws.cpp.all",
                cmake_package="AWSSDK",
                cmake_libs="${AWSSDK_LINK_LIBRARIES}",
                runtime_paths=["/opt/lib64/libaws*", "/opt/lib64/libs2n*"],
            ),
            CppDependencies.RUNTIME: CppDependencyConfig(
                docker_img="dependencies-runtime.aws.cpp.all",
                cmake_package="aws-lambda-runtime",
                cmake_libs="AWS::aws-lambda-runtime",
                # Compiled statically, no need to copy shared libraries.
                runtime_paths=[],
            ),
            CppDependencies.TORCH: CppDependencyConfig(
                docker_img="dependencies-torch.aws.cpp.all",
                cmake_package="Torch",
                cmake_libs="${TORCH_LIBRARIES} -lm",
                cmake_dir="${TORCH_INCLUDE_DIRS}",
                runtime_paths=["/opt/libtorch"],
            ),
            CppDependencies.OPENCV: CppDependencyConfig(
                docker_img="dependencies-opencv.aws.cpp.all",
                cmake_package="OpenCV",
                cmake_libs="${OpenCV_LIBS}",
                cmake_dir="${OpenCV_INCLUDE_DIRS}",
                runtime_paths=["/opt/opencv"],
            ),
            CppDependencies.LIBJPEG_TURBO: CppDependencyConfig(
                docker_img="dependencies-libjpeg-turbo.aws.cpp.all",
                cmake_package=None,
                cmake_libs="/opt/libjpeg-turbo/lib64/libturbojpeg.a",
                cmake_dir="/opt/libjpeg-turbo/include",
                runtime_paths=["/opt/libjpeg-turbo"],
            ),
            CppDependencies.IGRAPH: CppDependencyConfig(
                docker_img="dependencies-igraph.aws.cpp.all",
                cmake_package="igraph",
                cmake_libs="igraph::igraph",
                # Compiled statically, no need to copy shared libraries.
                runtime_paths=[],
            ),
            CppDependencies.BOOST: CppDependencyConfig(
                docker_img="dependencies-boost.aws.cpp.all",
                cmake_package="Boost",
                cmake_libs="${Boost_LIBRARIES}",
                cmake_dir="${Boost_INCLUDE_DIRS}",
                runtime_paths=["/opt/lib/libboost*"],
            ),
            CppDependencies.HIREDIS: CppDependencyConfig(
                docker_img="dependencies-hiredis.aws.cpp.all",
                cmake_package="hiredis",
                cmake_libs="hiredis::hiredis",
                runtime_paths=["/opt/lib/libhiredis*"],
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

        find_package_cmd =  ""
        if dependency_config.cmake_package:
            find_package_cmd = """
            find_package({cmake_package} REQUIRED)
            """.format(
                cmake_package=dependency_config.cmake_package,
            )

        return (
            find_package_cmd + (
                ""
                if not dependency_config.cmake_dir
                else """
            target_include_directories(${{PROJECT_NAME}} PRIVATE {cmake_dir})
        """.format(
                    cmake_dir=dependency_config.cmake_dir
                )
            )
            + """
            target_link_libraries(${{PROJECT_NAME}} PRIVATE {cmake_libs})
        """.format(
                cmake_libs=dependency_config.cmake_libs
            )
        )

    @staticmethod
    def get_required_dependencies(
        cpp_dependencies: list[CppDependencies],
    ) -> list[CppDependencies]:
        """
        Determine full set of required dependencies including core dependencies.

        Core dependencies (always included):
        - SDK: AWS SDK for S3, DynamoDB, SQS
        - RUNTIME: AWS Lambda C++ Runtime (compiled statically)
        - BOOST: Core C++ utility library
        - HIREDIS: Redis client (used by new storage wrappers)

        Args:
            cpp_dependencies: List of explicit dependencies from benchmark config

        Returns:
            Complete list of dependencies needed for the benchmark
        """
        deps = {
            CppDependencies.SDK,
            CppDependencies.RUNTIME,
            CppDependencies.BOOST,
            CppDependencies.HIREDIS,
        }

        deps.update(cpp_dependencies)

        return list(deps)

    @staticmethod
    def generate_dockerfile(
        cpp_dependencies: list[CppDependencies], dockerfile_template: str
    ) -> str:
        """
        Generate a custom Dockerfile for C++ Lambda functions with selective dependencies.

        This reads a Dockerfile template and replaces placeholders with:
        1. FROM statements for required dependency images
        2. COPY statements to only copy needed libraries from each dependency.

        Args:
            cpp_dependencies: List of explicit dependencies from benchmark config
            dockerfile_template: Content of Dockerfile.function template

        Returns:
            Complete Dockerfile content with placeholders replaced
        """
        required_deps = CppDependencies.get_required_dependencies(cpp_dependencies)
        dep_dict = CppDependencies._dependency_dictionary()

        from_statements = []
        for dep in required_deps:
            config = dep_dict[dep]
            # Use the short name (e.g., "sdk") as the stage alias
            from_statements.append(f"FROM ${{BASE_REPOSITORY}}:{config.docker_img} as {dep.value}")

        copy_statements = []
        for dep in required_deps:
            config = dep_dict[dep]
            for path in config.runtime_paths:
                """
                Two cases: copy entire directory or copy all files with a wildcard.
                """
                if "*" in path:
                    dest_dir = path.rsplit("/", 1)[0]
                    copy_statements.append(f"COPY --from={dep.value} {path} {dest_dir}/")
                else:
                    copy_statements.append(f"COPY --from={dep.value} {path} {path}")

        dockerfile = dockerfile_template.replace(
            "{{DEPENDENCY_IMAGES}}", "\n".join(from_statements)
        )
        dockerfile = dockerfile.replace("{{DEPENDENCY_COPIES}}", "\n".join(copy_statements))

        return dockerfile
