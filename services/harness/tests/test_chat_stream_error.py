from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "web" / "src" / "components" / "chat-panel.tsx"
TRANSCRIPT = ROOT / "web" / "src" / "lib" / "transcript.ts"


def test_stream_error_drops_the_placeholder_and_reloads_the_persisted_transcript():
    panel = PANEL.read_text()
    transcript = TRANSCRIPT.read_text()
    assert "unsaved-" not in panel
    assert "setMessages(previous)" not in panel
    failed = panel.split("if (failed)", 1)[1].split("return !failed", 1)[0]
    assert "getChat(characterId)" in failed
    assert "transcriptAfterFailedStream" in failed
    assert 'message.id !== "streaming"' in transcript
    assert 'message.id.startsWith("unsaved-")' in transcript
