package edu.colorado.cires.cmg.echofish.e2e.operations;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import edu.colorado.cires.cmg.echofish.data.cloudformation.CloudFormationOperations;
import edu.colorado.cires.cmg.echofish.data.cloudformation.ParameterKeyValue;
import edu.colorado.cires.cmg.echofish.data.s3.S3Operations;
import edu.colorado.cires.cmg.echofish.e2e.framework.StackContext;
import java.io.IOException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class UpdateStack {

  private static final Logger LOGGER = LoggerFactory.getLogger(UpdateStack.class);
  private static final TypeReference<List<ParameterKeyValue>> LIST_PKV = new TypeReference<>() {
  };


  private final S3Operations s3;
  private final CloudFormationOperations cf;
  private final ObjectMapper objectMapper;

  public UpdateStack(S3Operations s3, CloudFormationOperations cf, ObjectMapper objectMapper) {
    this.s3 = s3;
    this.cf = cf;
    this.objectMapper = objectMapper;
  }

  private String getParamValue(List<ParameterKeyValue> parameters, String key) {
    return parameters.stream()
        .filter(pkv -> pkv.getParameterKey().equals(key))
        .map(ParameterKeyValue::getParameterValue)
        .findFirst().orElse(null);
  }

  public void run(
      String deploymentParamPath,
      String stackParamPath,
      String deploymentStackName,
      String stackName,
      String cfBaseDir,
      String version,
      String repoBucket,
      String localResources) {

    List<ParameterKeyValue> deploymentParameters = getParameters(Paths.get(deploymentParamPath));
    List<ParameterKeyValue> stackParameters = getParameters(Paths.get(stackParamPath));

    if (!getParamValue(deploymentParameters, "StackPrefix").equals(getParamValue(stackParameters, "StackPrefix"))) {
      throw new IllegalStateException("StackPrefix must be the same in deployment and stack parameters");
    }

    String stackPrefix = getParamValue(deploymentParameters, "StackPrefix");
    String deploymentBucketName = getParamValue(deploymentParameters, "DeploymentBucketName");

    StackContext stackContext = StackContext.Builder.configure()
        .withStackPrefix(stackPrefix)
        .withDeploymentStackName(deploymentStackName)
        .withDeploymentBucketName(deploymentBucketName)
        .withStackName(stackName)
        .build();

    LOGGER.info("Deploying Stack: {}", stackName);

    OperationUtils.createOrUpdateStack(
        cf,
        s3,
        stackContext,
        cfBaseDir,
        version,
        deploymentParameters,
        stackParameters,
        repoBucket,
        new HashSet<>(Arrays.asList(localResources.split(","))));

    LOGGER.info("Done Deploying Stack: {}", stackName);

  }

  private List<ParameterKeyValue> getParameters(Path path) {
    try {
      return objectMapper.readValue(path.toFile(), LIST_PKV);
    } catch (IOException e) {
      throw new RuntimeException("Unable to read parameters", e);
    }
  }


}
