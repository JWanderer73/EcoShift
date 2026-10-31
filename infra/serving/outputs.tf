output "alb_dns_name" {
  value = aws_lb.main.dns_name
}

output "url" {
  description = "Dashboard at /, API at /v1/*, API docs at /docs (plain HTTP)."
  value       = "http://${aws_lb.main.dns_name}"
}
