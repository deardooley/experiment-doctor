terraform {
  required_version = ">= 1.5.7, < 2.0.0"
  required_providers {
    vultr = {
      source  = "vultr/vultr"
      version = "2.28.1"
    }
  }
}
provider "vultr" {} # VULTR_API_KEY from the operator environment only.
