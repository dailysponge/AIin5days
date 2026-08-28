# Terraform Outputs for LogiRoute Agent

output "service_url" {
  description = "The publicly accessible URL of the deployed Cloud Run service"
  value       = google_cloud_run_v2_service.logiroute_service.uri
}

output "artifact_registry_id" {
  description = "The ID of the created Artifact Registry repository"
  value       = google_artifact_registry_repository.repo.id
}

output "service_account_email" {
  description = "The email address of the dedicated Cloud Run Service Account"
  value       = google_service_account.logiroute_sa.email
}
