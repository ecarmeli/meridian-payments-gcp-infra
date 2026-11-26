#!/usr/bin/env python3
"""Idempotent, cross-platform GCP bootstrap script for Meridian Payments PoC.

Runs identically on Windows, macOS, Linux, and Google Cloud Shell using only
the Python 3 standard library (no virtualenv or pip packages required).

Workflow:
  1. Upfront dependency & auth pre-flight checks (gcloud, ADC, project access,
     Terraform >= 1.11, project paths, and Docker when --use-local-docker is set).
  2. Enables required GCP APIs (idempotent).
  3. Creates the versioned GCS bucket for Terraform remote state if missing.
  4. Creates the immutable-tag Artifact Registry Docker repository if missing
     (adopted automatically by Terraform's import block in infra/artifact_registry.tf).
  5. Builds and pushes the container image (via Cloud Build by default, or
     locally via Docker when --use-local-docker is passed) if the tag does not
     already exist in Artifact Registry.

Examples:
  python bootstrap_infra.py --project-id meridian-payments-515811 --image-tag v1
  python bootstrap_infra.py --project-id meridian-payments-515811 --image-tag v1 --use-local-docker
  python bootstrap_infra.py --project-id meridian-payments-515811 --image-tag v1 --check-only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Sequence, Tuple

MIN_PYTHON = (3, 9)
MIN_TERRAFORM_VERSION = (1, 11, 0)
ARTIFACT_REPO_DESCRIPTION = "Meridian Payments API container images"

BASE_REQUIRED_APIS = (
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "secretmanager.googleapis.com",
    "artifactregistry.googleapis.com",
    "run.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "storage.googleapis.com",
)

# Docker tag regex per OCI / Docker distribution spec (max 128 chars)
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")


class Colors:
    """Minimal ANSI color helper that degrades cleanly when not attached to a TTY."""

    def __init__(self) -> None:
        self.enabled = (
            callable(getattr(sys.stdout, "isatty", None)) and sys.stdout.isatty()
            and os.environ.get("NO_COLOR") is None
            and os.environ.get("TERM") != "dumb"
        )
        if self.enabled and os.name == "nt":
            # Enable VT100 processing in modern Windows terminals when possible
            os.system("")

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def cyan(self, text: str) -> str:
        return self._wrap("36", text)

    def green(self, text: str) -> str:
        return self._wrap("32", text)

    def yellow(self, text: str) -> str:
        return self._wrap("33", text)

    def red(self, text: str) -> str:
        return self._wrap("31", text)

    def dim(self, text: str) -> str:
        return self._wrap("90", text)


COLOR = Colors()


def log_step(msg: str) -> None:
    print(COLOR.cyan(f"==> {msg}"))


def log_ok(msg: str) -> None:
    print(COLOR.green(f"  [OK]   {msg}"))


def log_info(msg: str) -> None:
    print(COLOR.dim(f"  [INFO] {msg}"))


def log_warn(msg: str) -> None:
    print(COLOR.yellow(f"  [WARN] {msg}"))


def log_fail(msg: str) -> None:
    print(COLOR.red(f"  [FAIL] {msg}"))


def run_cmd(
    cmd: Sequence[str],
    *,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Execute an external command without shell=True (safe across Windows/POSIX)."""
    result = subprocess.run(
        list(cmd),
        text=True,
        capture_output=capture,
        check=False,
    )
    if check and result.returncode != 0:
        detail = ""
        if capture:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = f"\n{stderr or stdout}" if (stderr or stdout) else ""
        raise RuntimeError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}{detail}"
        )
    return result


def parse_semver(raw: str) -> Optional[Tuple[int, int, int]]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", raw)
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def format_semver(ver: Tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in ver)


def detect_gcloud_version(gcloud_bin: str) -> str:
    res = run_cmd([gcloud_bin, "version", "--format=json"], capture=True, check=False)
    if res.returncode == 0 and res.stdout:
        try:
            data = json.loads(res.stdout)
            sdk_ver = data.get("Google Cloud SDK")
            if isinstance(sdk_ver, str) and sdk_ver.strip():
                return sdk_ver.strip()
        except json.JSONDecodeError:
            pass
    return "unknown"


def detect_active_gcloud_account(gcloud_bin: str) -> str:
    res = run_cmd(
        [gcloud_bin, "auth", "list", "--filter=status:ACTIVE", "--format=json"],
        capture=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout:
        try:
            accounts = json.loads(res.stdout)
            if isinstance(accounts, list) and accounts:
                acct = accounts[0].get("account", "")
                if isinstance(acct, str):
                    return acct.strip()
        except json.JSONDecodeError:
            pass
    return ""


def detect_terraform_version(terraform_bin: str) -> Optional[Tuple[int, int, int]]:
    res = run_cmd([terraform_bin, "version", "-json"], capture=True, check=False)
    if res.returncode == 0 and res.stdout:
        try:
            data = json.loads(res.stdout)
            ver_str = data.get("terraform_version", "")
            parsed = parse_semver(ver_str)
            if parsed:
                return parsed
        except json.JSONDecodeError:
            pass

    fallback = run_cmd([terraform_bin, "version"], capture=True, check=False)
    if fallback.returncode == 0 and fallback.stdout:
        return parse_semver(fallback.stdout.splitlines()[0])
    return None


def resolve_image_tag(explicit_tag: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Return (tag, error_message). Uses explicit tag or falls back to Git short SHA."""
    if explicit_tag:
        tag = explicit_tag.strip()
        if not TAG_PATTERN.match(tag):
            return (
                None,
                f"Invalid image tag '{tag}'. Must match [A-Za-z0-9_][A-Za-z0-9._-]{{0,127}}.",
            )
        log_ok(f"Using explicit image tag: {tag}")
        return tag, None

    git_bin = shutil.which("git")
    if git_bin:
        inside = run_cmd(
            [git_bin, "rev-parse", "--is-inside-work-tree"], capture=True, check=False
        )
        if inside.returncode == 0 and inside.stdout.strip() == "true":
            sha_res = run_cmd(
                [git_bin, "rev-parse", "--short", "HEAD"], capture=True, check=False
            )
            if sha_res.returncode == 0 and sha_res.stdout.strip():
                tag = sha_res.stdout.strip()
                log_ok(f"Resolved image tag from Git HEAD: {tag}")
                dirty = run_cmd(
                    [git_bin, "status", "--porcelain"], capture=True, check=False
                )
                if dirty.stdout.strip():
                    log_warn(
                        f"Uncommitted Git changes detected; tag '{tag}' may not match final commit."
                    )
                return tag, None

    return (
        None,
        "No --image-tag provided and folder is not a Git repository. Pass --image-tag (e.g., --image-tag v1).",
    )


def run_preflight(
    args: argparse.Namespace,
) -> Tuple[str, Optional[str], str, Path, Path]:
    """Validate all local tools, auth, project access, and paths before mutating GCP."""
    log_step("Running dependency & environment pre-flight checks...")
    errors: list[str] = []

    # 1. Python runtime version
    py_ver = sys.version_info[:3]
    if sys.version_info >= MIN_PYTHON:
        log_ok(f"Python runtime found (v{format_semver(py_ver)})")
    else:
        log_fail(
            f"Python v{format_semver(py_ver)} is unsupported; Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required."
        )
        errors.append("Python version too old")

    # 2. Google Cloud SDK (gcloud), active account, ADC, and project access
    gcloud_bin = shutil.which("gcloud")
    if gcloud_bin:
        sdk_ver = detect_gcloud_version(gcloud_bin)
        log_ok(f"Google Cloud SDK found (v{sdk_ver})")

        active_account = detect_active_gcloud_account(gcloud_bin)
        if active_account:
            log_ok(f"gcloud authenticated as {active_account}")
        else:
            log_fail("No active gcloud account. Run: gcloud auth login")
            errors.append("gcloud auth login required")

        # Validate Application Default Credentials without ever printing token output
        adc_res = run_cmd(
            [gcloud_bin, "auth", "application-default", "print-access-token"],
            capture=True,
            check=False,
        )
        if adc_res.returncode == 0 and (adc_res.stdout or "").strip():
            log_ok("Application Default Credentials (ADC) configured for Terraform")
        else:
            log_fail(
                "Application Default Credentials missing or expired. "
                "Run: gcloud auth application-default login"
            )
            errors.append("gcloud auth application-default login required")

        if active_account:
            proj_res = run_cmd(
                [gcloud_bin, "projects", "describe", args.project_id],
                capture=True,
                check=False,
            )
            if proj_res.returncode == 0:
                log_ok(f"GCP project '{args.project_id}' is reachable")
            else:
                log_fail(
                    f"Cannot access GCP project '{args.project_id}'. "
                    "Verify the project ID and IAM permissions."
                )
                errors.append(f"GCP project '{args.project_id}' inaccessible")
    else:
        log_fail("Google Cloud SDK (gcloud) not found in PATH.")
        errors.append("gcloud CLI missing")

    # 3. Terraform CLI & minimum version (>= 1.11.0 for write-only secrets)
    terraform_bin = shutil.which("terraform")
    if terraform_bin:
        tf_ver = detect_terraform_version(terraform_bin)
        if tf_ver and tf_ver >= MIN_TERRAFORM_VERSION:
            log_ok(
                f"Terraform found (v{format_semver(tf_ver)} >= {format_semver(MIN_TERRAFORM_VERSION)})"
            )
        elif tf_ver:
            log_fail(
                f"Terraform v{format_semver(tf_ver)} is too old; "
                f"v{format_semver(MIN_TERRAFORM_VERSION)}+ is required for write-only secret attributes."
            )
            errors.append(f"Terraform >= {format_semver(MIN_TERRAFORM_VERSION)} required")
        else:
            log_fail("Terraform found, but its version could not be determined.")
            errors.append("Terraform version unreadable")
    else:
        log_fail(
            f"Terraform not found in PATH (v{format_semver(MIN_TERRAFORM_VERSION)}+ required)."
        )
        errors.append("terraform CLI missing")

    # 4. Docker CLI & daemon (required only when --use-local-docker is passed)
    docker_bin: Optional[str] = None
    if args.use_local_docker:
        docker_bin = shutil.which("docker")
        if docker_bin:
            info_res = run_cmd([docker_bin, "info"], capture=True, check=False)
            if info_res.returncode == 0:
                dver_res = run_cmd(
                    [docker_bin, "version", "--format", "{{.Client.Version}}"],
                    capture=True,
                    check=False,
                )
                dver = (dver_res.stdout or "").strip() or "unknown"
                log_ok(f"Docker found and daemon running (v{dver})")
            else:
                log_fail(
                    "Docker CLI found, but the Docker daemon is not running. "
                    "Start Docker or omit --use-local-docker."
                )
                errors.append("Docker daemon not running")
        else:
            log_fail(
                "Docker not found in PATH (required because --use-local-docker was set)."
            )
            errors.append("docker CLI missing")
    else:
        log_info(
            "Docker not required (using Cloud Build free tier; pass --use-local-docker to build locally)"
        )

    # 5. Local project files
    app_dir = Path(args.app_dir).resolve()
    infra_dir = Path(args.infra_dir).resolve()
    dockerfile_path = app_dir / "Dockerfile"

    if dockerfile_path.is_file():
        log_ok(f"Found Dockerfile at '{dockerfile_path}'")
    else:
        log_fail(
            f"Dockerfile not found at '{dockerfile_path}'. "
            "Run from the project root or pass --app-dir."
        )
        errors.append("Dockerfile missing")

    if infra_dir.is_dir():
        log_ok(f"Found Terraform directory at '{infra_dir}'")
    else:
        log_fail(
            f"Terraform directory not found at '{infra_dir}'. "
            "Run from the project root or pass --infra-dir."
        )
        errors.append("infra directory missing")

    # 6. Resolve and validate image tag
    image_tag, tag_err = resolve_image_tag(args.image_tag)
    if tag_err:
        log_fail(tag_err)
        errors.append("image tag invalid or missing")

    if errors:
        print()
        raise SystemExit(
            COLOR.red(
                f"Pre-flight checks failed ({len(errors)} issue(s)). "
                "Fix the [FAIL] items above and re-run."
            )
        )

    assert gcloud_bin is not None
    assert image_tag is not None
    return gcloud_bin, docker_bin, image_tag, app_dir, infra_dir


def resource_exists(gcloud_bin: str, args: Sequence[str]) -> bool:
    res = run_cmd([gcloud_bin, *args], capture=True, check=False)
    return res.returncode == 0


def ensure_apis(gcloud_bin: str, project_id: str, use_local_docker: bool) -> None:
    log_step("Ensuring required GCP APIs are enabled...")
    apis = list(BASE_REQUIRED_APIS)
    if not use_local_docker:
        apis.append("cloudbuild.googleapis.com")
    run_cmd([gcloud_bin, "services", "enable", *apis, f"--project={project_id}"])


def ensure_state_bucket(
    gcloud_bin: str, project_id: str, region: str, state_bucket: str
) -> None:
    bucket_uri = f"gs://{state_bucket}"
    desc = run_cmd(
        [
            gcloud_bin,
            "storage",
            "buckets",
            "describe",
            bucket_uri,
            f"--project={project_id}",
            "--format=json",
        ],
        capture=True,
        check=False,
    )

    if desc.returncode == 0 and desc.stdout:
        metadata = json.loads(desc.stdout)
        versioning_enabled = (
            metadata.get("versioning_enabled") is True
            or (metadata.get("versioning") or {}).get("enabled") is True
        )
        if versioning_enabled:
            print(
                COLOR.green(
                    f"==> State bucket {bucket_uri} already exists with versioning enabled; skipping."
                )
            )
            return

        log_step(
            f"State bucket {bucket_uri} exists without versioning; enabling versioning..."
        )
    else:
        log_step(f"Creating state bucket {bucket_uri}...")
        run_cmd(
            [
                gcloud_bin,
                "storage",
                "buckets",
                "create",
                bucket_uri,
                f"--project={project_id}",
                f"--location={region}",
                "--uniform-bucket-level-access",
                "--public-access-prevention",
            ]
        )

    run_cmd(
        [
            gcloud_bin,
            "storage",
            "buckets",
            "update",
            bucket_uri,
            "--versioning",
            f"--project={project_id}",
        ]
    )


def ensure_artifact_repo(
    gcloud_bin: str, project_id: str, region: str, repo_id: str
) -> None:
    if resource_exists(
        gcloud_bin,
        [
            "artifacts",
            "repositories",
            "describe",
            repo_id,
            f"--location={region}",
            f"--project={project_id}",
        ],
    ):
        print(
            COLOR.green(
                f"==> Artifact Registry repo '{repo_id}' already exists in {region}."
            )
        )
    else:
        log_step(f"Creating Artifact Registry repo '{repo_id}' in {region}...")
        run_cmd(
            [
                gcloud_bin,
                "artifacts",
                "repositories",
                "create",
                repo_id,
                "--repository-format=docker",
                f"--location={region}",
                "--immutable-tags",
                f"--description={ARTIFACT_REPO_DESCRIPTION}",
                f"--project={project_id}",
            ]
        )


def build_and_push_image(
    gcloud_bin: str,
    docker_bin: Optional[str],
    *,
    project_id: str,
    region: str,
    image_uri: str,
    image_tag: str,
    app_dir: Path,
    use_local_docker: bool,
) -> None:
    if resource_exists(
        gcloud_bin,
        ["artifacts", "docker", "images", "describe", image_uri, f"--project={project_id}"],
    ):
        print(
            COLOR.green(
                f"==> Image {image_uri} already exists in immutable Artifact Registry; skipping build."
            )
        )
        print(
            "    (Pass a new --image-tag if you want to build and push updated application code.)"
        )
        return

    if use_local_docker:
        assert docker_bin is not None
        registry_host = f"{region}-docker.pkg.dev"
        log_step(f"Configuring Docker auth for {registry_host}...")
        run_cmd([gcloud_bin, "auth", "configure-docker", registry_host, "--quiet"])

        log_step(f"Building {image_uri} locally (linux/amd64)...")
        run_cmd(
            [
                docker_bin,
                "build",
                "--platform",
                "linux/amd64",
                "--provenance=false",
                "--build-arg",
                f"COMMIT_SHA={image_tag}",
                "--build-arg",
                f"GIT_COMMIT={image_tag}",
                "-t",
                image_uri,
                str(app_dir),
            ]
        )

        log_step(f"Pushing {image_uri}...")
        run_cmd([docker_bin, "push", image_uri])
    else:
        cloudbuild_yaml = (
            "steps:\n"
            "  - name: 'gcr.io/cloud-builders/docker'\n"
            "    args:\n"
            "      - 'build'\n"
            "      - '--build-arg'\n"
            f"      - 'COMMIT_SHA={image_tag}'\n"
            "      - '--build-arg'\n"
            f"      - 'GIT_COMMIT={image_tag}'\n"
            "      - '-t'\n"
            f"      - '{image_uri}'\n"
            "      - '.'\n"
            "images:\n"
            f"  - '{image_uri}'\n"
        )
        with tempfile.TemporaryDirectory(prefix="meridian-cb-") as tmp_dir:
            cfg_path = Path(tmp_dir) / "cloudbuild.yaml"
            cfg_path.write_text(cloudbuild_yaml, encoding="utf-8", newline="\n")

            log_step(f"Building and pushing {image_uri} via Cloud Build...")
            run_cmd(
                [
                    gcloud_bin,
                    "builds",
                    "submit",
                    str(app_dir),
                    f"--project={project_id}",
                    f"--config={cfg_path}",
                ]
            )


def print_next_steps(
    *,
    project_id: str,
    region: str,
    image_tag: str,
    state_bucket: str,
    infra_dir_arg: str,
) -> None:
    system_name = platform.system()  # 'Windows', 'Darwin' (macOS), or 'Linux'
    platform_label = {
        "Windows": "Windows (PowerShell)",
        "Darwin": "macOS (zsh/bash)",
        "Linux": "Linux (bash)",
    }.get(system_name, f"{system_name} (POSIX shell)")

    print()
    print(
        f"Next ({platform_label}): review the plan and deploy with Terraform "
        "(you will be prompted interactively for api_token and sql_user_password):"
    )
    if system_name == "Windows":
        win_infra = str(Path(infra_dir_arg))
        print(
            '  New-Item -ItemType Directory -Path "$env:APPDATA\\terraform.d\\plugin-cache" -Force | Out-Null'
        )
        print('  $env:TF_PLUGIN_CACHE_DIR = "$env:APPDATA\\terraform.d\\plugin-cache"')
        print(
            f'  terraform -chdir={win_infra} init -reconfigure -backend-config="bucket={state_bucket}"'
        )
        print(f"  terraform -chdir={win_infra} plan `")
        print(f'    -var="gcp_project_id={project_id}" `')
        print(f'    -var="gcp_region={region}" `')
        print(f'    -var="cloudrun_image_tag={image_tag}"')
        print(f"  terraform -chdir={win_infra} apply `")
        print(f'    -var="gcp_project_id={project_id}" `')
        print(f'    -var="gcp_region={region}" `')
        print(f'    -var="cloudrun_image_tag={image_tag}"')
        print()
        print("Verify /health after apply:")
        print(f"  $url = terraform -chdir={win_infra} output -raw cloud_run_url")
        print('  Invoke-RestMethod "$url/health"')
    else:
        # Covers macOS ('Darwin') and Linux ('Linux')
        posix_infra = Path(infra_dir_arg).as_posix()
        print('  mkdir -p "${HOME}/.terraform.d/plugin-cache"')
        print('  export TF_PLUGIN_CACHE_DIR="${HOME}/.terraform.d/plugin-cache"')
        print(
            f'  terraform -chdir={posix_infra} init -reconfigure -backend-config="bucket={state_bucket}"'
        )
        print(f"  terraform -chdir={posix_infra} plan \\")
        print(f'    -var="gcp_project_id={project_id}" \\')
        print(f'    -var="gcp_region={region}" \\')
        print(f'    -var="cloudrun_image_tag={image_tag}"')
        print(f"  terraform -chdir={posix_infra} apply \\")
        print(f'    -var="gcp_project_id={project_id}" \\')
        print(f'    -var="gcp_region={region}" \\')
        print(f'    -var="cloudrun_image_tag={image_tag}"')
        print()
        print("Verify /health after apply:")
        print(f'  curl -i "$(terraform -chdir={posix_infra} output -raw cloud_run_url)/health"')


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Idempotent, cross-platform GCP bootstrap script for the "
            "Meridian Payments PoC."
        )
    )
    parser.add_argument(
        "-p",
        "--project-id",
        default=os.environ.get("PROJECT_ID"),
        required=os.environ.get("PROJECT_ID") is None,
        help="Target GCP project ID (or set PROJECT_ID env var).",
    )
    parser.add_argument(
        "-t",
        "--image-tag",
        default=os.environ.get("IMAGE_TAG"),
        help="Immutable container image tag (or set IMAGE_TAG; defaults to Git short SHA if in a repo).",
    )
    parser.add_argument(
        "-r",
        "--region",
        default=os.environ.get("REGION", "europe-west1"),
        help="GCP region (default: europe-west1).",
    )
    parser.add_argument(
        "--project-name",
        default=os.environ.get("PROJECT_NAME", "meridian"),
        help="Logical project prefix used for Artifact Registry repo naming (default: meridian).",
    )

    repo_root = Path(__file__).resolve().parent.parent

    parser.add_argument(
        "--app-dir",
        default=os.environ.get("APP_DIR", str(repo_root / "app")),
        help="Path to the directory containing Dockerfile (default: repo-root/app).",
    )
    parser.add_argument(
        "--infra-dir",
        default=os.environ.get("INFRA_DIR", str(repo_root / "infra")),
        help="Path to the Terraform directory (default: repo-root/infra).",
    )
    parser.add_argument(
        "--use-local-docker",
        action="store_true",
        help="Build and push the image locally with Docker instead of Cloud Build.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Run dependency and auth pre-flight checks only, without modifying GCP.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    gcloud_bin, docker_bin, image_tag, app_dir, _infra_dir = run_preflight(args)

    if args.check_only:
        print()
        print(COLOR.green("==> All pre-flight checks passed (--check-only; no GCP changes made)."))
        return 0

    repo_id = f"{args.project_name}-repo"
    state_bucket = f"{args.project_id}-tfstate"
    image_uri = f"{args.region}-docker.pkg.dev/{args.project_id}/{repo_id}/api:{image_tag}"

    print()
    log_step(
        f"Bootstrapping project={args.project_id}, region={args.region}, "
        f"repo={repo_id}, tag={image_tag}"
    )

    ensure_apis(gcloud_bin, args.project_id, args.use_local_docker)
    ensure_state_bucket(gcloud_bin, args.project_id, args.region, state_bucket)
    ensure_artifact_repo(gcloud_bin, args.project_id, args.region, repo_id)
    build_and_push_image(
        gcloud_bin,
        docker_bin,
        project_id=args.project_id,
        region=args.region,
        image_uri=image_uri,
        image_tag=image_tag,
        app_dir=app_dir,
        use_local_docker=args.use_local_docker,
    )

    print()
    print(COLOR.green(f"==> Bootstrap complete: {image_uri}"))
    print_next_steps(
        project_id=args.project_id,
        region=args.region,
        image_tag=image_tag,
        state_bucket=state_bucket,
        infra_dir_arg=args.infra_dir,
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nAborted by user.", file=sys.stderr)
        sys.exit(130)
    except RuntimeError as exc:
        print(COLOR.red(f"\nERROR: {exc}"), file=sys.stderr)
        sys.exit(1)
