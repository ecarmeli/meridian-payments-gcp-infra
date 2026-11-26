# Meridian Payments — GCP Landing Zone PoC

Minimal, production-shaped Google Cloud environment for Meridian Payments' EU API workload (`europe-west1`), provisioned with Terraform (`>= 1.11`) and a cross-platform Python 3 bootstrap script. See `CLARIFICATIONS.md` and `ASSUMPTIONS.md` for customer pushback and architectural assumptions.

## Architecture & Key Decisions

```
Internet ──HTTPS──▶ Cloud Run v2 (meridian-api) ──Direct VPC Egress──▶ Custom VPC (10.10.0.0/24)
                        │                                                    │ (PSA 10.20.0.0/24)
                        ├──▶ Secret Manager (db-password, api-token)         ▼
                        └──▶ Dedicated SA (meridian-api-runtime)       Cloud SQL PostgreSQL 18 (Private IP only)
```
* **Compute — Cloud Run v2 (`europe-west1`):** Selected over GKE and Compute Engine for a single stateless HTTP API. It eliminates cluster/OS patching overhead, scales automatically (`min=0, max=2`), provides managed TLS, and supports native Direct VPC Egress—matching a lean PoC while scaling cleanly to production workloads. Deployed in `europe-west1` (Belgium) to keep Lithuanian and German payment traffic inside the EU.

* **Network & Database Isolation:** Rejected the request to use the `default` VPC. Provisioned a custom regional VPC (`meridian-poc-vpc`, `10.10.0.0/24`) with Private Google Access and a Private Services Access peering block (`10.20.0.0/24`). Cloud SQL (`POSTGRES_18`, `db-f1-micro`) enforces `ipv4_enabled = false` and `ssl_mode = "ENCRYPTED_ONLY"`; Cloud Run reaches it strictly over internal routing (`PRIVATE_RANGES_ONLY`). Developer schema migrations should use the **Cloud SQL Auth Proxy** over IAM or an IAP-tunneled bastion—never a public database IP.

* **Zero-Secret Terraform State & Least-Privilege Runtime IAM:** Credentials (`api_token`, `sql_user_password`) are passed as `ephemeral = true` variables into write-only attributes (`secret_data_wo`, `password_wo`), so plaintext secrets never persist in `.tfplan` files or the versioned GCS remote state bucket (`-backend-config="bucket=..."`). Cloud Run runs under a dedicated service account (`meridian-api-runtime`) with per-secret `roles/secretmanager.secretAccessor` bindings and a conditional `roles/cloudsql.client` binding restricted strictly to the `meridian-poc-pg` instance via an IAM Condition (`resource.name == "projects/<PROJECT_ID>/instances/meridian-poc-pg"`).

* **Day-0 Bootstrap (`bootstrap_infra.py`):** Enables required APIs, creates the versioned state bucket and immutable-tag Artifact Registry (`meridian-repo`), and builds/pushes the container image tagged with `git rev-parse --short HEAD` before Terraform adopts the registry via an `import` block and deploys Cloud Run.

## How to Run

Prerequisites: `gcloud` (authenticated + ADC), `terraform >= 1.11`, and Python 3.9+.

```bash
# 1. Bootstrap APIs, GCS state bucket, Artifact Registry, and container image (defaults tag to Git short SHA)
python bootstrap_infra.py --project-id <PROJECT_ID>

# 2. Initialize remote state, review plan, and apply (prompts interactively for api_token and sql_user_password)
terraform -chdir=infra init -reconfigure -backend-config="bucket=<PROJECT_ID>-tfstate"
terraform -chdir=infra plan  -var="gcp_project_id=<PROJECT_ID>" -var="gcp_region=europe-west1" -var="cloudrun_image_tag=<GIT_SHORT_SHA>"
terraform -chdir=infra apply -var="gcp_project_id=<PROJECT_ID>" -var="gcp_region=europe-west1" -var="cloudrun_image_tag=<GIT_SHORT_SHA>"

# 3. Verify live /health contract (real DB query + live Secret Manager read)
curl -s "$(terraform -chdir=infra output -raw cloud_run_url)/health"
```

## Repository Structure
```text
meridian-payments-gcp-infra/
├── app/                       # FastAPI service, /health check & multi-stage Distroless Dockerfile
├── infra/                     # Flat domain-split Terraform root (network, database, secrets, iam, cloudrun)
├── scripts/
│   └── bootstrap_infra.py     # Idempotent GCP bootstrap & container build/push
├── CLARIFICATIONS.md          # Customer clarification email (first commit, unmodified)
├── ASSUMPTIONS.md             # Architectural decisions & rationale
├── README.md                  # Implemented architecture, run guide, AI log notes & prod delta
└── AI-LOG.md                  # Complete unedited AI session transcripts
```

## AI Tooling & Supervision

* **Tools & Share:** Used Gemini 4 Neon, Antigravity IDE agent, and Copilot Premium with GPT 6.2; AI generated Terraform, Python bootstrap, and application code under human architectural direction and manual verification.

## Key Rejections & Corrections:

  1. **Closed project-wide Cloud SQL IAM blast radius (`AI-LOG.md` & `Chat transcript - further enhancements with antigravity 2026-11-26.md`, Turn 9):** Auditing the AI-generated `iam.tf` revealed `roles/cloudsql.client` was bound at the project level, permitting `meridian-api-runtime` to open connector tunnels to *any* Cloud SQL instance in the project; I restricted the binding strictly to `meridian-poc-pg` via an IAM Condition and verified `/health` post-apply.

  2. **Eliminated plaintext secrets from Terraform state & plans (`Chat transcript - docker and terraform with antigravity 2026-11-24.md`, Turns 11–12; `Chat transcript - terraform security review.md`, Turns 1–7):** Rejected `google_sql_user.password` (which stored the plaintext DB password in `terraform.tfstate`) and refactored to `ephemeral = true` with write-only `password_wo` and `secret_data_wo` (plus `deletion_policy = "ABANDON"` on secret versions), ensuring credentials never touch `.tfplan` or GCS state.

  3. **Locked core security invariants out of `.tfvars` (`Chat transcript - docker and terraform with antigravity 2026-11-24.md`, Turns 11–12):** Rejected Antigravity's over-parameterization of ~40 settings in `variables.tf` where a variable override could weaken security, pruning to 18 toggles and hardcoding non-negotiable controls (`ipv4_enabled = false`, `ssl_mode = "ENCRYPTED_ONLY"`, `egress = "PRIVATE_RANGES_ONLY"`, `auto_create_subnetworks = false`) directly in the resource blocks.

  4. **Updated stale supply-chain dependency & added omitted security posture controls (`Chat transcript - further enhancements with antigravity 2026-11-26.md`, Turn 1; `AI-LOG.md`):** Caught an outdated PyPI dependency pin (`cloud-sql-python-connector` `1.23.0` → `1.24.0`) and added omitted production posture controls (Artifact Registry vulnerability scanning and Security Command Center) to the hardening baseline.

## Time Spent, Gaps & Production Hardening

* **Time Spent:** **[4 hours 30 minutes]** (stopped to respect the 5-hour hard budget; the optional CI/CD pipeline bonus was intentionally left out due to time).

* **What I Would Change for Production:**

  * **Edge Security:** Restrict Cloud Run ingress to `INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER`, disable the default `*.run.app` URI, and place an **External Application Load Balancer + Cloud Armor** (WAF/rate-limiting) with mTLS or OAuth2/JWT client auth in front.

  * **Database Resilience & Auth:** Upgrade Cloud SQL from zonal `db-f1-micro` to **Regional HA** with automated backups, Point-in-Time Recovery (PITR), `deletion_protection = true` to protect against destructire terraform operations, and **IAM database authentication** via the Cloud SQL Auth Proxy instead of static DB passwords.

  * **Supply Chain & Security Posture:** Enable **Artifact Registry vulnerability scanning** — ideally paired with Binary Authorization and activate **Security Command Center** for continuous posture monitoring and PCI-DSS visibility.

  * **Data Perimeter, Observability & US Expansion:** Add **VPC Service Controls** around Cloud SQL, Secret Manager, and Artifact Registry; wire Cloud Monitoring SLO alerts and Cloud Audit Log sinks; and replicate the regional stack into a US region (e.g., `us-east1`) behind Cloud DNS geo-routing if US customer expansion proceeds.