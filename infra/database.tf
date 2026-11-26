resource "google_sql_database_instance" "postgres" {
  name                = local.sql_instance_name
  region              = var.gcp_region
  database_version    = "POSTGRES_18"
  deletion_protection = var.sql_deletion_protection

  depends_on = [google_service_networking_connection.psa_connection]

  settings {
    edition           = "ENTERPRISE" # Explicit ENTERPRISE edition avoids costly Enterprise Plus defaults
    tier              = var.sql_tier
    availability_type = var.sql_availability_type
    disk_autoresize   = true
    disk_size         = 10

    ip_configuration {
      ipv4_enabled                                  = false # Security invariant: zero public IP exposure
      private_network                               = google_compute_network.vpc.id
      enable_private_path_for_google_cloud_services = false            # Security invariant: block unnecessary private paths from other GCP services
      ssl_mode                                      = "ENCRYPTED_ONLY" # Security invariant: enforce TLS on all DB connections
    }

    backup_configuration {
      enabled = var.sql_backup_enabled
    }
  }
}

resource "google_sql_database" "appdb" {
  name     = local.sql_database_name
  instance = google_sql_database_instance.postgres.name
}

resource "google_sql_user" "appuser" {
  name                = local.sql_user_name
  instance            = google_sql_database_instance.postgres.name
  password_wo         = var.sql_user_password
  password_wo_version = var.sql_user_password_version
  deletion_policy     = "ABANDON" # Allows clean destroy on PostgreSQL even if appuser owns objects/roles
}
