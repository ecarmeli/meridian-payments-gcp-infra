resource "google_service_account" "runtime" {
  account_id   = local.runtime_sa_account_id
  display_name = local.runtime_sa_display_name
}

resource "google_secret_manager_secret_iam_member" "db_password_accessor" {
  project   = google_secret_manager_secret.db_password.project
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "api_token_accessor" {
  project   = google_secret_manager_secret.api_token.project
  secret_id = google_secret_manager_secret.api_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "cloudsql_client" {
  project = var.gcp_project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"

  condition {
    title       = "restrict_to_postgres_instance"
    description = "Scope Cloud SQL Client access strictly to ${google_sql_database_instance.postgres.name}"
    expression  = "resource.name == \"projects/${var.gcp_project_id}/instances/${google_sql_database_instance.postgres.name}\""
  }
}
