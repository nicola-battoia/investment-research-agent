def pytest_addoption(parser):
    parser.addoption(
        "--qa-live",
        action="store_true",
        help="Run explicit rollback-based live QA permission probes",
    )
