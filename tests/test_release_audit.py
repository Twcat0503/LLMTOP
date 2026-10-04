from scripts.check_release import blocked_path, link_errors, scan


def test_private_files_and_secrets_are_rejected_without_echoing_values():
    secret = b"synthetic-private-endpoint.invalid"
    result = scan(
        {"docs/public.md": b"Endpoint: " + secret, "AGENTS.md": b"local instructions"}, [secret]
    )
    assert len(result) == 2
    assert all(secret.decode() not in error for error in result)
    assert blocked_path("docs/M1-VALIDATION.md")
    assert blocked_path("live.local.toml")
    assert blocked_path(".remote/task.key")
    assert not blocked_path("examples/.env.example")
    assert not blocked_path("src/llmtop/cli.py")


def test_public_document_cannot_link_to_ignored_file():
    files = {
        "README.md": b"[private](docs/M1-VALIDATION.md)",
        "docs/public.md": b"[home](../README.md)",
    }
    assert link_errors(files) == ["README.md: link points outside public files"]
