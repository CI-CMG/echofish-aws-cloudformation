# EchoFish AWS Cloudformation

## Building

### CU AWS Login
```bash
saml2aws login -a echofish
```

### Maven Build
```bash
mvn -Daws.profile=echofish -Daws.region=us-west-2 -Ps3 clean install 
```

### Maven Build With Integration Tests
```bash
mvn -Daws.profile=echofish -Daws.region=us-west-2 -Ps3 -Pit clean install 
```

### Creating Zipper Integration Tests

1. In the echofish-e2e-tests module add a file structure under src/test/resources/zips that matches
your ingest.zip.
1. Create a test with a class name that ends in "IT" that extends ZipperTestRunner
1. In the constructor, call super() and pass in the name of the directory created under "zips"
1. In your test you will have access to the ZipperResponse response object to get the path to a local
directory that contains the unzipped output or a local directory with the error staging data.


### Run Integration Tests In IDE

Setup default options for JUnit in IntelliJ
1. From the test dropdown at the top of the window, choose Edit Configurations
1. Select Templates -> JUnit
1. Add the following VM options to the ones listed ```-Daws.profile=echofish -Daws.region=us-west-2``` 

Build project without integration tests (listed above)

Login to AWS
```bash
saml2aws login -a echofish
```

Build project
```bash
mvn clean install
```

Change directory to E2E module
```bash
cd echofish-e2e-tests
```

Start test stack
```bash
mvn -Daws.profile=echofish -Daws.region=us-west-2 -DCF_DeployAdminResources=no -Ps3 -Pit exec:java@create-stack
```

Note: -DCF_DeployAdminResources=no prevents deployment of the admin API and UI. Omit this property to do a full deploy.

Run your tests in your IDE

Tear down test stack
```bash
mvn -Daws.profile=echofish -Daws.region=us-west-2 -Ps3 -Pit exec:java@delete-stack
```

