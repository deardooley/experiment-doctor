# M0 architecture decisions

- Single Linux VM, dedicated rootless runtime: minimizes deployment overhead while separating API/model credentials from daemon access. Containers share a kernel; no hostile multitenant security claim.
- Reduced Agave contract: typed immutable jobs and future submit/status/cancel/artifacts adapter, without Agave wire compatibility or its service stack.
- Independent verifier: candidate files and numeric artifacts are untrusted; trusted specifications and verifier images are separately versioned and inaccessible to patches.
- Vultr inference: live JSON is validated before deterministic server dispatch. Native tool capability must be probed for the selected model; it is not assumed.
