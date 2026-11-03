"""The host's caller-projects locator: placement's dual (reeleehq/muvid#296)."""

import pytest

import nw
from nw.genres import _reset_caller_projects_dir


@pytest.fixture(autouse=True)
def _clean():
    _reset_caller_projects_dir()
    yield
    _reset_caller_projects_dir()


def test_no_host_means_no_directory():
    assert nw.caller_projects_dir("u@x.com") is None


def test_the_locator_is_per_caller(tmp_path):
    nw.register_caller_projects_dir(lambda caller: tmp_path / "projects" / caller)
    assert nw.caller_projects_dir("a@x.com") == tmp_path / "projects" / "a@x.com"
    assert nw.caller_projects_dir("b@x.com") == tmp_path / "projects" / "b@x.com"


def test_a_str_answer_is_a_path():
    nw.register_caller_projects_dir(lambda caller: f"/srv/{caller}")
    assert nw.caller_projects_dir("u").as_posix() == "/srv/u"


def test_one_host_per_process():
    def mine(caller):
        return f"/a/{caller}"

    nw.register_caller_projects_dir(mine)
    nw.register_caller_projects_dir(mine)  # the same one again: a no-op
    with pytest.raises(ValueError, match="already registered"):
        nw.register_caller_projects_dir(lambda caller: f"/b/{caller}")
    assert nw.caller_projects_dir("u").as_posix() == "/a/u"


def test_a_non_callable_is_refused():
    with pytest.raises(TypeError):
        nw.register_caller_projects_dir("/srv/projects")


def test_a_reloaded_module_re_registering_its_locator_is_the_same_host():
    namespace: dict = {"__name__": "host_app"}
    code = "def locate(caller):\n    return f'/srv/{caller}'\n"
    exec(code, namespace)
    first = namespace["locate"]
    exec(code, namespace)  # what importlib.reload does: a new function object
    assert namespace["locate"] is not first
    nw.register_caller_projects_dir(first)
    nw.register_caller_projects_dir(namespace["locate"])
    assert nw.caller_projects_dir("u").as_posix() == "/srv/u"


def test_a_locator_may_have_no_directory_for_a_caller():
    nw.register_caller_projects_dir(lambda caller: None if caller == "guest" else "/p")
    assert nw.caller_projects_dir("guest") is None
