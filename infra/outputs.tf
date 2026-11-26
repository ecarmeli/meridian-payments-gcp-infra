output "cloud_run_url" {
  description = "Public HTTPS URL of the Meridian Payments Cloud Run service."
  value       = google_cloud_run_v2_service.api.uri
}

output "cloud_sql_private_ip" {
  description = "Private IPv4 address of the Cloud SQL for PostgreSQL instance."
  value       = google_sql_database_instance.postgres.private_ip_address
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name (project:region:instance) used by the Cloud SQL Python Connector."
  value       = google_sql_database_instance.postgres.connection_name
}

output "runtime_service_account_email" {
  description = "Dedicated least-privilege IAM service account email used by Cloud Run."
  value       = google_service_account.runtime.email
}

output "artifact_registry_repo_url" {
  description = "Docker Artifact Registry repository URL for pushing API container images."
  value       = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${google_artifact_registry_repository.repo.repository_id}"
}
