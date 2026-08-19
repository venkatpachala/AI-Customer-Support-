"""
voice/tests/test_voice_session.py — Unit tests for VoiceSession.

Tests:
  - normalize_auth() state transitions
  - Auth ladder: anonymous → identified → verified
  - TTFA computation (LatencyRecord)
  - begin_turn / complete_turn lifecycle
  - metrics_summary()
"""
import time
import pytest

from voice.context import VoiceSession, LatencyRecord
from voice.events import VoiceSessionStatus


class TestLatencyRecord:
    def test_ttfa_computed_correctly(self):
        rec = LatencyRecord()
        now = time.time()
        rec.t_user_turn_ended = now
        rec.t_stt_final = now + 0.3
        rec.t_runtime_start = now + 0.35
        rec.t_runtime_done = now + 1.0
        rec.t_tts_start = now + 1.05
        rec.t_first_audio = now + 1.5

        assert rec.ttfa_ms is not None
        assert abs(rec.ttfa_ms - 1500.0) < 1.0  # 1.5s = 1500ms

    def test_stt_latency_computed(self):
        rec = LatencyRecord()
        now = time.time()
        rec.t_user_turn_ended = now
        rec.t_stt_final = now + 0.4
        assert abs(rec.stt_latency_ms - 400.0) < 1.0

    def test_runtime_latency_computed(self):
        rec = LatencyRecord()
        now = time.time()
        rec.t_runtime_start = now
        rec.t_runtime_done = now + 0.8
        assert abs(rec.runtime_latency_ms - 800.0) < 1.0

    def test_ttfa_none_when_timestamps_missing(self):
        rec = LatencyRecord()
        assert rec.ttfa_ms is None
        rec.t_user_turn_ended = time.time()
        assert rec.ttfa_ms is None  # still None without t_first_audio

    def test_as_dict_keys(self):
        rec = LatencyRecord()
        d = rec.as_dict()
        assert "ttfa_ms" in d
        assert "stt_latency_ms" in d
        assert "runtime_latency_ms" in d
        assert "tts_latency_ms" in d


class TestVoiceSessionAuthLadder:
    def test_default_is_anonymous(self):
        s = VoiceSession()
        assert s.auth_level == "anonymous"
        assert s.verified is False

    def test_normalize_anonymous(self):
        s = VoiceSession(auth_level="anonymous")
        s.normalize_auth()
        assert s.auth_level == "anonymous"
        assert s.verified is False
        assert s.verified_customer is False

    def test_normalize_identified(self):
        s = VoiceSession(auth_level="identified")
        s.normalize_auth()
        assert s.auth_level == "identified"
        assert s.verified is False

    def test_normalize_verified(self):
        s = VoiceSession(auth_level="verified")
        s.normalize_auth()
        assert s.auth_level == "verified"
        assert s.verified is True

    def test_normalize_case_insensitive(self):
        s = VoiceSession(auth_level="VERIFIED")
        s.normalize_auth()
        assert s.auth_level == "verified"

    def test_normalize_unknown_falls_to_anonymous(self):
        s = VoiceSession(auth_level="superuser")
        s.normalize_auth()
        assert s.auth_level == "anonymous"
        assert s.verified is False


class TestVoiceSessionLifecycle:
    def test_initial_status_is_connecting(self):
        s = VoiceSession()
        assert s.status == VoiceSessionStatus.CONNECTING

    def test_begin_turn_sets_user_speaking(self):
        s = VoiceSession()
        s.begin_turn()
        assert s.status == VoiceSessionStatus.USER_SPEAKING

    def test_mark_turn_ended_sets_listening(self):
        s = VoiceSession()
        s.begin_turn()
        s.mark_turn_ended()
        assert s.status == VoiceSessionStatus.LISTENING
        assert s.current_latency.t_user_turn_ended is not None

    def test_mark_stt_final_sets_timestamp(self):
        s = VoiceSession()
        s.begin_turn()
        s.mark_stt_final()
        assert s.current_latency.t_stt_final is not None

    def test_mark_runtime_start_sets_processing(self):
        s = VoiceSession()
        s.mark_runtime_start()
        assert s.status == VoiceSessionStatus.PROCESSING
        assert s.current_latency.t_runtime_start is not None

    def test_mark_tts_start_sets_assistant_speaking(self):
        s = VoiceSession()
        s.mark_tts_start()
        assert s.status == VoiceSessionStatus.ASSISTANT_SPEAKING
        assert s.current_latency.t_tts_start is not None

    def test_complete_turn_increments_count(self):
        s = VoiceSession()
        s.complete_turn()
        assert s.turn_count == 1
        assert len(s.latency_history) == 1

    def test_avg_ttfa_with_multiple_turns(self):
        s = VoiceSession()
        # Simulate 2 turns with known TTFA
        for delta in [1.0, 2.0]:
            s.begin_turn()
            now = time.time()
            s.current_latency.t_user_turn_ended = now
            s.current_latency.t_first_audio = now + delta
            s.complete_turn()
        avg = s.avg_ttfa_ms()
        assert avg is not None
        assert abs(avg - 1500.0) < 10.0  # (1000 + 2000) / 2 = 1500ms

    def test_metrics_summary_keys(self):
        s = VoiceSession(tenant_id="test", customer_id="cust1")
        summary = s.metrics_summary()
        assert summary["tenant_id"] == "test"
        assert summary["customer_id"] == "cust1"
        assert "status" in summary
        assert "turn_count" in summary
        assert "interruption_count" in summary
        assert "avg_ttfa_ms" in summary
