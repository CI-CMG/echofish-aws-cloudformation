package edu.colorado.cires.cmg.echofish.e2e.operations;

import com.amazonaws.util.IOUtils;
import edu.colorado.cires.cmg.echofish.data.cloudformation.CloudFormationOperations;
import edu.colorado.cires.cmg.echofish.data.cloudformation.ParameterKeyValue;
import edu.colorado.cires.cmg.echofish.data.s3.S3Operations;
import edu.colorado.cires.cmg.echofish.e2e.framework.StackContext;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.Enumeration;
import java.util.List;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public final class OperationUtils {

  private static final Logger LOGGER = LoggerFactory.getLogger(OperationUtils.class);

  public static void createOrUpdateStack(
      CloudFormationOperations cf,
      S3Operations s3,
      StackContext stackContext,
      String cfBaseDir,
      String version,
      List<ParameterKeyValue> deploymentParameters,
      List<ParameterKeyValue> stackParameters,
      String repoBucket,
      Set<String> localResources
      ) {

    Path cfTargetDir = Paths.get(cfBaseDir).resolve("target");
    String name = String.format("echofish-aws-cloudformation-%s", version);
    Path bundle = cfTargetDir.resolve(String.format("%s.zip", name));
    Path bundleDir = cfTargetDir.resolve(name);

    Path csvPath = cfTargetDir.resolve("resources").resolve("resources.csv");

    if (!Files.exists(bundleDir)) {
      unzip(bundle, cfTargetDir);
    }

    if (!cf.stackExists(stackContext.getDeploymentStackName())) {
      createDeploymentStack(cf, bundleDir, stackContext, deploymentParameters);
    }

    hardSyncBucket(
        s3,
        bundleDir,
        stackContext.getDeploymentBucketName(),
        repoBucket,
        csvPath,
        localResources);

    if (!cf.stackExists(stackContext.getStackName())) {
      createStack(cf, stackContext, stackParameters);
    } else {
      updateStack(cf, stackContext, stackParameters);
    }
  }

  public static void createDeploymentStack(CloudFormationOperations cf, Path bundleDir, StackContext stackContext,
      List<ParameterKeyValue> parameters) {

    String stackName = stackContext.getDeploymentStackName();

    LOGGER.info("Creating Stack: {}", stackName);

    try {
      cf.createStackWithBodyAndWait(
          stackName,
          Files.readString(bundleDir.resolve("deploy/deployment-stack.yaml"), StandardCharsets.UTF_8),
          parameters);
    } catch (IOException e) {
      throw new RuntimeException("Unable to create deployment stack", e);
    }

    LOGGER.info("Done Creating Stack: {}", stackName);
  }

  public static void updateStack(CloudFormationOperations cf, StackContext stackContext, List<ParameterKeyValue> parameters) {

    String stackName = stackContext.getStackName();

    LOGGER.info("Updating Stack: {}", stackName);

    cf.updateStackWithUrlAndWait(
        stackName,
        String.format("https://s3.amazonaws.com/%s/stack/echofish-stack.yaml", stackContext.getDeploymentBucketName()),
        parameters);

    LOGGER.info("Done Updating Stack: {}", stackName);
  }

  public static void createStack(CloudFormationOperations cf, StackContext stackContext, List<ParameterKeyValue> parameters) {

    String stackName = stackContext.getStackName();

    LOGGER.info("Creating Stack: {}", stackName);

    cf.createStackWithUrlAndWait(
        stackName,
        String.format("https://s3.amazonaws.com/%s/stack/echofish-stack.yaml", stackContext.getDeploymentBucketName()),
        parameters);

    LOGGER.info("Done Creating Stack: {}", stackName);
  }

  public static void hardSyncBucket(
      S3Operations s3,
      Path bundleDir,
      String bucketName,
      String repoBucket,
      Path csvPath,
      Set<String> localResources
      ) {

    emptyBucket(s3, bucketName);

    LOGGER.info("Syncing {} to S3 Bucket {}", bundleDir.toString(), bucketName);

    s3.uploadDirectoryToBucket(bundleDir, bucketName);

    S3ResourceCopier copier = new S3ResourceCopier(s3, repoBucket, bucketName);
    List<S3Resource> s3Resources = null;
    try {
      s3Resources = copier.parseResources(csvPath);
    } catch (IOException e) {
      throw new RuntimeException(e);
    }
    copier.copy(s3Resources, localResources);

    LOGGER.info("Done Syncing {} to S3 Bucket {}", bundleDir.toString(), bucketName);
  }

  public static void emptyBucket(S3Operations s3, String bucketName) {

    LOGGER.info("Emptying Bucket: {}", bucketName);

    s3.deleteObjects(bucketName, s3.listObjects(bucketName));

    try {
      s3.deleteObjects(bucketName, s3.listObjects(bucketName));
    } catch (Exception e) {
      LOGGER.warn("Unable to delete bucket '{}'", bucketName, e);
    }

    LOGGER.info("Done Emptying Bucket: {}", bucketName);

  }

  public static void unzip(Path bundle, Path targetDir) {

    LOGGER.info("Unzipping CloudFormation Bundle: {}", bundle.toString());

    try (ZipFile zipFile = new ZipFile(bundle.toFile())) {
      Enumeration<? extends ZipEntry> entries = zipFile.entries();
      while (entries.hasMoreElements()) {
        ZipEntry entry = entries.nextElement();
        Path entryDestination = targetDir.resolve(entry.getName());
        if (entry.isDirectory()) {
          Files.createDirectories(entryDestination);
        } else {
          Path parent = entryDestination.getParent();
          if (parent != null && !Files.exists(parent)) {
            Files.createDirectories(parent);
          }
          try (InputStream in = zipFile.getInputStream(entry);
              OutputStream out = Files.newOutputStream(entryDestination)) {
            IOUtils.copy(in, out);
          }
        }
      }
    } catch (IOException e) {
      throw new RuntimeException("Unable to extract zip file", e);
    }

    LOGGER.info("Done Unzipping CloudFormation Bundle: {}", bundle.toString());
  }

  private OperationUtils() {

  }
}
