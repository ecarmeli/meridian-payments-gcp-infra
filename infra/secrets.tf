# Both secret versions (db-password and api-token) are managed by Terraform via
# write-only secret_data_wo arguments, so secret payloads are never persisted in
# saved plan files or terraform.tfstate.

resource "google_secret_manager_secret" "db_password" {
  secret_id = local.db_password_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  secret                 = google_secret_manager_secret.db_password.id
  secret_data_wo         = var.sql_user_password
  secret_data_wo_version = var.sql_user_password_version
  deletion_policy        = "ABANDON"

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_secret_manager_secret" "api_token" {
  secret_id = local.api_token_secret_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "api_token" {
  secret                 = google_secret_manager_secret.api_token.id
  secret_data_wo         = var.api_token
  secret_data_wo_version = var.api_token_version
  deletion_policy        = "ABANDON"

  lifecycle {
    create_before_destroy = true
  }
}
