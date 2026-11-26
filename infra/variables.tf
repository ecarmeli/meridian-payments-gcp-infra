# ==============================================================================
# Core & Application
# ==============================================================================

variable "gcp_project_id" {
  description = "GCP project ID for the Meridian Payments PoC."
  type        = string
  default     = "lightbulb-90616"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.gcp_project_id))
    error_message = "gcp_project_id must be a valid GCP project ID (6-30 lowercase letters, digits, or hyphens)."
  }
}

variable "project_name" {
  type    = string
  default = "meridian"
}

variable "environment" {
  type    = string
  default = "poc"
}

variable "gcp_region" {
  description = "GCP deployment region for regional resources."
  type        = string
  default     = "europe-west1"

  validation {
    condition     = can(regex("^[a-z]+-[a-z]+[0-9]+$", var.gcp_region))
    error_message = "gcp_region must be a valid GCP region identifier (for example, europe-west1)."
  }
}

variable "app_candidate_name" {
  description = "Candidate name returned in the GET /health JSON response."
  type        = string
  default     = "Erez Carmeli"

  validation {
    condition     = length(trimspace(var.app_candidate_name)) > 0
    error_message = "app_candidate_name must not be empty."
  }
}

variable "cloudrun_image_tag" {
  description = "Short Git SHA tag of the container image in Artifact Registry."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$", var.cloudrun_image_tag))
    error_message = "cloudrun_image_tag must be a non-empty valid OCI image tag."
  }
}

# ==============================================================================
# Network CIDRs
# ==============================================================================

variable "network_subnet_cidr" {
  description = "Primary IPv4 CIDR block for the custom VPC subnet."
  type        = string
  default     = "10.10.0.0/24"

  validation {
    condition     = can(cidrhost(var.network_subnet_cidr, 0))
    error_message = "network_subnet_cidr must be a valid IPv4 CIDR range."
  }
}

variable "network_psa_address" {
  description = "Starting IPv4 address for Private Services Access (PSA) peering allocation."
  type        = string
  default     = "10.20.0.0"

  validation {
    condition     = can(cidrhost("${var.network_psa_address}/32", 0))
    error_message = "network_psa_address must be a valid IPv4 address."
  }
}

variable "network_psa_prefix_length" {
  description = "Prefix length for the Private Services Access IP allocation."
  type        = number
  default     = 24

  validation {
    condition     = var.network_psa_prefix_length >= 16 && var.network_psa_prefix_length <= 24 && floor(var.network_psa_prefix_length) == var.network_psa_prefix_length
    error_message = "network_psa_prefix_length must be an integer between 16 and 24."
  }
}

# ==============================================================================
# Cloud SQL (PoC vs. Prod Toggles & Ephemeral Auth)
# ==============================================================================

variable "sql_tier" {
  description = "Cost-safe PoC tier; use db-custom-2-7680 + REGIONAL HA in production."
  type        = string
  default     = "db-f1-micro"

  validation {
    condition     = length(trimspace(var.sql_tier)) > 0
    error_message = "sql_tier must not be empty."
  }
}

variable "sql_availability_type" {
  description = "Cloud SQL availability mode (ZONAL for PoC; REGIONAL for production HA)."
  type        = string
  default     = "ZONAL"

  validation {
    condition     = contains(["ZONAL", "REGIONAL"], var.sql_availability_type)
    error_message = "sql_availability_type must be ZONAL or REGIONAL."
  }
}

variable "sql_backup_enabled" {
  description = "Enable automated Cloud SQL backups (false for PoC; true in production)."
  type        = bool
  default     = false
}

variable "sql_deletion_protection" {
  description = "Prevent accidental Cloud SQL instance deletion (false for PoC teardown; true in production)."
  type        = bool
  default     = false
}

variable "sql_user_password" {
  description = "Write-only password for appuser; pass via TF_VAR_sql_user_password at apply time (omitted from plans and state)."
  type        = string
  sensitive   = true
  ephemeral   = true

  validation {
    condition     = length(trimspace(var.sql_user_password)) > 0
    error_message = "sql_user_password must not be empty."
  }
}

variable "sql_user_password_version" {
  description = "Monotonic version counter for appuser write-only password; increment alongside TF_VAR_sql_user_password to rotate."
  type        = number
  default     = 1

  validation {
    condition     = var.sql_user_password_version >= 1 && floor(var.sql_user_password_version) == var.sql_user_password_version
    error_message = "sql_user_password_version must be an integer >= 1."
  }
}

variable "api_token" {
  description = "Third-party provider API token stored in Secret Manager (write-only; never persisted in state or plan files)."
  type        = string
  sensitive   = true
  ephemeral   = true

  validation {
    condition     = length(trimspace(var.api_token)) > 0
    error_message = "api_token must be a non-empty string."
  }
}

variable "api_token_version" {
  description = "Version integer for api-token secret rotation."
  type        = number
  default     = 1

  validation {
    condition     = var.api_token_version >= 1 && floor(var.api_token_version) == var.api_token_version
    error_message = "api_token_version must be an integer >= 1."
  }
}

# ==============================================================================
# Cloud Run (PoC vs. Prod Toggles & Scaling)
# ==============================================================================

variable "cloudrun_ingress" {
  description = "Ingress policy for Cloud Run. In production behind an External ALB + Cloud Armor, restrict to INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER and set default_uri_disabled = true on the service."
  type        = string
  default     = "INGRESS_TRAFFIC_ALL"

  validation {
    condition     = contains(["INGRESS_TRAFFIC_ALL", "INGRESS_TRAFFIC_INTERNAL_ONLY", "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"], var.cloudrun_ingress)
    error_message = "cloudrun_ingress must be a valid Cloud Run v2 ingress setting."
  }
}

variable "cloudrun_min_instances" {
  description = "Minimum number of Cloud Run instances (0 enables scale-to-zero for PoC)."
  type        = number
  default     = 0

  validation {
    condition     = var.cloudrun_min_instances >= 0 && floor(var.cloudrun_min_instances) == var.cloudrun_min_instances
    error_message = "cloudrun_min_instances must be an integer >= 0."
  }
}

variable "cloudrun_max_instances" {
  description = "Maximum number of Cloud Run instances."
  type        = number
  default     = 2

  validation {
    condition     = var.cloudrun_max_instances >= 1 && floor(var.cloudrun_max_instances) == var.cloudrun_max_instances
    error_message = "cloudrun_max_instances must be an integer >= 1."
  }
}

variable "cloudrun_deletion_protection" {
  description = "Prevent accidental Cloud Run service deletion (false for PoC; true in production)."
  type        = bool
  default     = false
}

variable "cloudrun_allow_unauthenticated" {
  description = "Grant allUsers roles/run.invoker. For a public payments API behind a plain External ALB + Serverless NEG (which does not mint OIDC tokens), keep IAM invocation open (allUsers or invoker_iam_disabled = true if Domain Restricted Sharing blocks allUsers) and enforce client auth at the gateway/app layer (mTLS, OAuth2/JWT); set false only when fronted by IAP or an identity-minting gateway."
  type        = bool
  default     = true
}
