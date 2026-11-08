import os

import pytest

from packages.security.environment import CREDENTIALS, isolate_environment


@pytest.mark.parametrize("module,allowed", [("apps.api", {"API_SESSION_KEY", "API_OPERATOR_TOKEN"}),
                                            ("services.control", {"INFERENCE_API_KEY"}),
                                            ("services.runner", set())])
def test_role_entry_reexecs_without_other_service_credentials(monkeypatch, module, allowed):
    for name in CREDENTIALS:
        monkeypatch.setenv(name, "synthetic-not-a-real-key")
    observed = {}
    class Reexec(Exception):
        pass
    def execve(executable, argv, env):
        observed.update(env=env, argv=argv)
        raise Reexec()
    monkeypatch.setattr(os, "execve", execve)
    with pytest.raises(Reexec):
        isolate_environment(module, allowed)
    assert CREDENTIALS.intersection(observed["env"]) == allowed
    assert observed["argv"][1:3] == ["-m", module]
