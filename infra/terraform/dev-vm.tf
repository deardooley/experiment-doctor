# Dedicated key; private material remains on the operator machine.
resource "vultr_ssh_key" "dev" {
  name    = "experiment-doctor-dev"
  ssh_key = var.ssh_public_key
}
