# Fission

### Requirements
- docker
- kubeclt > 1.18.4
- miniukube > 1.11.0
- helm > 3.2.4

### Run
```sh 
$ python sebs.py --repetitions 1 test_invoke 010.sleep ../local/tests/ test config/fission.json
```

### Implemented features: 
- automatic Fission instalation if nessesary
- Fission environment preparation
- config for Fission
- packaging code with support requirement file (python)
- deploying function (python, node)
- adding http trigger
- cache usage implementation
- automatic sync function invoke
- measurement executions times
- if cold start checking
- storage service usage - Minio
- wrapper-handler for Python, Node
- wrapper-storage for Python
- cleanup after benchmark

### About
Fission has very simplified [documentation][df1]. It is difficult to find detailed information that goes beyond the deploy hello world function. Many important functionalities are omitted and others have been implemented in a very non-intuitive way (limiting the display of function logs to 20 lines). *Fission* functions as a black box, making it difficult to extract information about what is happening with the function being performed. The documentation does not explain the folder structure on which the function is deployed. *Fission* does not require configuration in the form of login data because in our case it is run locally. The user does not receive any statistics regarding the performance of the function, therefore the only certain benchmarks are time measures. *Fission* works on *Kubernetes* so it is possible to access the metrics for the given application. However, these statistics will apply to the specific pod / pods and not the function itself. In addition, these are other than those required by the statistics interface from other benchmarks (*AWS*). It is possible to obtain records from *Prometheus* existing with *Fission* in the same napespace but we were unable to obtain it therefore, the values for memory benchmarks have not been implemented.  *Fission* does not provide access to storage service, which is why we implemented storage based on *MinIO*. *Fission* uses *Flask* to handle requests in *Python*. 

### Package
If the function you want to place on fission consists of only one source file containing functions, you can create functions using this file directly. However, if our function requires additional resources (for example, requirements.txt, other file, other script) we must create a package in the form of a zip archive. To install the packages contained in the.txt requirements, the zip package must include a build script (for example, `build.sh`) that ensures that the package installation starts. The path to this file must be given when creating the package using the --buildcmd flag.


This is an example of the `build.sh` file using environment variables inside *Fission* namespace.

```sh 
pip3 install -r ${SRC_PKG}/requirements.txt -t ${SRC_PKG} && cp -r ${SRC_PKG} ${DEPLOY_PKG}
```

[df1]: <https://docs.fission.io/docs/>
