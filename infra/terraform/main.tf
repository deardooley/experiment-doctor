resource "vultr_firewall_group" "demo" {
  description = "Experiment Doctor"
}
resource "vultr_firewall_rule" "web" {
  for_each          = toset(["80", "443"])
  firewall_group_id = vultr_firewall_group.demo.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = "0.0.0.0"
  subnet_size       = 0
  port              = each.value
}
resource "vultr_firewall_rule" "ssh" {
  firewall_group_id = vultr_firewall_group.demo.id
  protocol          = "tcp"
  ip_type           = "v4"
  subnet            = cidrhost(var.admin_cidr, 0)
  subnet_size       = tonumber(split("/", var.admin_cidr)[1])
  port              = "22"
}
resource "vultr_instance" "demo" {
  region            = var.region
  plan              = var.plan
  os_id             = var.os_id
  label             = "experiment-doctor"
  hostname          = var.hostname
  enable_ipv6       = false
  ssh_key_ids       = [vultr_ssh_key.dev.id]
  firewall_group_id = vultr_firewall_group.demo.id
  user_data         = file("${path.module}/../cloud-init/bootstrap.yaml")
}
output "ipv4" {
  value = vultr_instance.demo.main_ip
}
