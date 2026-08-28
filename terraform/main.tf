# Terraform Infrastructure as Code for LogiRoute Agent on Google Cloud Run

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# 1. Dedicated Service Account for LogiRoute Agent
resource "google_service_account" "logiroute_sa" {
  account_id   = "${var.service_name}-sa"
  display_name = "LogiRoute Agent Service Account"
  description  = "Identity for LogiRoute Cloud Run autonomous dispatch service"
}

# 2. Artifact Registry for Container Storage
resource "google_artifact_registry_repository" "repo" {
  location      = var.region
  repository_id = "${var.service_name}-repo"
  description   = "Docker container registry for LogiRoute Agent"
  format        = "DOCKER"
}

# 3. Secret Manager for Gemini API Key
resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "gemini-api-key"
  replication {
    auto {}
  }
}

# Grant Cloud Run Service Account read access to the secret
resource "google_secret_manager_secret_iam_member" "secret_access" {
  secret_id = google_secret_manager_secret.gemini_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.logiroute_sa.email}"
}

# 4. Google Cloud Run v2 Service Deployment
resource "google_cloud_run_v2_service" "logiroute_service" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.logiroute_sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.repo.repository_id}/${var.service_name}:${var.image_tag}"

      resources {
        limits = {
          cpu    = var.container_cpu
          memory = var.container_memory
        }
        cpu_idle = true
        startup_cpu_boost = true
      }

      env {
        name  = "MODEL_NAME"
        value = var.model_name
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name  = "PORT"
        value = tostring(var.container_port)
      }

      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_key.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 2
        period_seconds        = 5
        failure_threshold     = 3
        http_get {
          path = "/healthz"
          port = var.container_port
        }
      }

      liveness_probe {
        period_seconds    = 15
        timeout_seconds   = 3
        failure_threshold = 3
        http_get {
          path = "/healthz"
          port = var.container_port
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# 5. Public access IAM policy (optional / configurable)
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.logiroute_service.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
