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

## MVN Central
The Maven Central build will end up here:
```commandline
https://repo1.maven.org/maven2/io/github/ci-cmg/echofish/
```
## Manually copying files between buckets
This command copies a directory down from your dev bucket then uploads it to the NODD bucket:
```
export copy_path=level_1/Bell_M._Shimada/SH1507/ && aws --profile nodd-zarr --no-sign-request s3 sync s3://rudy-dev-echofish2-118234403147-echofish-dev-output/$copy_path temp-bucket-copy/$copy_path && aws --profile nodd-zarr s3 sync temp-bucket-copy/$copy_path s3://noaa-wcsd-zarr-pds/$copy_path
```
Just replace the variable at the beginning of the command and set up the “nodd-zarr” profile with the creds. I copied level 1 and 2 of SH1507 over.

## Copying files with NODD Credentials
To copy files from a public bucket into the NODD bucket you will need an intermediate step. The NODD credentials are locked down preventing GET requests to any other bucket.
```commandline
export copy_path=level_1/Bell_M._Shimada/SH1507/ && aws --profile nodd-zarr --no-sign-request s3 sync s3://rudy-dev-echofish2-118234403147-echofish-dev-output/$copy_path temp-bucket-copy/$copy_path && aws --profile nodd-zarr s3 sync temp-bucket-copy/$copy_path s3://noaa-wcsd-zarr-pds/$copy_path
```

"SaKe2015-D20150719-T190837.raw",
"SaKe2015-D20150719-T191613.raw",
"SaKe2015-D20150719-T192213.raw",
"SaKe2015-D20150719-T192812.raw",
"SaKe2015-D20150719-T193412.raw",
"SaKe2015-D20150719-T193443.raw",
"SaKe2015-D20150719-T194042.raw",
"SaKe2015-D20150719-T194642.raw",
"SaKe2015-D20150719-T195242.raw",
"SaKe2015-D20150719-T195842.raw",
