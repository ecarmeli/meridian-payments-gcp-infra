Subject: GCP PoC – Architecture Recommendations and Open Questions

Hi,

As part of the initial architecture review for the GCP PoC, we identified a few security recommendations that should be incorporated into the design, together with two questions requiring your confirmation.

## Security Recommendations

### 1. GitHub Actions Authentication

Using a static service account JSON key introduces a long-lived credential that can be compromised if not handled securely and rotated periodically.

Workload Identity Federation is the recommended solution to authenticate GitHub Actions to Google Cloud using short-lived OIDC credentials, without exporting or storing sensitive service account keys.

### 2. Dedicated Custom VPC

The default VPC in Google Cloud includes additional subnets and permissive preconfigured firewall rules, and is therefore not recommended as the foundation for this environment.

We strongly recommend provisioning a dedicated custom VPC with explicitly defined subnets and least-privilege firewall rules. This allows Cloud SQL to use Private Services Access without requiring a public IP address.

### 3. Secure Database Migration Path

To keep Cloud SQL completely unreachable from the public Internet, we recommend executing database schema migrations through an automated CI/CD job with controlled access to the private database.

If developers must run migrations directly from their laptops, an alternative can be considered using an authenticated Identity-Aware Proxy (IAP) tunnel through a controlled intermediary inside the VPC, such as a hardened migration host. This would introduce additional infrastructure and should therefore be used only if direct developer access is necessary.

## Open Questions Requiring Your Confirmation

### 1. Region and Data Residency

Are there any data-residency, regulatory, contractual, or internal policy requirements that require all resources and data to remain within the EU?

If so, is there a specific EU region we should use, such as Frankfurt (`europe-west3`) or Belgium (`europe-west1`)?

### 2. Production-Level Controls

Assuming that synthetic data will be used during the three-week PoC, should the environment include the following production-level controls?

- Cloud SQL Regional High Availability
- Cloud KMS customer-managed encryption keys

Alternatively, we can implement a lower-cost single-zone baseline using Google-managed encryption.

To protect your three-week timeline, we will proceed with our recommended baseline unless you advise otherwise.

Best regards,

Erez
