# Terraform Variables for LogiRoute Agent

variable "project_id" {
  type        = string
  description = "The Google Cloud Project ID"
}

variable "region" {
  type        = string
  description = "The Google Cloud region for deployment"
  default     = "us-central1"
}

variable "service_name" {
  type        = string
  description = "Name of the Cloud Run service"
  default     = "logiroute-agent"
}

variable "image_tag" {
  type        = string
  description = "Container image tag to deploy"
  default     = "latest"
}

variable "model_name" {
  type        = string
  description = "Default Gemini model for ADK agents"
  default     = "gemini-2.5-flash"
}

variable "log_level" {
  type        = string
  description = "Application log level"
  default     = "INFO"
}

variable "container_port" {
  type        = number
  description = "Container listening port"
  default     = 8080
}

variable "container_cpu" {
  type        = string
  description = "CPU allocation for the container"
  default     = "1000m"
}

variable "container_memory" {
  type        = string
  description = "Memory allocation for the container"
  default     = "512Mi"
}

variable "min_instances" {
  type        = number
  description = "Minimum number of container instances"
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum number of container instances for auto-scaling"
  default     = 10
}

variable "allow_unauthenticated" {
  type        = bool
  description = "Whether to allow unauthenticated invocations of the Cloud Run service"
  default     = true
}
