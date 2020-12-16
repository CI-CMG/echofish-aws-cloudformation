package edu.colorado.cires.cmg.echofish.e2e.framework;

public class StackContext {

  private final String deploymentStackName;
  private final String stackName;
  private final String deploymentBucketName;
  private final String stackPrefix;

  private StackContext(Builder builder) {
    deploymentStackName = builder.deploymentStackName;
    stackName = builder.stackName;
    deploymentBucketName = builder.deploymentBucketName;
    stackPrefix = builder.stackPrefix;
  }

  public String getDeploymentStackName() {
    return deploymentStackName;
  }

  public String getStackName() {
    return stackName;
  }
  
  public String getDeploymentBucketName() {
    return deploymentBucketName;
  }

  public String getStackPrefix() {
    return stackPrefix;
  }

  public static class Builder {

    private String deploymentStackName;
    private String stackName;
    private String deploymentBucketName;
    private String stackPrefix;

    public static Builder configure() {
      return new Builder();
    }

    public static Builder configureTest(String id) {
      String deploymentStackName = String.format("%s-deployment", id);
      String stackName = String.format("%s-stack", id);
      String deploymentBucketName = deploymentStackName;
      String stackPrefix = id;

      return new Builder()
          .withDeploymentBucketName(deploymentBucketName)
          .withStackName(stackName)
          .withDeploymentStackName(deploymentStackName)
          .withStackPrefix(stackPrefix);
    }

    private Builder() {

    }

    public Builder withDeploymentStackName(String deploymentStackName) {
      this.deploymentStackName = deploymentStackName;
      return this;
    }

    public Builder withStackName(String stackName) {
      this.stackName = stackName;
      return this;
    }


    public Builder withDeploymentBucketName(String deploymentBucketName) {
      this.deploymentBucketName = deploymentBucketName;
      return this;
    }

    public Builder withStackPrefix(String stackPrefix) {
      this.stackPrefix = stackPrefix;
      return this;
    }

    public StackContext build() {
      return new StackContext(this);
    }
  }
}
