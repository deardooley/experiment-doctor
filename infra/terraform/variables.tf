variable "region" {
  type = string
}
variable "plan" {
  type = string
}
variable "os_id" {
  type = number
}
variable "hostname" {
  type    = string
  default = "experiment-doctor"
}
variable "ssh_public_key" {
  type = string
}
variable "admin_cidr" {
  type = string
  validation {
    condition     = can(cidrnetmask(var.admin_cidr)) && !endswith(var.admin_cidr, "/0")
    error_message = "Provide a restricted administrator IPv4 CIDR."
  }
}
variable "release_manifest_sha256" {
  type        = string
  default     = ""
  description = "Reviewed release manifest SHA-256; non-secret deployment provenance only."
  validation {
    condition     = var.release_manifest_sha256 == "" || can(regex("^[a-f0-9]{64}$", var.release_manifest_sha256))
    error_message = "Use an empty value or a SHA-256 hex digest."
  }
}
