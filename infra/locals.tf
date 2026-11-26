locals {
  vpc_name                = "${var.project_name}-${var.environment}-vpc"
  subnet_name             = "${var.project_name}-${var.environment}-subnet"
  psa_range_name          = "google-managed-services-${var.project_name}-${var.environment}-vpc"
  db_password_secret_id   = "db-password"
  api_token_secret_id     = "api-token"
  runtime_sa_account_id   = "${var.project_name}-api-runtime"
  runtime_sa_display_name = "${title(var.project_name)} API Cloud Run Runtime SA"
  sql_instance_name       = "${var.project_name}-${var.environment}-pg"
  sql_database_name       = "appdb"
  sql_user_name           = "appuser"
  artifact_repo_id        = "${var.project_name}-repo"
  cloudrun_service_name   = "${var.project_name}-api"
  cloudrun_image_name     = "api"
  cloudrun_container_port = 8080
}