# README



## Deployment on OpenWhisk



To deploy your project on OpenWhisk, follow these steps:



### 1. Prepare the Project



Use the JAR file from this [link](#) or follow the steps below:



1. Create a Maven project. The project should be named `copy_files_and_pom.xml`.

2. Build the project using Maven:

```bash
	mvn clean package
```


### 2. Test the Function



#### Delete an Action



To delete an action, use the following command:
```bash
wsk -i action delete loginChecker
```


#### Create an Action



To create an action, use the following command:



```bash

wsk -i action create loginChecker target/check_login-1.0-SNAPSHOT.jar --main faas.LoggedInChecker
```


#### Check if the Action Exists



To check if the action exists, use:



```bash

wsk -i list
```


#### View Logs of the Last Invocation





```bash
wsk activation logs --last
```


### Manual Testing



#### Input



In the `test` folder, there is an `inputGenerator` for the function. You can change the values as needed. For the token, three states exist:



- `null`

- `invalid`

- `valid`



A sample input is also available in the folder.