package edu.colorado.cires.cmg.echofish.e2e.operations;

import edu.colorado.cires.cmg.echofish.data.s3.S3Operations;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.apache.commons.csv.CSVFormat;
import org.apache.commons.csv.CSVParser;
import org.apache.commons.csv.CSVRecord;
import org.apache.commons.io.input.BOMInputStream;
import org.apache.commons.lang3.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class S3ResourceCopier {

  private static final Logger LOGGER = LoggerFactory.getLogger(S3ResourceCopier.class);

  private final S3Operations s3;
  private final String repositoryBucket;
  private final String deploymentBucket;

  public S3ResourceCopier(S3Operations s3, String repositoryBucket, String deploymentBucket) {
    this.s3 = s3;
    this.repositoryBucket = repositoryBucket;
    this.deploymentBucket = deploymentBucket;

  }

  private String getValue(CSVRecord record, Map<String, Integer> header, String key) {
    String value = record.get(header.get(key));
    if (value != null) {
      return value.trim();
    }
    return null;
  }

  private String getTemplateVersion(String version, String timestamp) {
    if (version.endsWith("-SNAPSHOT")) {
      return version + timestamp;
    }
    return version;
  }

  public List<S3Resource> parseResources(Path csvPath) throws IOException {
    List<S3Resource> s3Resources = new ArrayList<>();
    try (CSVParser parser = CSVParser.parse(new BOMInputStream(Files.newInputStream(csvPath)), StandardCharsets.UTF_8, CSVFormat.RFC4180)) {
      int row = 0;
      Map<String, Integer> header = new HashMap<>();
      for (CSVRecord record : parser) {
        if (row++ == 0) {
          int i = 0;
          for (String value : record) {
            header.put(value, i++);
          }
        } else {
          S3Resource s3Resource = new S3Resource();
          s3Resource.setId(getValue(record, header, "id"));
          s3Resource.setGroup(getValue(record, header, "group"));
          s3Resource.setArtifact(getValue(record, header, "artifact"));
          s3Resource.setVersion(getValue(record, header, "version"));
          s3Resource.setClassifier(getValue(record, header, "classifier"));
          s3Resource.setExtension(getValue(record, header, "extension"));
          s3Resource.setDirectory(getValue(record, header, "directory"));
          s3Resource.setTimestamp(getValue(record, header, "timestamp"));
          s3Resource.setTemplateVersion(getTemplateVersion(s3Resource.getVersion(), s3Resource.getTimestamp()));
          s3Resources.add(s3Resource);
        }
      }
    }
    return s3Resources;
  }

  private String suffix(S3Resource s3Resource) {
    return (s3Resource.getClassifier().equals("jar") ? "" : "-" + s3Resource.getClassifier()) + "." + s3Resource.getExtension();
  }

  private String resolveRepositoryPath(S3Resource s3Resource) {
    String start = s3Resource.getVersion().endsWith("-SNAPSHOT") ? "snapshot" : "release";
    Path path = Paths.get(start, s3Resource.getGroup().split("\\."));
    path = path.resolve(s3Resource.getArtifact()).resolve(s3Resource.getVersion());
    List<String> artifacts = s3.listObjects(repositoryBucket, path.toString());
    Collections.sort(artifacts);
    Collections.reverse(artifacts);
    for(String artifact : artifacts) {
      String fileName = Paths.get(artifact).getFileName().toString();
      if(fileName.startsWith(s3Resource.getArtifact() + "-") && fileName.endsWith(suffix(s3Resource))) {
        return artifact;
      }
    }
    return null;
  }

  private String resolveDeploymentPath(S3Resource s3Resource) {
    Path path;
    if(StringUtils.isBlank(s3Resource.getDirectory())) {
      path = Paths.get("");
    } else {
      path = Paths.get(s3Resource.getDirectory());
    }
    path = path.resolve(s3Resource.getArtifact() + "-" + s3Resource.getTemplateVersion() + suffix(s3Resource));
    return path.toString();
  }

  public void copy(List<S3Resource> s3Resources, Set<String> localResources) {
    for (S3Resource s3Resource : s3Resources) {
      String id = s3Resource.getId();
      if(localResources.contains(id)) {
        throw new UnsupportedOperationException("Not supported yet");
      } else {
        String repoPath = resolveRepositoryPath(s3Resource);
        String deploymentPath = resolveDeploymentPath(s3Resource);
        LOGGER.info("Copying S3 resource: {}/{} to {}/{}", repositoryBucket, repoPath, deploymentBucket, deploymentPath);
        s3.copyObject(repositoryBucket, repoPath, deploymentBucket, deploymentPath);
      }
    }
  }



}
