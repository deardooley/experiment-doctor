FROM python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY verifiers/decay-v1/check.py verifiers/decay-v1/spec.json /verifier/
USER 65532:65532
WORKDIR /tmp
ENTRYPOINT ["python", "-I", "/verifier/check.py"]
