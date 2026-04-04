def test_create_and_get_session_persists_to_sqlite(client, app_module, tmp_path):
    workspace = str(tmp_path)
    create_response = client.post("/api/sessions", json={"workspace": workspace, "mode": "refactor"})
    assert create_response.status_code == 200
    payload = create_response.json()

    fetch_response = client.get(f"/api/sessions/{payload['session_id']}")
    assert fetch_response.status_code == 200
    fetched = fetch_response.json()

    assert fetched["session_id"] == payload["session_id"]
    assert fetched["workspace"] == workspace
    assert fetched["busy"] is False

    stored = app_module.get_session_record(payload["session_id"])
    assert stored is not None
    assert stored["workspace"] == workspace


def test_run_stream_saves_messages_and_streams_events(client, app_module, tmp_path, monkeypatch):
    workspace = str(tmp_path)
    create_response = client.post("/api/sessions", json={"workspace": workspace, "mode": "refactor"})
    session_id = create_response.json()["session_id"]

    async def fake_run_agent(**kwargs):
        kwargs["conversation_messages"].append({"role": "assistant", "content": "Done summary"})
        yield {"type": "thought", "content": "Working on the task"}
        yield {"type": "done", "content": "Finished", "changed_files": [], "iterations": 1}

    monkeypatch.setattr(app_module, "run_agent", fake_run_agent)

    with client.stream("POST", f"/api/sessions/{session_id}/run", json={"goal": "Write docs"}) as response:
        body = "".join(chunk.decode() if isinstance(chunk, bytes) else chunk for chunk in response.iter_text())

    assert response.status_code == 200
    assert '"type": "thought"' in body
    assert '"type": "done"' in body

    stored = app_module.get_session_record(session_id)
    assert stored["busy"] is False
    assert any(message.get("content") == "Done summary" for message in stored["messages"])


def test_approval_decision_endpoint_updates_pending_approval(client, app_module, tmp_path):
    workspace = str(tmp_path)
    create_response = client.post("/api/sessions", json={"workspace": workspace, "mode": "refactor"})
    session_id = create_response.json()["session_id"]

    session = app_module.get_session_record(session_id)
    now = app_module._utc_now()
    session["approvals"] = {
        "approval-1": {
            "tool": "run_command",
            "args": {"command": "git status"},
            "decision": None,
            "created_at": now,
            "updated_at": now,
        }
    }
    app_module.save_approval(session_id, "approval-1", "run_command", {"command": "git status"}, None, now, now)
    app_module.save_session(session)

    response = client.post(f"/api/sessions/{session_id}/approvals/approval-1", json={"decision": "approved"})
    assert response.status_code == 200
    assert response.json()["decision"] == "approved"

    approval = app_module.get_approval(session_id, "approval-1")
    assert approval["decision"] == "approved"
