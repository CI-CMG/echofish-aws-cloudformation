package edu.colorado.cires.cmg.echofish.e2e.operations;

import edu.colorado.cires.cmg.echofish.data.cloudformation.CloudFormationOperations;
import edu.colorado.cires.cmg.echofish.data.s3.S3Operations;
import edu.colorado.cires.cmg.echofish.e2e.framework.StackContext;
import edu.colorado.cires.cmg.echofish.e2e.framework.EchofishITUtils;
import java.nio.file.Path;
import java.nio.file.Paths;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class DeleteStack {

  private static final Logger LOGGER = LoggerFactory.getLogger(DeleteStack.class);

  private final CloudFormationOperations cf;
  private final S3Operations s3;

  public DeleteStack(CloudFormationOperations cf, S3Operations s3) {
    this.cf = cf;
    this.s3 = s3;
  }

  private void emptyBucket(String bucket) {
    try {
      OperationUtils.emptyBucket(s3, bucket);
    } catch (Exception e) {
      LOGGER.warn("Unable to empty bucket '{}'", bucket, e);
    }
  }

  public void run(String baseDir) {
    Path targetDir = Paths.get(baseDir).resolve("target");
    String id = EchofishITUtils.readId(targetDir);
    LOGGER.info("Deleting AWS Test Resources: {}", id);
    StackContext stackContext = StackContext.Builder.configureTest(id).build();
    emptyBucket(stackContext.getDeploymentBucketName());
    deleteStack(stackContext.getStackName());
    deleteStack(stackContext.getDeploymentStackName());

    LOGGER.info("Done Deleting AWS Test Resources: {}", id);
  }

  private void deleteStack(String stackName) {

    LOGGER.info("Deleting Stack: {}", stackName);

    try {
      cf.deleteStackAndWait(stackName);
    } catch (Exception e) {
      LOGGER.warn("Unable to delete stack '{}'", stackName, e);
    }

    LOGGER.info("Done Deleting Stack: {}", stackName);
  }




}
