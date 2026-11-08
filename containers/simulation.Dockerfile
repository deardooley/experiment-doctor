# Override only with a reviewed, immutable Python image digest when upgrading.
FROM python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
USER 65532:65532
WORKDIR /tmp
# No package installation; untrusted bundles will be injected by M1 runner.
ENTRYPOINT ["python", "-I"]
