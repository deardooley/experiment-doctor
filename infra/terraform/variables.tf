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
