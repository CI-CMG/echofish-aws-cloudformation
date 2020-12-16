package edu.colorado.cires.cmg.echofish.e2e.operations;

public class S3Resource {

  private String id;
  private String group;
  private String artifact;
  private String version;
  private String templateVersion;
  private String classifier;
  private String extension;
  private String directory;
  private String timestamp;

  public String getTimestamp() {
    return timestamp;
  }

  public void setTimestamp(String timestamp) {
    this.timestamp = timestamp;
  }

  public String getTemplateVersion() {
    return templateVersion;
  }

  public void setTemplateVersion(String templateVersion) {
    this.templateVersion = templateVersion;
  }

  public String getId() {
    return id;
  }

  public void setId(String id) {
    this.id = id;
  }

  public String getGroup() {
    return group;
  }

  public void setGroup(String group) {
    this.group = group;
  }

  public String getArtifact() {
    return artifact;
  }

  public void setArtifact(String artifact) {
    this.artifact = artifact;
  }

  public String getVersion() {
    return version;
  }

  public void setVersion(String version) {
    this.version = version;
  }

  public String getClassifier() {
    return classifier;
  }

  public void setClassifier(String classifier) {
    this.classifier = classifier;
  }

  public String getExtension() {
    return extension;
  }

  public void setExtension(String extension) {
    this.extension = extension;
  }

  public String getDirectory() {
    return directory;
  }

  public void setDirectory(String directory) {
    this.directory = directory;
  }

  @Override
  public String toString() {
    return "S3Resource{" +
        "id='" + id + '\'' +
        ", group='" + group + '\'' +
        ", artifact='" + artifact + '\'' +
        ", version='" + version + '\'' +
        ", templateVersion='" + templateVersion + '\'' +
        ", classifier='" + classifier + '\'' +
        ", extension='" + extension + '\'' +
        ", directory='" + directory + '\'' +
        ", timestamp='" + timestamp + '\'' +
        '}';
  }
}
