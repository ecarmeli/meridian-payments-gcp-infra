terraform {
  backend "gcs" {
    prefix = "meridian-poc/state"
  }
}