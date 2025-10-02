from llmbench.config.loader import load_config

def test_load_mock_config():
    cfg = load_config("config/config_mock.yaml")
    assert cfg.metadata["experiment_name"] == "mock_quick"
    assert len(cfg.servers) == 1
    assert cfg.servers[0].name == "mock_server"
    assert any(s.name == "short_chat" for s in cfg.scenarios)

