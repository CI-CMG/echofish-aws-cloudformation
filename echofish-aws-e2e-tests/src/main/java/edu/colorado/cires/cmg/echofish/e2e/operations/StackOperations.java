package edu.colorado.cires.cmg.echofish.e2e.operations;

import com.amazonaws.services.cloudformation.AmazonCloudFormationClientBuilder;
import com.amazonaws.services.dynamodbv2.AmazonDynamoDBClientBuilder;
import com.amazonaws.services.dynamodbv2.document.DynamoDB;
import com.amazonaws.services.s3.AmazonS3ClientBuilder;
import com.fasterxml.jackson.databind.ObjectMapper;
import edu.colorado.cires.cmg.echofish.data.cloudformation.CloudFormationOperations;
import edu.colorado.cires.cmg.echofish.data.cloudformation.CloudFormationOperationsImpl;
import edu.colorado.cires.cmg.echofish.data.model.jackson.ObjectMapperCreator;
import edu.colorado.cires.cmg.echofish.data.s3.S3Operations;
import edu.colorado.cires.cmg.echofish.data.s3.S3OperationsImpl;
import java.util.Arrays;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;


public class StackOperations {


  private static final Logger LOGGER = LoggerFactory.getLogger(StackOperations.class);

  private static final CloudFormationOperations cf = new CloudFormationOperationsImpl(AmazonCloudFormationClientBuilder.defaultClient());
  private static final S3Operations s3 = new S3OperationsImpl(AmazonS3ClientBuilder.defaultClient());
  private static final DynamoDB dynamoDb = new DynamoDB(AmazonDynamoDBClientBuilder.defaultClient());
  private static final ObjectMapper objectMapper = ObjectMapperCreator.create();

  public static void main(String[] args) {

    LOGGER.info("{}", Arrays.toString(args));

    switch (args[0]) {
      case "create-stack": {
        String localResources = args[5];
        if (localResources == null) {
          localResources = "";
        }
        localResources = localResources.trim();
        new CreateStack(cf, s3, dynamoDb, objectMapper).run(args[1].trim(), args[2].trim(), args[3].trim(), args[4].trim(), localResources);
      }
      break;
      case "delete-stack":
        new DeleteStack(cf, s3).run(args[1]);
        break;
      case "update-stack": {
        String deploymentParamPath = args[1].trim();
        String stackParamPath = args[2].trim();
        String deploymentStackName = args[3].trim();
        String stackName = args[4].trim();
        String cfBaseDir = args[5].trim();
        String version = args[6].trim();
        String repoBucket = args[7].trim();
        String localResources = args[8];
        if (localResources == null) {
          localResources = "";
        }
        localResources = localResources.trim();
        new UpdateStack(s3, cf, objectMapper)
            .run(deploymentParamPath, stackParamPath, deploymentStackName, stackName, cfBaseDir, version, repoBucket, localResources);
      }
      break;
      default:
        throw new RuntimeException("Invalid command '" + args[0] + "'");
    }

  }

}
