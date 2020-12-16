package edu.colorado.cires.cmg.echofish.e2e.operations;

import com.amazonaws.services.dynamodbv2.document.DynamoDB;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import edu.colorado.cires.cmg.echofish.data.cloudformation.CloudFormationOperations;
import edu.colorado.cires.cmg.echofish.data.cloudformation.ParameterKeyValue;
import edu.colorado.cires.cmg.echofish.data.s3.S3Operations;
import edu.colorado.cires.cmg.echofish.e2e.framework.StackContext;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import org.apache.commons.lang3.RandomStringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class CreateStack {

  private static final Logger LOGGER = LoggerFactory.getLogger(CreateStack.class);

  private static final TypeReference<List<ParameterKeyValue>> LIST_PKV = new TypeReference<>() {
  };

  private final CloudFormationOperations cf;
  private final S3Operations s3;
  private final ObjectMapper objectMapper;

  public CreateStack(CloudFormationOperations cf, S3Operations s3, DynamoDB dynamoDb, ObjectMapper objectMapper) {
    this.cf = cf;
    this.s3 = s3;
    this.objectMapper = objectMapper;
  }

  public void run(String version, String cfBaseDir, String baseDir, String repoBucket, String localResources) {

    String id = String.format("test-%s", RandomStringUtils.random(8, true, true)).toLowerCase(Locale.ENGLISH);

    LOGGER.info("Creating AWS Test Resources: {}", id);

    StackContext stackContext = StackContext.Builder.configureTest(id).build();

    Path deployParams = Paths.get(baseDir).resolve("parameters").resolve("deployment-parameters.json");
    Path params = Paths.get(baseDir).resolve("parameters").resolve("echofish-parameters.json");
    List<ParameterKeyValue> deploymentParameters = getDeploymentParameters(deployParams, stackContext);
    List<ParameterKeyValue> stackParameters = getParameters(params, stackContext);

    Path targetDir = Paths.get(baseDir).resolve("target");
    writeIdFile(targetDir, id);

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

    LOGGER.info("Done Creating AWS Test Resources: {}", id);
  }





  private void writeIdFile(Path target, String id) {

    LOGGER.info("Writing ID File: {}", id);

    try {
      Path file = target.resolve("test-id.txt");
      Files.deleteIfExists(file);
      Files.writeString(file, id, StandardCharsets.UTF_8);
    } catch (IOException e) {
      throw new RuntimeException("Unable to write id file", e);
    }

    LOGGER.info("Done Writing ID File: {}", id);
  }

  private List<ParameterKeyValue> getDeploymentParameters(Path deployParams, StackContext stackContext) {
    try {
      List<ParameterKeyValue> kvs = objectMapper.readValue(deployParams.toFile(), LIST_PKV);
      kvs.addAll(getSystemProps("CFD_"));
      kvs.add(new ParameterKeyValue("StackPrefix", stackContext.getStackPrefix()));
      kvs.add(new ParameterKeyValue("DeploymentBucketName", stackContext.getDeploymentBucketName()));
      return kvs;
    } catch (IOException e) {
      throw new RuntimeException("Unable to read deployment parameters", e);
    }
  }

  private List<ParameterKeyValue> getSystemProps(String prefix) {
    List<ParameterKeyValue> keyValues = new ArrayList<>();
    System.getProperties().forEach((k,v) -> {
      if(k instanceof String && v instanceof String) {
        String key = (String) k;
        if(key.startsWith(prefix)) {
          key = key.replaceFirst(prefix, "");
          keyValues.add(new ParameterKeyValue(key, (String)v));
        }
      }
    });
    return keyValues;
  }

  private List<ParameterKeyValue> getParameters(Path paramsPath, StackContext stackContext) {
    try {
      List<ParameterKeyValue> kvs = objectMapper.readValue(paramsPath.toFile(), LIST_PKV);
      kvs.addAll(getSystemProps("CF_"));
      kvs.add(new ParameterKeyValue("StackPrefix", stackContext.getStackPrefix()));
      return kvs;
    } catch (IOException e) {
      throw new RuntimeException("Unable to read parameters", e);
    }
  }

}
