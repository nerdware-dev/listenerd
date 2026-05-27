from listenerd.watcher import SessionState, SessionStateMachine


def test_initial_state_is_idle():
    sm = SessionStateMachine(cooldown_seconds=10)
    assert sm.state == SessionState.IDLE


def test_mic_on_transitions_to_recording():
    sm = SessionStateMachine(cooldown_seconds=10)
    event = sm.tick(now=100.0, mic_on=True)
    assert sm.state == SessionState.RECORDING
    assert event == "start"


def test_already_recording_no_event():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    event = sm.tick(now=101.0, mic_on=True)
    assert sm.state == SessionState.RECORDING
    assert event is None


def test_mic_off_during_recording_enters_cooldown():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    event = sm.tick(now=200.0, mic_on=False)
    assert sm.state == SessionState.COOLDOWN
    assert event is None


def test_mic_on_during_cooldown_returns_to_recording():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    sm.tick(now=200.0, mic_on=False)  # cooldown
    event = sm.tick(now=205.0, mic_on=True)
    assert sm.state == SessionState.RECORDING
    assert event is None


def test_cooldown_expires_emits_stop():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    sm.tick(now=200.0, mic_on=False)        # enter cooldown at t=200
    event = sm.tick(now=211.0, mic_on=False) # 11s later, cooldown expired
    assert sm.state == SessionState.IDLE
    assert event == "stop"


def test_session_duration_tracked():
    sm = SessionStateMachine(cooldown_seconds=10)
    sm.tick(now=100.0, mic_on=True)
    sm.tick(now=200.0, mic_on=False)
    sm.tick(now=211.0, mic_on=False)
    assert sm.last_session_duration_seconds == 100  # 200 - 100
