# Production ingress note for a public payments API behind External ALB + Cloud Armor:
#   - Set var.cloudrun_ingress = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER" and add
#     default_uri_disabled = true on this resource to disable the default *.run.app URL.
#   - Keep Cloud Run's IAM invoker check open (allUsers roles/run.invoker, or
#     invoker_iam_disabled = true if Domain Restricted Sharing blocks allUsers) because a
#     plain External ALB + Serverless NEG does not mint Google OIDC identity tokens, and
#     enforce client auth at the API gateway / application layer (mTLS, OAuth2/JWT).
#   - Set var.cloudrun_allow_unauthenticated = false behind an ALB only when fronted by
#     Identity-Aware Proxy (IAP) or an identity-minting gateway.

resource "google_cloud_run_v2_service" "api" {
  name                = local.cloudrun_service_name
  location            = var.gcp_region
  ingress             = var.cloudrun_ingress
  deletion_protection = var.cloudrun_deletion_protection

  template {
    service_account = google_service_account.runtime.email

    scaling {
      min_instance_count = var.cloudrun_min_instances
      max_instance_count = var.cloudrun_max_instances
    }

    vpc_access {
      egress = "PRIVATE_RANGES_ONLY" # Security invariant: route private RFC1918 DB traffic via Direct VPC Egress

      network_interfaces {
        network    = google_compute_network.vpc.id
        subnetwork = google_compute_subnetwork.subnet.id
      }
    }

    containers {
      image = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${google_artifact_registry_repository.repo.repository_id}/${local.cloudrun_image_name}:${var.cloudrun_image_tag}"

      ports {
        container_port = local.cloudrun_container_port
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "LOCAL_DEV"
        value = "false" # Security/runtime invariant on Cloud Run
      }

      env {
        name  = "CANDIDATE_NAME"
        value = var.app_candidate_name
      }

      env {
        name  = "GCP_REGION"
        value = var.gcp_region
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.gcp_project_id
      }

      env {
        name  = "DB_PASSWORD_SECRET_ID"
        value = google_secret_manager_secret.db_password.secret_id
      }

      env {
        name  = "API_TOKEN_SECRET_ID"
        value = google_secret_manager_secret.api_token.secret_id
      }

      env {
        name  = "CLOUD_SQL_CONNECTION_NAME"
        value = google_sql_database_instance.postgres.connection_name
      }

      env {
        name  = "DB_NAME"
        value = google_sql_database.appdb.name
      }

      env {
        name  = "DB_USER"
        value = google_sql_user.appuser.name
      }
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.cloudrun_allow_unauthenticated ? 1 : 0

  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
