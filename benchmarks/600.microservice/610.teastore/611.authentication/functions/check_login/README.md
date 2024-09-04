
# README

## Deployment on OpenWhisk

To deploy your project on OpenWhisk, follow these steps:

### 1. Create the JAR file

Use the JAR file from this [link](https://github.com/spcl/serverless-benchmarks/tree/microservice_teastore_becnhmarks/benchmarks/600.microservice/610.teastore/611.authentication/functions/check_login/output) or follow the steps below:

1. Create a Maven project. The project should be named `check_login`.
2. Replace the `src` folder of the project with src folder of in this [link](https://github.com/spcl/serverless-benchmarks/tree/microservice_teastore_becnhmarks/benchmarks/600.microservice/610.teastore/611.authentication/functions/check_login/output)
3. Build the project using Maven:

```bash
mvn clean package
```

### 2. Run the Function on OpenWhisk

- If you do not have OpenWhisk, follow [this](https://openwhisk.apache.org/documentation.html) instruction.

- Create A Java-based action: [link(https://github.com/apache/openwhisk/blob/master/docs/actions-java.md)
  
- Invoke the action with different parameter formats: [link](https://github.com/apache/openwhisk/blob/master/docs/parameters.md)

Below are example commands you can use quickly:

#### Create the Action

To create loginChecker action, use the following command:

```bash
wsk -i action create loginChecker target/check_login-1.0-SNAPSHOT.jar --main faas.LoggedInChecker
```

If the function already exists, you can delete it using the following command:

```bash
wsk -i action delete loginChecker
```

#### Check if the Action is Created

```bash
wsk -i action list
```

#### Invoke the Action

```bash
wsk -i action invoke --result loginChecker --param-file src/test/java/sample_input_valid_token.txt
```
* check Input section of readme for more detail

#### View Logs of the Last Invocation

(If there is an error in invocation)

```bash
wsk activation logs --last
```

#### Input

In the `test` folder, there is an `inputGenerator` for the function. You can change the values as needed. For the token, three states exist:

- `null`
- `invalid`
- `valid`

A sample input is also available in the folder.

### About the Code

In the source code of TeaStore, the token is checked in the validate function of ShaSecurityProvider class and then set to null. In each operation which check validity of blob, uses the secure function in ShaSecurityProvider, which subsequently sets a valid token.

