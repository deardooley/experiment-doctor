# Release carrier: services retain separate Linux identities on the host.
# Trusted source/wheels/static assets only; never a candidate execution image.
FROM python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY containers/requirements.txt /release/requirements.txt
RUN python -m pip download --only-binary=:all: --require-hashes -r /release/requirements.txt -d /release/wheels
COPY apps/api /release/apps/api
COPY services /release/services
COPY packages /release/packages
COPY experiments /release/experiments
COPY verifiers /release/verifiers
COPY scripts/doctor /release/scripts/doctor
COPY apps/web/dist /release/web
COPY infra /release/infra
USER 65532:65532
ENTRYPOINT ["/bin/false"]
