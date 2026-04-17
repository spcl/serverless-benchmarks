# Copyright 2020-2025 ETH Zurich and the SeBS authors. All rights reserved.
"""C++ dependencies supported in SeBS benchmarks."""

from __future__ import annotations
from enum import Enum
from typing import Optional


class CppDependencyConfig:
    """Configuration of each C++ dependency."""

    def __init__(
        self,
        docker_img: str,
        cmake_package: str | None,
        cmake_libs: str,
        cmake_dir: Optional[str] = None,
        runtime_paths: Optional[list[str]] = None,
        cmake_required: Optional[str] = None,
        cmake_definitions: Optional[str] = None,
    ):
        """Initializes a new C++ dependency configuration.

        Args:
            docker_img: Docker image providing the dependency
            cmake_package: Name of CMake package to find
            cmake_libs: Variable or list of libraries to link against in CMake
            cmake_dir: Additional include directory to add in CMake (if not provided by the package)
            runtime_paths: Paths to dynamic libraries that should be copied with function.
            cmake_definitions: Preprocessor definitions to set when this dependency is used.
        """
        self.docker_img = docker_img
        self.cmake_package = cmake_package
        self.cmake_dir = cmake_dir
        self.cmake_libs = cmake_libs
        self.cmake_required = cmake_required
        self.cmake_definitions = cmake_definitions
        self.runtime_paths = runtime_paths or []


class CppDependencies(str, Enum):
    """C++ dependencies used in the benchmarks.

    Attributes:
        SDK: AWS C++ SDK
        RUNTIME: AWS C++ Lambda Runtime
        TORCH: Torch C++ API
        OPENCV: OpenCV
        LIBJPEG_TURBO: Libjpeg-turbo (used in 210.thumbnailer)
        IGRAPH: Graph library used in 50* benchmarks
        BOOST: Standard Boost libraries
        HIREDIS: Redis client library used by storage wrappers
    """

    SDK = "sdk"
    RUNTIME = "runtime"
    TORCH = "torch"
    OPENCV = "opencv"
    LIBJPEG_TURBO = "libjpeg-turbo"
    IGRAPH = "igraph"
    BOOST = "boost"
    HIREDIS = "hiredis"
    RAPIDJSON = "rapidjson"

    @staticmethod
    def _dependency_dictionary() -> dict[str, CppDependencyConfig]:
        """Maps dependency enum to its configuration details.

        Returns:
            Full CMake and Docker configuration for each dependency,
            used for generating Dockerfiles and CMakeLists.
        """
        return {
            CppDependencies.SDK: CppDependencyConfig(
                docker_img="dependencies-sdk.aws.cpp.all",
                cmake_package="AWSSDK",
                cmake_libs="${AWSSDK_LINK_LIBRARIES}",
                runtime_paths=["/opt/lib64/libaws*", "/opt/lib64/libs2n*"],
                cmake_required="s3",
                cmake_definitions="SEBS_USE_AWS_SDK",
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
            CppDependencies.RAPIDJSON: CppDependencyConfig(
                docker_img="dependencies-rapidjson.aws.cpp.all",
                cmake_package=None,
                cmake_libs="",
                cmake_dir="/opt/include",
                runtime_paths=[],
            ),
        }

    @staticmethod
    def deserialize(val: str) -> CppDependencies:
        """Deserialize enum from string.

        Args:
            val: dependency name as string (e.g., "sdk", "torch")

        Returns:
            Dependency enum member corresponding to the input string.

        Raises:
            Exception: for unknown dependency types
        """
        for member in CppDependencies:
            if member.value == val:
                return member
        raise Exception(f"Unknown C++ dependency type {val}")

    @staticmethod
    def to_cmake_list(dependency: CppDependencies) -> str:
        """Returns the full CMake integration for the given C++ dependency.

        Args:
            dependency: target name

        Returns:
            CMake configuration: find package, include directories, and link libraries.

        Raises:
            ValueError: if C++ dependency is unsupported (unknown)
        """
        if dependency not in CppDependencies:
            raise ValueError(f"Unknown C++ dependency {dependency}")
        dependency_config = CppDependencies._dependency_dictionary()[dependency]

        find_package_cmd = ""
        if dependency_config.cmake_package and dependency_config.cmake_required:
            find_package_cmd = """
            find_package({cmake_package} REQUIRED COMPONENTS {required})
            """.format(
                cmake_package=dependency_config.cmake_package,
                required=dependency_config.cmake_required,
            )
        elif dependency_config.cmake_package:
            find_package_cmd = """
            find_package({cmake_package})
            """.format(
                cmake_package=dependency_config.cmake_package,
            )

        link_line = (
            ""
            if not dependency_config.cmake_libs
            else """
            target_link_libraries(${{PROJECT_NAME}} PRIVATE {cmake_libs})
        """.format(
                cmake_libs=dependency_config.cmake_libs
            )
        )

        definitions_line = (
            ""
            if not dependency_config.cmake_definitions
            else """
            target_compile_definitions(${{PROJECT_NAME}} PRIVATE {cmake_definitions})
        """.format(
                cmake_definitions=dependency_config.cmake_definitions
            )
        )

        return (
            find_package_cmd
            + (
                ""
                if not dependency_config.cmake_dir
                else """
            target_include_directories(${{PROJECT_NAME}} PRIVATE {cmake_dir})
        """.format(
                    cmake_dir=dependency_config.cmake_dir
                )
            )
            + link_line
            + definitions_line
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
            CppDependencies.RUNTIME,
            CppDependencies.BOOST,
            CppDependencies.RAPIDJSON,
        }

        deps.update(cpp_dependencies)

        return list(deps)

    @staticmethod
    def generate_dockerfile(
        cpp_dependencies: list[CppDependencies],
        dockerfile_template: str,
        sebs_version: str,
        previous_version: str | None = None,
        docker_client=None,
        docker_repository: str | None = None,
    ) -> str:
        """
        Generate a custom Dockerfile for C++ Lambda functions with selective dependencies.

        This reads a Dockerfile template and replaces placeholders with:
        1. FROM statements for required dependency images
        2. COPY statements to only copy needed libraries from each dependency.

        Supports version fallback: if a dependency image doesn't exist with the current
        SeBS version, falls back to the previous major version.

        Args:
            cpp_dependencies: List of explicit dependencies from benchmark config
            dockerfile_template: Content of Dockerfile.function template
            sebs_version: Current SeBS version
            previous_version: Previous major SeBS version for fallback
            docker_client: Docker client for checking image availability
            docker_repository: Docker repository name

        Returns:
            Complete Dockerfile content with placeholders replaced
        """
        required_deps = CppDependencies.get_required_dependencies(cpp_dependencies)
        dep_dict = CppDependencies._dependency_dictionary()

        from_statements = []
        for dep in required_deps:
            config = dep_dict[dep]

            # Determine which version to use (current or previous fallback)
            version_to_use = sebs_version
            if docker_client and docker_repository and previous_version:
                current_image = f"{docker_repository}:{config.docker_img}-{sebs_version}"
                previous_image = f"{docker_repository}:{config.docker_img}-{previous_version}"

                # Try current version first
                try:
                    docker_client.images.get(current_image)
                except Exception:
                    # Current version not available, try previous version
                    try:
                        docker_client.images.get(previous_image)
                        version_to_use = previous_version
                    except Exception:
                        # Neither version available - use current and let it fail later
                        pass

            # Use the short name (e.g., "sdk") as the stage alias
            from_statements.append(
                f"FROM ${{BASE_REPOSITORY}}:{config.docker_img}-{version_to_use} as {dep.value}"
            )

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
