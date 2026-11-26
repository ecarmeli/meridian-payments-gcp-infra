import {
  to = google_artifact_registry_repository.repo
  id = "projects/${var.gcp_project_id}/locations/${var.gcp_region}/repositories/${local.artifact_repo_id}"
}

resource "google_artifact_registry_repository" "repo" {
  location      = var.gcp_region
  repository_id = local.artifact_repo_id
  format        = "DOCKER" # API invariant for Docker container registry
  description   = "Meridian Payments API container images"

  docker_config {
    immutable_tags = true
  }
}
