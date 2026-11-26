resource "google_compute_network" "vpc" {
  name                    = local.vpc_name
  auto_create_subnetworks = false # Security invariant: dedicated custom VPC only (never auto-mode/default VPC)
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "subnet" {
  name                     = local.subnet_name
  region                   = var.gcp_region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.network_subnet_cidr
  private_ip_google_access = true # Security invariant: reach Google APIs privately without public IPs
}

resource "google_compute_global_address" "psa_range" {
  name          = local.psa_range_name
  purpose       = "VPC_PEERING" # GCP API invariant for Private Services Access
  address_type  = "INTERNAL"    # Security invariant: internal RFC1918 peering allocation only
  prefix_length = var.network_psa_prefix_length
  address       = var.network_psa_address
  network       = google_compute_network.vpc.id
}

resource "google_service_networking_connection" "psa_connection" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com" # GCP API constant for PSA
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  deletion_policy         = "ABANDON" # Operational invariant: prevents Terraform destroy hangs on peering cleanup
}
